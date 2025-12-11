import socket
import csv
import argparse
from datetime import datetime, timedelta
from collections import deque, OrderedDict
from protocol import decode_packet, MSG_INIT, MSG_DATA, MSG_HEARTBEAT,SENSOR_HB_INTERVAL


class Server:
    def __init__(self, port, log_file, heartbeat_log_file, max_buffer_size=100, max_gap_wait_seconds=5):
        self.port = port
        self.log_file = log_file
        self.heartbeat_log_file = heartbeat_log_file
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packet_count = 0

        # Configuration
        self.max_buffer_size = max_buffer_size
        self.max_gap_wait_seconds = max_gap_wait_seconds

        # Key: Device_ID, Value: { ... state dict ... }
        self.device_states = {}

        # File handles
        self.telemetry_file = None
        self.heartbeat_file = None

    def run(self):
        self.device_states = {}
        self.sock.bind(('0.0.0.0', self.port))
        self.sock.settimeout(1.0)  # Timeout for cleanup checks

        print(f"[SERVER] Listening on port {self.port}")
        print(f"[CONFIG] Max buffer size: {self.max_buffer_size} packets per device")
        print(f"[CONFIG] Max gap wait time: {self.max_gap_wait_seconds} seconds")

        with open(self.log_file, 'w', newline='') as f, \
                open(self.heartbeat_log_file, 'w', newline='') as hb_f:

            self.telemetry_file = f
            self.heartbeat_file = hb_f
            writer = csv.writer(f)
            heartbeat_writer = csv.writer(hb_f)

            writer.writerow(['Timestamp', 'Device_ID', 'Seq_Num', 'Msg_Type',
                             'Duplicate_Flag', 'Gap_Flag', 'Temp_C', 'Humid_Pct', 'Volt_V'])
            self.telemetry_file.flush()

            heartbeat_writer.writerow(['Timestamp', 'Device_ID', 'Seq_Num', 'Interval', 'Status'])
            self.heartbeat_file.flush()

            try:
                while True:
                    try:
                        data, addr = self.sock.recvfrom(1024)
                        self.packet_count += 1
                        try:
                            packet = decode_packet(data)
                            timestamp = datetime.now()
                            self._process_telemetry(packet, timestamp, writer,heartbeat_writer)

                            if self.packet_count % 100 == 0:
                                self._cleanup_old_buffers(timestamp, writer)
                        except Exception as e:
                            print(f"[ERROR] Decode failed: {e}")

                    except socket.timeout:
                        self._cleanup_old_buffers(datetime.now(), writer)
                        continue

            except KeyboardInterrupt:
                print(f"\n[SERVER] Stopped. Total packets: {self.packet_count}")
                self._print_buffer_statistics()

        self.sock.close()

    def _process_telemetry(self, packet, timestamp, writer,heartbeat_writer):
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        if packet.device_id not in self.device_states:
            self.device_states[packet.device_id] = self._create_device_state()

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

                writer.writerow([timestamp_str, packet.device_id, packet.seq_num, 'INIT', 0, 0, '', '', ''])
                self.telemetry_file.flush()

                self._process_buffered_packets(packet.device_id, timestamp, writer)
                return

            if packet.msg_type == MSG_HEARTBEAT:
                print(f"[{self.packet_count}] HEARTBEAT device {packet.device_id}")
                device_state['last_seq'] = packet.seq_num
                device_state['last_values'] = None  # Reset values
                device_state['gap_start_time'] = None
                self._process_heartbeat(packet, timestamp, heartbeat_writer)


        else:
            # --- DATA Message ---
            # 1. Duplicate Check
            if current_seq <= last_seq:
                print(f"[{self.packet_count}] DATA {packet.device_id} seq={current_seq} [DUPLICATE]")
                self._log_data_packet(packet, timestamp_str, writer, True, False)
                return

            # 2. In-Order Check
            if current_seq == last_seq + 1:
                print(f"[{self.packet_count}] DATA {packet.device_id} seq={current_seq} [IN-ORDER]")
                self._log_data_packet(packet, timestamp_str, writer, False, False)

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

                    self._interpolate_and_log(packet.device_id, last_seq, next_avail_seq,
                                              start_vals, end_vals, timestamp_str, writer)

                    # Advance state to just before the next available packet
                    device_state['last_seq'] = next_avail_seq - 1
                    device_state['gap_start_time'] = None

                    # Now process the buffered packets (or current) naturally
                    if current_seq == device_state['last_seq'] + 1:
                        # Current packet is now next
                        self._log_data_packet(packet, timestamp_str, writer, False, False)
                        device_state['last_values'] = self._get_packet_values(packet)
                        device_state['last_seq'] = current_seq
                    else:
                        # Check buffer
                        self._process_buffered_packets(packet.device_id, timestamp, writer)

                    # If current packet is still a gap relative to the NEW position, buffer it
                    if current_seq > device_state['last_seq'] + 1:
                        self._add_to_buffer(packet, timestamp, timestamp_str, device_state)
                    return

            # 4. Buffer the packet (Wait)
            self._add_to_buffer(packet, timestamp, timestamp_str, device_state)

    def _add_to_buffer(self, packet, timestamp, timestamp_str, device_state):
        buffer = device_state['buffer']
        current_seq = packet.seq_num

        if len(buffer) >= self.max_buffer_size:
            buffer.pop(next(iter(buffer)))

        buffer[current_seq] = {
            'packet': packet,
            'timestamp': timestamp_str,
            'arrival_time': timestamp,
            'logged': False
        }
        device_state['buffer'] = OrderedDict(sorted(buffer.items()))
        print(f"[BUFFERED] Device {packet.device_id}: seq={current_seq}")

        if device_state['gap_start_time'] is None:
            device_state['gap_start_time'] = timestamp

    def _process_heartbeat(self, packet, timestamp, writer):
        """Process heartbeat messages and check for timeouts"""
        timestamp_str = timestamp.strftime('%Y-%m-%d %H:%M:%S')

        # 1. Initialize State
        if packet.device_id not in self.device_states:
            self.device_states[packet.device_id] = self._create_device_state()

        device_state = self.device_states[packet.device_id]
        last_hb = device_state['last_heartbeat']

        # 2. Extract Promised Interval (from Client)
        client_interval = None
        for r in packet.readings:
            # Requires SENSOR_HB_INTERVAL imported from protocol.py
            if r.sensor_type == SENSOR_HB_INTERVAL:
                client_interval = r.value
                device_state['expected_hb_interval'] = client_interval

        # Fallback to saved interval or default
        if client_interval is None:
            client_interval = device_state.get('expected_hb_interval', 5.0)

        # 3. Calculate Status
        actual_interval = 0.0
        status = "ALIVE"

        if last_hb is not None:
            actual_interval = (timestamp - last_hb).total_seconds()

            # Allow small buffer for jitter (+1.5s)
            threshold = client_interval + 1.5

            if actual_interval > threshold:
                status = f"TIMEOUT_RECOVERED (> {threshold}s)"
                print(f"[{self.packet_count}] HEARTBEAT {packet.device_id} [LATE] "
                      f"Gap: {actual_interval:.2f}s (Expected: {client_interval}s)")
            else:
                print(f"[{self.packet_count}] HEARTBEAT {packet.device_id} [ALIVE] "
                      f"Interval: {actual_interval:.2f}s")
        else:
            status = "FIRST_CONTACT"
            print(f"[{self.packet_count}] HEARTBEAT {packet.device_id} [INIT] "
                  f"Promised Interval: {client_interval}s")

        # 4. Log to CSV
        writer.writerow([
            timestamp_str,
            packet.device_id,
            packet.seq_num,
            f"{actual_interval:.2f}",
            status
        ])

        # --- FIX IS HERE ---
        # BAD: heartbeat_writer.writer.flush()
        # GOOD: Flush the file handle directly
        if self.heartbeat_file:
            self.heartbeat_file.flush()

        # 5. Update State
        device_state['last_heartbeat'] = timestamp

    def _process_buffered_packets(self, device_id, timestamp, writer):
        device_state = self.device_states[device_id]
        buffer = device_state['buffer']
        last_seq = device_state['last_seq']

        while buffer:
            next_seq = next(iter(buffer))
            if next_seq == last_seq + 1:
                item = buffer.pop(next_seq)
                print(f"[REORDER] releasing seq={next_seq}")
                self._log_data_packet(item['packet'], item['timestamp'], writer, False, False)

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

    # --- NEW HELPER: Get Values (T, H, V) ---
    def _get_packet_values(self, packet):
        t = packet.readings[0].value if len(packet.readings) > 0 else 0.0
        h = packet.readings[1].value if len(packet.readings) > 1 else 0.0
        v = packet.readings[2].value if len(packet.readings) > 2 else 0.0
        return (t, h, v)

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

            # Log Estimated Packet (Gap Flag = 1, but with DATA values)
            writer.writerow([
                timestamp_str, device_id, seq, 'DATA',
                0, 1,  # Gap Flag is 1 to indicate "Estimated"
                f"{current_vals[0]:.2f}",
                f"{current_vals[1]:.2f}",
                f"{current_vals[2]:.2f}"
            ])

        if self.telemetry_file: self.telemetry_file.flush()

    def _log_data_packet(self, packet, timestamp_str, writer, is_dup, is_gap):
        t, h, v = self._get_packet_values(packet)
        writer.writerow([
            timestamp_str, packet.device_id, packet.seq_num, 'DATA',
            1 if is_dup else 0,
            1 if is_gap else 0,
            f"{t:.2f}", f"{h:.2f}", f"{v:.2f}"
        ])
        if self.telemetry_file: self.telemetry_file.flush()

    def _create_device_state(self):
        return {
            'last_seq': -1,
            'buffer': OrderedDict(),
            'last_values': None,        # For Data Interpolation
            'gap_start_time': None,     # For Gap Timeout
            'last_heartbeat': None,     # <--- ADD THIS (Fixes the error)
            'expected_hb_interval': SENSOR_HB_INTERVAL # <--- ADD THIS (Stores client preference)
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
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--log-file', default='telemetry.csv')
    parser.add_argument('--heartbeat-log-file', default='heartbeats.csv')
    parser.add_argument('--max-buffer', type=int, default=1000)
    parser.add_argument('--max-gap-wait', type=int, default=5)
    args = parser.parse_args()

    server = Server(args.port, args.log_file, args.heartbeat_log_file, args.max_buffer, args.max_gap_wait)
    server.run()