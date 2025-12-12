#!/usr/bin/env python3
"""
Temperature Sensor Client
Generates only temperature readings with deterministic seed
"""
import socket
import time
import random
import argparse
import sys
import os

# Add Network-ProjectPhase1 to path
sys.path.append("")

from protocol_M_M import (
    VERSION, MSG_INIT, MSG_DATA, MSG_HEARTBEAT, SENSOR_TEMP,
    TelemetryPacket, SensorReading, encode_packet
)

class TemperatureClient:
    def __init__(self, device_id, host, port, interval, seed=None, heartbeat_interval=10.0, enable_heartbeat=False, period_heartbeat=3.0, enable_batching=False, batching_interval=10.0):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.interval = interval
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sensor_type = "TEMPERATURE"
        
        # Heartbeat settings
        self.heartbeat_interval = heartbeat_interval  # Time to wait before starting heartbeats
        self.period_heartbeat = period_heartbeat      # Interval between heartbeats during idle period
        self.enable_heartbeat = enable_heartbeat
        self.last_data_time = 0
        self.last_heartbeat_time = 0
        
        # Batching settings
        self.enable_batching = enable_batching
        self.batching_interval = batching_interval
        self.batch_readings = []  # Collect readings for batching
        self.max_readings_per_packet = 37  # (200 - 12 - 1) / 5 = 37 max readings
        
        # Use deterministic seed for reproducible results
        if seed is not None:
            random.seed(seed)
            print(f"[TEMP CLIENT {device_id}] Random seed set to {seed}")
        else:
            random.seed(10000 + device_id)  # Default deterministic seed
            print(f"[TEMP CLIENT {device_id}] Using default seed: {10000 + device_id}")
        
        if enable_heartbeat:
            print(f"[TEMP CLIENT {device_id}] Heartbeat enabled: {heartbeat_interval}s idle threshold, {period_heartbeat}s period")
        
        if enable_batching:
            print(f"[TEMP CLIENT {device_id}] Batching enabled: {batching_interval}s batch interval, max {self.max_readings_per_packet} readings/packet")

    def send_init(self):
        packet = TelemetryPacket(
            VERSION, MSG_INIT, self.device_id,
            self.seq, int(time.time()), [], flags=0
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[TEMP CLIENT {self.device_id}] INIT seq={self.seq}")
        self.seq += 1

    def send_heartbeat(self):
        """Send heartbeat message to indicate client is alive"""
        packet = TelemetryPacket(
            VERSION, MSG_HEARTBEAT, self.device_id,
            self.seq, int(time.time()), [], flags=0  # Empty readings for heartbeat
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[TEMP CLIENT {self.device_id}] HEARTBEAT seq={self.seq}")
        self.seq += 1
        self.last_heartbeat_time = time.time()

    def generate_temperature_reading(self):
        """Generate a single temperature reading"""
        temp_value = random.uniform(20.0, 30.0)
        return SensorReading(SENSOR_TEMP, temp_value)

    def send_temperature_data(self):
        """Send single temperature reading (normal mode)"""
        reading = self.generate_temperature_reading()
        readings = [reading]

        packet = TelemetryPacket(
            VERSION, MSG_DATA, self.device_id,
            self.seq, int(time.time()), readings, flags=0
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[TEMP CLIENT {self.device_id}] DATA seq={self.seq}, temp={reading.value:.2f}°C")
        self.seq += 1
        self.last_data_time = time.time()

    def add_reading_to_batch(self):
        """Add a reading to the current batch"""
        reading = self.generate_temperature_reading()
        self.batch_readings.append(reading)
        print(f"[TEMP CLIENT {self.device_id}] Added to batch: temp={reading.value:.2f}°C (batch size: {len(self.batch_readings)})")
        
        # Check if batch is full
        if len(self.batch_readings) >= self.max_readings_per_packet:
            print(f"[TEMP CLIENT {self.device_id}] Batch full ({self.max_readings_per_packet} readings), sending early")
            self.send_batch()

    def send_batch(self):
        """Send all readings in the current batch"""
        if not self.batch_readings:
            return
        
        packet = TelemetryPacket(
            VERSION, MSG_DATA, self.device_id,
            self.seq, int(time.time()), self.batch_readings.copy(), flags=0x01  # FLAG_BATCHING
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        
        # Log batch details
        temp_values = [r.value for r in self.batch_readings]
        avg_temp = sum(temp_values) / len(temp_values)
        min_temp = min(temp_values)
        max_temp = max(temp_values)
        
        print(f"[TEMP CLIENT {self.device_id}] BATCH seq={self.seq}, {len(self.batch_readings)} readings, "
              f"temp avg={avg_temp:.2f}°C (min={min_temp:.2f}, max={max_temp:.2f})")
        
        self.seq += 1
        self.last_data_time = time.time()
        self.batch_readings.clear()  # Clear batch after sending

    def run(self, duration):
        print(f"[TEMP CLIENT {self.device_id}] Starting temperature sensor for {duration}s")
        self.send_init()
        
        start_time = time.time()
        end_time = start_time + duration
        self.last_data_time = start_time
        self.last_heartbeat_time = start_time

        if self.enable_batching:
            # BATCHING MODE
            print(f"[TEMP CLIENT {self.device_id}] Running in BATCHING mode")
            next_reading_time = start_time + self.interval  # Schedule first reading collection
            next_batch_send_time = start_time + self.batching_interval  # Schedule first batch send
            next_heartbeat_time = start_time + self.heartbeat_interval  # Schedule first potential heartbeat
            
            try:
                while time.time() < end_time:
                    current_time = time.time()
                    
                    # Priority 1: Send BATCH if it's time (highest priority)
                    if current_time >= next_batch_send_time:
                        self.send_batch()  # Send whatever is in the batch (even if empty)
                        next_batch_send_time = current_time + self.batching_interval  # Schedule next batch
                        # Reset heartbeat timing when batch is sent
                        next_heartbeat_time = current_time + self.heartbeat_interval
                        
                    # Priority 2: Collect reading if it's time
                    elif current_time >= next_reading_time:
                        self.add_reading_to_batch()
                        next_reading_time = current_time + self.interval  # Schedule next reading
                        
                    # Priority 3: Send HEARTBEAT if enabled, idle long enough, and time for heartbeat
                    elif (self.enable_heartbeat and 
                          current_time >= next_heartbeat_time and
                          (current_time - self.last_data_time) >= self.heartbeat_interval):
                        self.send_heartbeat()
                        next_heartbeat_time = current_time + self.period_heartbeat  # Schedule next heartbeat
                    
                    # Small sleep to prevent busy waiting
                    time.sleep(0.1)
                    
                # Send any remaining readings in batch before exit
                if self.batch_readings:
                    print(f"[TEMP CLIENT {self.device_id}] Sending final batch with {len(self.batch_readings)} readings")
                    self.send_batch()
                    
            except KeyboardInterrupt:
                print(f"\n[TEMP CLIENT {self.device_id}] Stopping...")
                # Send any remaining readings in batch
                if self.batch_readings:
                    print(f"[TEMP CLIENT {self.device_id}] Sending final batch with {len(self.batch_readings)} readings")
                    self.send_batch()
        else:
            # NORMAL MODE (existing logic)
            print(f"[TEMP CLIENT {self.device_id}] Running in NORMAL mode")
            next_data_time = start_time + self.interval  # Schedule first data packet
            next_heartbeat_time = start_time + self.heartbeat_interval  # Schedule first potential heartbeat
            
            try:
                while time.time() < end_time:
                    current_time = time.time()
                    
                    # Priority 1: Send DATA if it's time (DATA has highest priority)
                    if current_time >= next_data_time:
                        self.send_temperature_data()
                        next_data_time = current_time + self.interval  # Schedule next data
                        # Reset heartbeat timing when data is sent
                        next_heartbeat_time = current_time + self.heartbeat_interval
                        
                    # Priority 2: Send HEARTBEAT if enabled, idle long enough, and time for heartbeat
                    elif (self.enable_heartbeat and 
                          current_time >= next_heartbeat_time and
                          (current_time - self.last_data_time) >= self.heartbeat_interval):
                        self.send_heartbeat()
                        next_heartbeat_time = current_time + self.period_heartbeat  # Schedule next heartbeat
                    
                    # Small sleep to prevent busy waiting
                    time.sleep(0.1)
                    
            except KeyboardInterrupt:
                print(f"\n[TEMP CLIENT {self.device_id}] Stopping...")
        
        self.sock.close()
        print(f"[TEMP CLIENT {self.device_id}] Socket closed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Temperature Sensor Client")
    parser.add_argument("--device-id", type=int, default=3001, help="Device ID (default: 3001)")
    parser.add_argument("--server-host", default="127.0.0.1", help="Server hostname (default: 127.0.0.1)")
    parser.add_argument("--server-port", type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between readings (default: 2.0s)")
    parser.add_argument("--duration", type=float, default=20.0, help="Total duration (default: 20.0s)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    parser.add_argument("--heartbeat-interval", type=float, default=10.0, help="Heartbeat interval when idle (default: 10.0s)")
    parser.add_argument("--period-heartbeat", type=float, default=3.0, help="Period between heartbeats during idle time (default: 3.0s)")
    parser.add_argument("--enable-heartbeat", action="store_true", help="Enable heartbeat functionality")
    parser.add_argument("--enable-batching", action="store_true", help="Enable batching mode (collect multiple readings per packet)")
    parser.add_argument("--batching-interval", type=float, default=10.0, help="Interval between batch sends (default: 10.0s)")
    args = parser.parse_args()

    client = TemperatureClient(args.device_id, args.server_host, args.server_port, args.interval, args.seed, 
                              args.heartbeat_interval, args.enable_heartbeat, args.period_heartbeat,
                              args.enable_batching, args.batching_interval)
    client.run(args.duration)