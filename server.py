import socket
import csv
import argparse
from datetime import datetime
from protocol import decode_packet, MSG_INIT, MSG_DATA


class Server:
    def __init__(self, port, log_file):
        self.port = port
        self.log_file = log_file
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.packet_count = 0
    
    def run(self):
        # Bind to port
        self.sock.bind(('0.0.0.0', self.port))
        print(f"[SERVER] Listening on port {self.port}")

        # Open CSV file
        with open(self.log_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Device_ID', 'Seq_Num', 'Msg_Type', 'Temp_C', 'Humid_Pct', 'Volt_V'])
            
            try:
                while True:
                    # Receive packet
                    data, addr = self.sock.recvfrom(1024)
                    self.packet_count += 1
                    
                    # Decode packet
                    try:
                        packet = decode_packet(data)
                        
                        # Log packet
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        if packet.msg_type == MSG_INIT:
                            writer.writerow([timestamp, packet.device_id, packet.seq_num, 'INIT', '', '', ''])
                            print(f"[{self.packet_count}] INIT from device {packet.device_id}")
                        
                        elif packet.msg_type == MSG_DATA:
                            # Extract sensor values
                            temp = packet.readings[0].value if len(packet.readings) > 0 else ''
                            humid = packet.readings[1].value if len(packet.readings) > 1 else ''
                            volt = packet.readings[2].value if len(packet.readings) > 2 else ''
                            
                            writer.writerow([timestamp, packet.device_id, packet.seq_num, 'DATA', 
                                           f'{temp:.2f}' if temp else '', 
                                           f'{humid:.2f}' if humid else '', 
                                           f'{volt:.2f}' if volt else ''])
                            print(f"[{self.packet_count}] DATA from device {packet.device_id}, seq={packet.seq_num}")
                        
                        f.flush()  # Write to disk immediately
                    
                    except Exception as e:
                        print(f"[ERROR] Failed to decode packet: {e}")
            
            except KeyboardInterrupt:
                print(f"\n[SERVER] Stopped")
                print(f"Total packets: {self.packet_count}")
        
        self.sock.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='TinyTelemetry Server')
    parser.add_argument('--port', type=int, default=5000)
    parser.add_argument('--log-file', type=str, default='telemetry.csv')
    args = parser.parse_args()
    
    server = Server(args.port, args.log_file)
    server.run()