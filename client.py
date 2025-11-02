import socket
import time
import random
import argparse

from protocol import (
    VERSION, MSG_INIT, MSG_DATA,
    SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT,
    TelemetryPacket, SensorReading, encode_packet
)

class Client:
    def __init__(self, device_id, host, port, interval):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.interval = interval
        self.seq = 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_init(self):
        packet = TelemetryPacket(
            VERSION, MSG_INIT, self.device_id,
            self.seq, int(time.time()), []
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[INIT] seq={self.seq}")
        self.seq += 1

    def send_data(self):
        readings = [
            SensorReading(SENSOR_TEMP,  random.uniform(20, 30)),
            SensorReading(SENSOR_HUM, random.uniform(40, 60)),
            SensorReading(SENSOR_VOLT,  random.uniform(4.5, 5.5))
        ]

        packet = TelemetryPacket(
            VERSION, MSG_DATA, self.device_id,
            self.seq, int(time.time()), readings
        )
        self.sock.sendto(encode_packet(packet), (self.host, self.port))
        print(f"[DATA] seq={self.seq}")
        self.seq += 1

    def run(self, duration):
        self.send_init()
        end = time.time() + duration

        try:
            while time.time() < end:
                self.send_data()
                time.sleep(self.interval)
        except KeyboardInterrupt:
            print("\nStopping now :D...")
        finally:
            self.sock.close()
            print("Socket closed ^^")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="TinyTelemetry Client")
    parser.add_argument("--device-id", type=int, required=True)
    parser.add_argument("--server-host", required=True)
    parser.add_argument("--server-port", type=int, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=10.0)
    args = parser.parse_args()

    client = Client(args.device_id, args.server_host, args.server_port, args.interval) #client instance
    client.run(args.duration)
