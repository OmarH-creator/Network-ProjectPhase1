#!/usr/bin/env python3
"""
Humidity Sensor Client
Generates only humidity readings with deterministic seed
"""
import socket
import time
import random
import argparse
import sys
import os

# Add Network-ProjectPhase1 to path
sys.path.append("")

from protocol import (
    VERSION, MSG_INIT, MSG_DATA, MSG_HEARTBEAT, SENSOR_HUM,
    TelemetryPacket, SensorReading, encode_packet
)

class HumidityClient:
    def __init__(self, device_id, host, port, interval, seed=None, heartbeat_interval=10.0, enable_heartbeat=False, period_heartbeat=3.0):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.interval = interval
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sensor_type = "HUMIDITY"
        
        # Heartbeat settings
        self.heartbeat_interval = heartbeat_interval  # Time to wait before starting heartbeats
        self.period_heartbeat = period_heartbeat      # Interval between heartbeats during idle period
        self.enable_heartbeat = enable_heartbeat
        self.last_data_time = 0
        self.last_heartbeat_time = 0
        
        # Use deterministic seed for reproducible results
        if seed is not None:
            random.seed(seed)
            print(f"[HUMID CLIENT {device_id}] Random seed set to {seed}")
        else:
            random.seed(20000 + device_id)  # Default deterministic seed
            print(f"[HUMID CLIENT {device_id}] Using default seed: {20000 + device_id}")
        
        if enable_heartbeat:
            print(f"[HUMID CLIENT {device_id}] Heartbeat enabled: {heartbeat_interval}s idle threshold, {period_heartbeat}s period")

    def send_init(self):
        packet = TelemetryPacket(
            VERSION, MSG_INIT, self.device_id,
            self.seq, int(time.time()), []
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[HUMID CLIENT {self.device_id}] INIT seq={self.seq}")
        self.seq += 1

    def send_heartbeat(self):
        """Send heartbeat message to indicate client is alive"""
        packet = TelemetryPacket(
            VERSION, MSG_HEARTBEAT, self.device_id,
            self.seq, int(time.time()), []  # Empty readings for heartbeat
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[HUMID CLIENT {self.device_id}] HEARTBEAT seq={self.seq}")
        self.seq += 1
        self.last_heartbeat_time = time.time()

    def send_humidity_data(self):
        # Generate only humidity reading (realistic range: 30-90%)
        humid_value = random.uniform(30.0, 90.0)
        
        readings = [
            SensorReading(SENSOR_HUM, humid_value)
        ]

        packet = TelemetryPacket(
            VERSION, MSG_DATA, self.device_id,
            self.seq, int(time.time()), readings
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[HUMID CLIENT {self.device_id}] DATA seq={self.seq}, humidity={humid_value:.2f}%")
        self.seq += 1
        self.last_data_time = time.time()

    def run(self, duration):
        print(f"[HUMID CLIENT {self.device_id}] Starting humidity sensor for {duration}s")
        self.send_init()
        
        start_time = time.time()
        end_time = start_time + duration
        next_data_time = start_time + self.interval  # Schedule first data packet
        next_heartbeat_time = start_time + self.heartbeat_interval  # Schedule first potential heartbeat
        
        self.last_data_time = start_time
        self.last_heartbeat_time = start_time

        try:
            while time.time() < end_time:
                current_time = time.time()
                
                # Priority 1: Send DATA if it's time (DATA has highest priority)
                if current_time >= next_data_time:
                    self.send_humidity_data()
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
            print(f"\n[HUMID CLIENT {self.device_id}] Stopping...")
        finally:
            self.sock.close()
            print(f"[HUMID CLIENT {self.device_id}] Socket closed")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Humidity Sensor Client")
    parser.add_argument("--device-id", type=int, default=3002, help="Device ID (default: 3002)")
    parser.add_argument("--server-host", default="127.0.0.1", help="Server hostname (default: 127.0.0.1)")
    parser.add_argument("--server-port", type=int, default=5000, help="Server port (default: 5000)")
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between readings (default: 2.0s)")
    parser.add_argument("--duration", type=float, default=20.0, help="Total duration (default: 20.0s)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    parser.add_argument("--heartbeat-interval", type=float, default=10.0, help="Heartbeat interval when idle (default: 10.0s)")
    parser.add_argument("--period-heartbeat", type=float, default=3.0, help="Period between heartbeats during idle time (default: 3.0s)")
    parser.add_argument("--enable-heartbeat", action="store_true", help="Enable heartbeat functionality")
    args = parser.parse_args()

    client = HumidityClient(args.device_id, args.server_host, args.server_port, args.interval, args.seed,
                           args.heartbeat_interval, args.enable_heartbeat, args.period_heartbeat)
    client.run(args.duration)