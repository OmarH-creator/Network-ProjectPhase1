import socket
import csv
import argparse
import time
from datetime import datetime, timedelta
from collections import deque, OrderedDict, defaultdict
from protocol_M_M import decode_packet, MSG_INIT, MSG_DATA, MSG_HEARTBEAT, SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT

# Try to import psutil for CPU monitoring, fallback if not available
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[WARNING] psutil not available - CPU monitoring disabled")


class Server:
    def __init__(self, port, log_file, max_buffer_size=100, max_gap_wait_seconds=5, auto_shutdown_timeout=None):
        self.port = port
        self.log_file = log_file
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packet_count = 0

        # Configuration
        self.max_buffer_size = max_buffer_size
        self.max_gap_wait_seconds = max_gap_wait_seconds
        
        # Auto-shutdown feature
        self.auto_shutdown_timeout = auto_shutdown_timeout
        self.last_packet_time = None

        # Metrics tracking
        self.start_time = None
        self.total_bytes_received = 0
        self.packets_received = 0
        self.duplicate_count = 0
        self.sequence_gaps = 0
        self.cpu_times = []

        # Per-device tracking for duplicate and gap detection
        self.device_states = defaultdict(lambda: {
            'last_seq': -1,
            'packets': 0,
            'duplicates': 0,
            'gaps': 0,
            'bytes': 0,
            'buffer': OrderedDict(),
            'last_values': None,
            'gap_start_time': None,
            'last_heartbeat': None,
            'expected_hb_interval': 5.0
        })

        # Batch details CSV file
        self.batch_details_file = log_file.replace('.csv', '_batch_details.csv')
        self.batch_details_writer = None
        self.batch_details_file_handle = None

        # Process for CPU monitoring (if available)
        self.process = None
        self.psutil_available = PSUTIL_AVAILABLE
        if self.psutil_available:
            try:
                self.process = psutil.Process(os.getpid())
            except Exception:
                self.psutil_available = False

        # File handles
        self.telemetry_file = None

    def run(self):
        self.sock.bind(('0.0.0.0', self.port))
        self.sock.settimeout(1.0)  # Timeout for cleanup checks

        print(f"[SERVER] Listening on port {self.port}")
        print(f"[CONFIG] Max buffer size: {self.max_buffer_size} packets per device")
        print(f"[CONFIG] Max gap wait time: {self.max_gap_wait_seconds} seconds")
        if self.auto_shutdown_timeout:
            print(f"[CONFIG] Auto-shutdown after {self.auto_shutdown_timeout}s of no packets")

        # Start metrics collection
        self.start_time = time.time()

        # Initialize batch details CSV
        self.initialize_batch_details_csv()

        with open(self.log_file, 'w', newline='', encoding='utf-8') as f:

            self.telemetry_file = f
            writer = csv.writer(f)

            writer.writerow(['Timestamp', 'Precise_Time', 'Device_ID', 'Seq_Num', 'Msg_Type', 'Temp_C', 'Humid_Pct', 'Volt_V'])
            self.telemetry_file.flush()

            try:
                while True:
                    try:
                        # Measure CPU time for this packet
                        cpu_start = time.perf_counter()
                        data, addr = self.sock.recvfrom(1024)
                        arrival_time = time.time()  # Capture precise arrival time immediately
                        self.packet_count += 1
                        self.last_packet_time = arrival_time  # Update last packet time
                        
                        # Update metrics
                        packet_size = len(data)
                        self.total_bytes_received += packet_size
                        self.packets_received += 1
                        
                        try:
                            packet = decode_packet(data)
                            timestamp = datetime.now()
                            
                            # Update device state metrics (device_state created automatically by defaultdict)
                            
                            self._process_telemetry(packet, timestamp, arrival_time, writer)
                            
                            # Measure CPU time for this packet (basic timing)
                            cpu_end = time.perf_counter()
                            cpu_time_ms = (cpu_end - cpu_start) * 1000
                            self.cpu_times.append(cpu_time_ms)

                            if self.packet_count % 100 == 0:
                                self._cleanup_old_buffers(timestamp, writer)
                            
                            # Print periodic metrics (every 50 packets)
                            if self.packet_count % 50 == 0:
                                current_metrics = self.calculate_metrics()
                                print(f"[METRICS] Packets: {current_metrics['packets_received']}, "
                                      f"Avg size: {current_metrics['bytes_per_report']:.1f}B, "
                                      f"Duplicates: {current_metrics['duplicate_rate']:.2f}%, "
                                      f"Gaps: {current_metrics['sequence_gap_count']}, "
                                      f"CPU: {current_metrics['cpu_ms_per_report']:.3f}ms/pkt")
                        except Exception as e:
                            print(f"[ERROR] Decode failed: {e}")

                    except socket.timeout:
                        # Check for auto-shutdown
                        if self.auto_shutdown_timeout and self.last_packet_time:
                            time_since_last = time.time() - self.last_packet_time
                            if time_since_last >= self.auto_shutdown_timeout:
                                print(f"\n[SERVER] Auto-shutdown: No packets for {self.auto_shutdown_timeout}s")
                                break
                        self._cleanup_old_buffers(datetime.now(), writer)
                        continue

            except KeyboardInterrupt:
                print(f"\n[SERVER] Shutting down...")

        # Finalize and save metrics
        self.finalize_and_save_metrics()
        self.sock.close()

    def _process_telemetry(self, packet, timestamp, arrival_time, writer):
        timestamp_str = datetime.fromtimestamp(arrival_time).strftime('%Y-%m-%d %H:%M:%S.%f')
        precise_time = f"{arrival_time:.6f}"  # Unix timestamp with 6 decimal places

        # Device state is automatically created by defaultdict

        device_state = self.device_states[packet.device_id]
        buffer = device_state['buffer']
        current_seq = packet.seq_num
        last_seq = device_state['last_seq']

        # --- INIT Message ---
        if packet.msg_type != MSG_DATA:
            if packet.msg_type == MSG_INIT:
                print(f"[{self.packet_count}] INIT device {packet.device_id}")
                device_state['last_seq'] = packet.seq_num
                device_state['last_values'] = None  # Reset values
                device_state['gap_start_time'] = None

                writer.writerow([timestamp_str, precise_time, packet.device_id, packet.seq_num, 'INIT', '<null>', '<null>', '<null>'])
                self.telemetry_file.flush()

                self._process_buffered_packets(packet.device_id, timestamp, writer)
                return

            if packet.msg_type == MSG_HEARTBEAT:
                print(f"[{self.packet_count}] HEARTBEAT device {packet.device_id}")
                device_state['last_seq'] = packet.seq_num
                device_state['last_values'] = None  # Reset values
                device_state['gap_start_time'] = None
                
                # Log HEARTBEAT to main CSV (like old server)
                writer.writerow([timestamp_str, precise_time, packet.device_id, packet.seq_num, 'HEARTBEAT', '<null>', '<null>', '<null>'])
                self.telemetry_file.flush()


        else:
            # --- DATA Message ---
            # 1. Duplicate Check
            if current_seq <= last_seq:
                print(f"[{self.packet_count}] DATA {packet.device_id} seq={current_seq} [DUPLICATE]")
                device_state['duplicates'] += 1
                self.duplicate_count += 1
                self._log_data_packet(packet, timestamp_str, precise_time, writer, True, False)
                return

            # 2. In-Order Check
            if current_seq == last_seq + 1:
                print(f"[{self.packet_count}] DATA {packet.device_id} seq={current_seq} [IN-ORDER]")
                self._log_data_packet(packet, timestamp_str, precise_time, writer, False, False)

                # Update last_values for interpolation
                device_state['last_values'] = self._get_packet_values(packet)
                device_state['last_seq'] = current_seq
                device_state['gap_start_time'] = None

                self._process_buffered_packets(packet.device_id, timestamp, writer)
                return

            # 3. Gap Detected
            # Check Timeout Logic
            if device_state['gap_start_time'] is not None:
                gap_age = (timestamp - device_state['gap_start_time']).total_seconds()
                if gap_age > self.max_gap_wait_seconds:
                    # TIMEOUT: We waited too long. We must fill the gap NOW.
                    print(f"[TIMEOUT] Filling gap after seq={last_seq}")

                    # Determine the 'End' of the gap.
                    # It is either the first packet in buffer OR the current packet.
                    if buffer:
                        next_avail_seq = next(iter(buffer))
                        next_packet = buffer[next_avail_seq]['packet']
                    else:
                        next_avail_seq = current_seq
                        next_packet = packet

                    # Interpolate from last_seq to next_avail_seq
                    start_vals = device_state['last_values']
                    end_vals = self._get_packet_values(next_packet)

                    gap_size = next_avail_seq - last_seq - 1
                    device_state['gaps'] += gap_size
                    self.sequence_gaps += gap_size

                    self._interpolate_and_log(packet.device_id, last_seq, next_avail_seq,
                                              start_vals, end_vals, timestamp_str, writer)

                    # Advance state to just before the next available packet
                    device_state['last_seq'] = next_avail_seq - 1
                    device_state['gap_start_time'] = None

                    # Now process the buffered packets (or current) naturally
                    if current_seq == device_state['last_seq'] + 1:
                        # Current packet is now next
                        self._log_data_packet(packet, timestamp_str, precise_time, writer, False, False)
                        device_state['last_values'] = self._get_packet_values(packet)
                        device_state['last_seq'] = current_seq
                    else:
                        # Check buffer
                        self._process_buffered_packets(packet.device_id, timestamp, writer)

                    # If current packet is still a gap relative to the NEW position, buffer it
                    if current_seq > device_state['last_seq'] + 1:
                        self._add_to_buffer(packet, timestamp, timestamp_str, precise_time, device_state)
                    return

            # 4. Buffer the packet (Wait)
            self._add_to_buffer(packet, timestamp, timestamp_str, precise_time, device_state)

    def _add_to_buffer(self, packet, timestamp, timestamp_str, precise_time, device_state):
        buffer = device_state['buffer']
        current_seq = packet.seq_num

        if len(buffer) >= self.max_buffer_size:
            buffer.pop(next(iter(buffer)))

        buffer[current_seq] = {
            'packet': packet,
            'timestamp': timestamp_str,
            'precise_time': precise_time,
            'arrival_time': timestamp,
            'logged': False
        }
        device_state['buffer'] = OrderedDict(sorted(buffer.items()))
        print(f"[BUFFERED] Device {packet.device_id}: seq={current_seq}")

        if device_state['gap_start_time'] is None:
            device_state['gap_start_time'] = timestamp

    def initialize_batch_details_csv(self):
        """Initialize the batch details CSV file"""
        try:
            self.batch_details_file_handle = open(self.batch_details_file, 'w', newline='', encoding='utf-8')
            self.batch_details_writer = csv.writer(self.batch_details_file_handle)
            # Write header for batch details
            self.batch_details_writer.writerow([
                'Batch_Timestamp', 'Device_ID', 'Seq_Num', 'Batch_Size', 'Reading_Index', 
                'Sensor_Type', 'Value', 'Unit', 'Batch_Avg', 'Batch_Min', 'Batch_Max'
            ])
            print(f"[SERVER] Batch details logging to: {self.batch_details_file}")
        except Exception as e:
            print(f"[WARNING] Could not create batch details file: {e}")
            self.batch_details_writer = None

    def log_batch_details(self, timestamp, device_id, seq_num, readings):
        """Log individual readings from a batch to the batch details CSV"""
        if not self.batch_details_writer or not readings:
            return
        
        from collections import defaultdict
        
        # Group readings by sensor type for batch statistics
        sensor_groups = defaultdict(list)
        for reading in readings:
            sensor_groups[reading.sensor_type].append(reading.value)
        
        # Log each reading with batch context
        for i, reading in enumerate(readings):
            sensor_type_name = {
                SENSOR_TEMP: 'TEMPERATURE',
                SENSOR_HUM: 'HUMIDITY', 
                SENSOR_VOLT: 'VOLTAGE'
            }.get(reading.sensor_type, f'UNKNOWN_{reading.sensor_type}')
            
            unit = {
                SENSOR_TEMP: '°C',
                SENSOR_HUM: '%',
                SENSOR_VOLT: 'V'
            }.get(reading.sensor_type, '')
            
            # Calculate batch statistics for this sensor type
            sensor_values = sensor_groups[reading.sensor_type]
            batch_avg = sum(sensor_values) / len(sensor_values)
            batch_min = min(sensor_values)
            batch_max = max(sensor_values)
            
            self.batch_details_writer.writerow([
                timestamp, device_id, seq_num, len(readings), i + 1,
                sensor_type_name, f"{reading.value:.3f}", unit,
                f"{batch_avg:.3f}", f"{batch_min:.3f}", f"{batch_max:.3f}"
            ])
        
        # Flush to ensure data is written
        if self.batch_details_file_handle:
            self.batch_details_file_handle.flush()

    def _process_buffered_packets(self, device_id, timestamp, writer):
        device_state = self.device_states[device_id]
        buffer = device_state['buffer']
        last_seq = device_state['last_seq']

        while buffer:
            next_seq = next(iter(buffer))
            if next_seq == last_seq + 1:
                item = buffer.pop(next_seq)
                print(f"[REORDER] releasing seq={next_seq}")
                self._log_data_packet(item['packet'], item['timestamp'], item['precise_time'], writer, False, False)

                # Update state
                device_state['last_values'] = self._get_packet_values(item['packet'])
                device_state['last_seq'] = next_seq
                last_seq = next_seq
            else:
                break

        if not buffer:
            device_state['gap_start_time'] = None

    def _cleanup_old_buffers(self, current_time, writer):
        for device_id, state in self.device_states.items():
            buffer = state['buffer']
            if not buffer: continue

            oldest = buffer[next(iter(buffer))]
            if (current_time - oldest['arrival_time']).total_seconds() > self.max_gap_wait_seconds * 2:
                print(f"[CLEANUP] Force filling gap for device {device_id}")

                # Force fill gap up to the first buffered packet
                first_buff_seq = next(iter(buffer))
                first_buff_packet = buffer[first_buff_seq]['packet']

                start_vals = state['last_values']
                end_vals = self._get_packet_values(first_buff_packet)

                self._interpolate_and_log(device_id, state['last_seq'], first_buff_seq,
                                          start_vals, end_vals, oldest['timestamp'], writer)

                state['last_seq'] = first_buff_seq - 1
                self._process_buffered_packets(device_id, current_time, writer)

    # --- NEW HELPER: Get Values (T, H, V) based on sensor type ---
    def _get_packet_values(self, packet):
        # Initialize all values as None (will be <null> in CSV)
        temp = None
        humid = None
        volt = None
        
        # Extract sensor values by type (not by position)
        for reading in packet.readings:
            if reading.sensor_type == SENSOR_TEMP:
                temp = reading.value
            elif reading.sensor_type == SENSOR_HUM:
                humid = reading.value
            elif reading.sensor_type == SENSOR_VOLT:
                volt = reading.value
        
        return (temp, humid, volt)

    # --- NEW HELPER: Linear Interpolation ---
    def _interpolate_and_log(self, device_id, start_seq, end_seq, start_vals, end_vals, timestamp_str, writer):
        count = end_seq - start_seq - 1
        if count <= 0: return

        # Handle edge case: missing start values (first packet lost)
        if start_vals is None: start_vals = end_vals

        print(f"   >>> Estimating {count} packets (Seq {start_seq + 1} to {end_seq - 1})")

        # Calculate steps
        step_t = (end_vals[0] - start_vals[0]) / (count + 1)
        step_h = (end_vals[1] - start_vals[1]) / (count + 1)
        step_v = (end_vals[2] - start_vals[2]) / (count + 1)

        current_vals = list(start_vals)

        for i in range(count):
            seq = start_seq + 1 + i
            current_vals[0] += step_t
            current_vals[1] += step_h
            current_vals[2] += step_v

            # Log Estimated Packet (interpolated values)
            temp_str = f"{current_vals[0]:.2f}" if current_vals[0] is not None else '<null>'
            humid_str = f"{current_vals[1]:.2f}" if current_vals[1] is not None else '<null>'
            volt_str = f"{current_vals[2]:.2f}" if current_vals[2] is not None else '<null>'
            
            writer.writerow([
                timestamp_str, f"{time.time():.6f}", device_id, seq, 'DATA',
                temp_str, humid_str, volt_str
            ])

        if self.telemetry_file: self.telemetry_file.flush()

    def _log_data_packet(self, packet, timestamp_str, precise_time, writer, is_dup, is_gap):
        temp, humid, volt = self._get_packet_values(packet)
        
        # Determine if this is a batch (multiple readings) or single reading
        is_batch = len(packet.readings) > 1
        
        if is_batch:
            # Log individual readings to batch details CSV
            self.log_batch_details(timestamp_str, packet.device_id, packet.seq_num, packet.readings)
            
            # Calculate averages for main CSV
            from collections import defaultdict
            sensor_sums = defaultdict(list)
            
            # Group readings by sensor type
            for reading in packet.readings:
                sensor_sums[reading.sensor_type].append(reading.value)
            
            # Calculate averages
            temp_avg = sum(sensor_sums[SENSOR_TEMP]) / len(sensor_sums[SENSOR_TEMP]) if SENSOR_TEMP in sensor_sums else None
            humid_avg = sum(sensor_sums[SENSOR_HUM]) / len(sensor_sums[SENSOR_HUM]) if SENSOR_HUM in sensor_sums else None
            volt_avg = sum(sensor_sums[SENSOR_VOLT]) / len(sensor_sums[SENSOR_VOLT]) if SENSOR_VOLT in sensor_sums else None
            
            # Use averages for main CSV
            temp_str = f"{temp_avg:.2f}" if temp_avg is not None else '<null>'
            humid_str = f"{humid_avg:.2f}" if humid_avg is not None else '<null>'
            volt_str = f"{volt_avg:.2f}" if volt_avg is not None else '<null>'
        else:
            # Single reading - format values
            temp_str = f"{temp:.2f}" if temp is not None else '<null>'
            humid_str = f"{humid:.2f}" if humid is not None else '<null>'
            volt_str = f"{volt:.2f}" if volt is not None else '<null>'
        
        writer.writerow([
            timestamp_str, precise_time, packet.device_id, packet.seq_num, 'DATA',
            temp_str, humid_str, volt_str
        ])
        if self.telemetry_file: self.telemetry_file.flush()

    def calculate_metrics(self):
        """Calculate all required Phase 2 metrics"""
        if self.start_time is None:
            return {}
        
        duration = time.time() - self.start_time
        
        # Calculate bytes per report (average packet size)
        bytes_per_report = self.total_bytes_received / self.packets_received if self.packets_received > 0 else 0
        
        # Calculate duplicate rate as percentage
        duplicate_rate = (self.duplicate_count / self.packets_received * 100) if self.packets_received > 0 else 0
        
        # Calculate CPU time per report (average) - use basic timing if psutil not available
        if self.psutil_available and self.cpu_times:
            cpu_ms_per_report = sum(self.cpu_times) / len(self.cpu_times)
        else:
            # Fallback: estimate CPU time from packet processing
            cpu_ms_per_report = (duration * 1000) / self.packets_received if self.packets_received > 0 else 0
        
        return {
            'bytes_per_report': bytes_per_report,
            'packets_received': self.packets_received,
            'duplicate_rate': duplicate_rate,
            'sequence_gap_count': self.sequence_gaps,
            'cpu_ms_per_report': cpu_ms_per_report,
            'duration_seconds': duration,
            'packets_per_second': self.packets_received / duration if duration > 0 else 0,
            'bytes_per_second': self.total_bytes_received / duration if duration > 0 else 0
        }

    def write_metrics_to_csv(self):
        """Append metrics to the end of the CSV file"""
        metrics = self.calculate_metrics()
        
        if not metrics:
            return
        
        # Append metrics to the CSV file
        with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Add separator rows
            writer.writerow(['', '', '', '', '', '', '', ''])
            writer.writerow(['=== PHASE 2 METRICS REPORT ===', '', '', '', '', '', '', ''])
            writer.writerow(['', '', '', '', '', '', '', ''])
            
            # Required Phase 2 metrics
            writer.writerow(['METRIC', 'VALUE', 'UNIT', '', '', '', '', ''])
            writer.writerow(['bytes_per_report', f"{metrics['bytes_per_report']:.2f}", 'bytes', '', '', '', '', ''])
            writer.writerow(['packets_received', metrics['packets_received'], 'count', '', '', '', '', ''])
            writer.writerow(['duplicate_rate', f"{metrics['duplicate_rate']:.3f}", 'percent', '', '', '', '', ''])
            writer.writerow(['sequence_gap_count', metrics['sequence_gap_count'], 'count', '', '', '', '', ''])
            cpu_note = " (estimated)" if not self.psutil_available else ""
            writer.writerow(['cpu_ms_per_report', f"{metrics['cpu_ms_per_report']:.3f}", f'milliseconds{cpu_note}', '', '', '', '', ''])
            
            # Additional performance metrics
            writer.writerow(['', '', '', '', '', '', '', ''])
            writer.writerow(['=== ADDITIONAL METRICS ===', '', '', '', '', '', '', ''])
            writer.writerow(['duration_seconds', f"{metrics['duration_seconds']:.1f}", 'seconds', '', '', '', '', ''])
            writer.writerow(['packets_per_second', f"{metrics['packets_per_second']:.1f}", 'packets/sec', '', '', '', '', ''])
            writer.writerow(['bytes_per_second', f"{metrics['bytes_per_second']:.1f}", 'bytes/sec', '', '', '', '', ''])
            writer.writerow(['total_bytes_received', self.total_bytes_received, 'bytes', '', '', '', '', ''])
            
            # Per-device statistics
            writer.writerow(['', '', '', '', '', '', '', ''])
            writer.writerow(['=== PER-DEVICE STATISTICS ===', '', '', '', '', '', '', ''])
            writer.writerow(['Device_ID', 'Packets', 'Duplicates', 'Dup_Rate_%', 'Gaps', 'Bytes', '', ''])
            
            for device_id, state in sorted(self.device_states.items()):
                device_dup_rate = (state['duplicates'] / state['packets'] * 100) if state['packets'] > 0 else 0
                writer.writerow([device_id, state['packets'], state['duplicates'], 
                               f"{device_dup_rate:.1f}", state['gaps'], state['bytes'], '', ''])
            
            # Phase 2 compliance
            writer.writerow(['', '', '', '', '', '', '', ''])
            writer.writerow(['=== PHASE 2 COMPLIANCE ===', '', '', '', '', '', '', ''])
            writer.writerow(['Check', 'Status', 'Threshold', '', '', '', '', ''])
            
            compliance_checks = [
                ("Duplicate rate <= 1%", metrics['duplicate_rate'] <= 1.0, "<= 1%"),
                ("Packets received > 0", metrics['packets_received'] > 0, "> 0"),
                ("No critical gaps", metrics['sequence_gap_count'] < metrics['packets_received'] * 0.05, "< 5% of packets")
            ]
            
            all_passed = True
            for check_name, passed, threshold in compliance_checks:
                status = "PASS" if passed else "FAIL"
                writer.writerow([check_name, status, threshold, '', '', '', '', ''])
                if not passed:
                    all_passed = False
            
            overall_status = "COMPLIANT" if all_passed else "NON-COMPLIANT"
            writer.writerow(['', '', '', '', '', '', '', ''])
            writer.writerow(['OVERALL STATUS', overall_status, '', '', '', '', '', ''])
            
            # Add timestamp
            end_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            writer.writerow(['Report generated', end_time, '', '', '', '', '', ''])

    def print_metrics_report(self):
        """Print comprehensive metrics report"""
        metrics = self.calculate_metrics()
        
        if not metrics:
            print("[METRICS] No data collected")
            return
        
        print("\n" + "="*70)
        print("PHASE 2 METRICS REPORT")
        print("="*70)
        
        # Required Phase 2 metrics
        print(f"bytes_per_report:     {metrics['bytes_per_report']:.2f} bytes")
        print(f"packets_received:     {metrics['packets_received']}")
        print(f"duplicate_rate:       {metrics['duplicate_rate']:.3f}%")
        print(f"sequence_gap_count:   {metrics['sequence_gap_count']}")
        cpu_note = " (estimated)" if not self.psutil_available else ""
        print(f"cpu_ms_per_report:    {metrics['cpu_ms_per_report']:.3f} ms{cpu_note}")
        
        print("\nAdditional Performance Metrics:")
        print(f"Duration:             {metrics['duration_seconds']:.1f} seconds")
        print(f"Packets per second:   {metrics['packets_per_second']:.1f}")
        print(f"Bytes per second:     {metrics['bytes_per_second']:.1f}")
        print(f"Total bytes received: {self.total_bytes_received}")
        
        # Per-device breakdown
        print(f"\nPer-Device Statistics:")
        for device_id, state in self.device_states.items():
            device_dup_rate = (state['duplicates'] / state['packets'] * 100) if state['packets'] > 0 else 0
            print(f"  Device {device_id}: {state['packets']} packets, "
                  f"{state['duplicates']} duplicates ({device_dup_rate:.1f}%), "
                  f"{state['gaps']} gaps, {state['bytes']} bytes")
        
        # Phase 2 compliance check
        print(f"\nPhase 2 Compliance:")
        compliance_checks = [
            ("Duplicate rate <= 1%", metrics['duplicate_rate'] <= 1.0),
            ("Packets received > 0", metrics['packets_received'] > 0),
            ("No critical gaps", metrics['sequence_gap_count'] < metrics['packets_received'] * 0.05)  # Less than 5% gaps
        ]
        
        all_passed = True
        for check_name, passed in compliance_checks:
            status = "PASS" if passed else "FAIL"
            print(f"  {check_name}: {status}")
            if not passed:
                all_passed = False
        
        overall_status = "COMPLIANT" if all_passed else "NON-COMPLIANT"
        print(f"\nOverall Status: {overall_status}")
        print("="*70)

    def finalize_and_save_metrics(self):
        """Write metrics to CSV and print report"""
        print("\n[SERVER] Finalizing metrics...")
        
        # Close batch details file
        if self.batch_details_file_handle:
            self.batch_details_file_handle.close()
            print(f"[SERVER] Batch details saved to: {self.batch_details_file}")
        
        # Write metrics to CSV file
        self.write_metrics_to_csv()
        
        # Print final metrics report to console
        self.print_metrics_report()
        
        print(f"[SERVER] Metrics saved to: {self.log_file}")

    def _print_buffer_statistics(self):
        """Print statistics about buffered packets"""
        total_buffered = 0
        for device_id, state in self.device_states.items():
            if 'buffer' in state and state['buffer']:
                buffered_count = len(state['buffer'])
                total_buffered += buffered_count
                print(f"Device {device_id}: {buffered_count} packets still buffered")
        print(f"Total buffered packets: {total_buffered}")

    def _create_device_state(self):
        return {
            'last_seq': -1,
            'buffer': OrderedDict(),
            'last_values': None,        # For Data Interpolation
            'gap_start_time': None,     # For Gap Timeout
            'last_heartbeat': None,     # For heartbeat tracking
            'expected_hb_interval': 5.0 # Default heartbeat interval
        }

    def _print_buffer_statistics(self):
        """Print statistics about buffered packets"""
        total_buffered = 0
        for device_id, state in self.device_states.items():
            if 'buffer' in state and state['buffer']:
                buffered_count = len(state['buffer'])
                total_buffered += buffered_count
                print(f"Device {device_id}: {buffered_count} packets still buffered")
        print(f"Total buffered packets: {total_buffered}")



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TinyTelemetry Server with Reordering and Auto-shutdown')
    parser.add_argument('--port', type=int, default=5000, help='Server port (default: 5000)')
    parser.add_argument('--log-file', default='telemetry.csv', help='CSV log file (default: telemetry.csv)')
    parser.add_argument('--max-buffer', type=int, default=1000, help='Max buffer size per device (default: 1000)')
    parser.add_argument('--max-gap-wait', type=int, default=5, help='Max gap wait time in seconds (default: 5)')
    parser.add_argument('--auto-shutdown', type=int, help='Auto-shutdown after N seconds of no packets (optional)')
    args = parser.parse_args()

    print(f"[SERVER] Main CSV: {args.log_file}")
    print(f"[SERVER] Batch details CSV: {args.log_file.replace('.csv', '_batch_details.csv')}")

    server = Server(args.port, args.log_file, args.max_buffer, args.max_gap_wait, args.auto_shutdown)
    server.run()