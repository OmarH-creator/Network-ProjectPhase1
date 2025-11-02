"""
Automated Baseline Test - Phase 1
Runs client and server, generates logs, validates results
"""
import subprocess
import time
import socket
import csv
import sys
from datetime import datetime
from mock_protocol import decode_packet, MSG_NAMES, SENSOR_NAMES


def run_baseline_test():
    """Run automated baseline test scenario"""
    print("="*70)
    print("TinyTelemetry - Baseline Test")
    print("="*70)
    print(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # Test parameters
    DEVICE_ID = 1001
    HOST = '127.0.0.1'
    PORT = 5000
    INTERVAL = 1.0
    DURATION = 60

    print(f"Test Configuration:")
    print(f"  Device ID:  {DEVICE_ID}")
    print(f"  Server:     {HOST}:{PORT}")
    print(f"  Interval:   {INTERVAL} seconds")
    print(f"  Duration:   {DURATION} seconds")
    print(f"  Expected:   ~{DURATION} packets")
    print()

    # Create CSV log file
    csv_file = open('telemetry.csv', 'w', newline='')
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(['Timestamp', 'Device_ID', 'Seq_Num', 'Msg_Type',
                        'Temp_C', 'Humid_Pct', 'Volt_V'])

    # Start server socket
    print("[1/4] Starting server...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))
    sock.settimeout(1.0)  # 1 second timeout
    print(f"      Server listening on {HOST}:{PORT}")
    print()

    # Start client process
    print("[2/4] Starting client...")
    client_cmd = [
        'python', 'client.py',
        '--device-id', str(DEVICE_ID),
        '--server-host', HOST,
        '--server-port', str(PORT),
        '--interval', str(INTERVAL),
        '--duration', str(DURATION)
    ]

    try:
        client_process = subprocess.Popen(
            client_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        print(f"      Client started (PID: {client_process.pid})")
        print()
    except Exception as e:
        print(f"      ERROR: Failed to start client: {e}")
        sock.close()
        csv_file.close()
        return False

    # Collect packets
    print("[3/4] Collecting packets...")
    print("      (This will take ~60 seconds)")
    print()

    packet_count = 0
    init_count = 0
    data_count = 0
    start_time = time.time()

    while time.time() - start_time < DURATION + 5:  # Extra 5 seconds buffer
        try:
            data, addr = sock.recvfrom(1024)
            packet_count += 1

            # Decode packet
            try:
                packet = decode_packet(data)
                msg_type_name = MSG_NAMES.get(packet.msg_type, 'UNKNOWN')

                if packet.msg_type == 0x00:  # INIT
                    init_count += 1
                    csv_writer.writerow([
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        packet.device_id,
                        packet.seq_num,
                        'INIT',
                        '', '', ''
                    ])
                    print(f"      [{packet_count:3d}] INIT from device {packet.device_id}")

                elif packet.msg_type == 0x01:  # DATA
                    data_count += 1

                    # Extract sensor values (simplified - assumes 3 readings)
                    temp = humid = volt = ''
                    if len(data) >= 28:
                        import struct
                        temp = struct.unpack('!f', data[14:18])[0]
                        humid = struct.unpack('!f', data[19:23])[0]
                        volt = struct.unpack('!f', data[24:28])[0]

                    csv_writer.writerow([
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        packet.device_id,
                        packet.seq_num,
                        'DATA',
                        f'{temp:.2f}' if temp else '',
                        f'{humid:.2f}' if humid else '',
                        f'{volt:.2f}' if volt else ''
                    ])

                    if data_count % 10 == 0:
                        print(f"      [{packet_count:3d}] Received {data_count} DATA packets...")

            except Exception as e:
                print(f"      Warning: Failed to decode packet: {e}")

        except socket.timeout:
            # Check if client is still running
            if client_process.poll() is not None:
                break
            continue
        except Exception as e:
            print(f"      Error receiving packet: {e}")
            break

    # Wait for client to finish
    print()
    print("[4/4] Finalizing...")
    try:
        client_process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        client_process.kill()

    # Close resources
    sock.close()
    csv_file.close()

    # Generate results
    print()
    print("="*70)
    print("Test Results")
    print("="*70)
    print(f"Total Packets:    {packet_count}")
    print(f"  INIT packets:   {init_count}")
    print(f"  DATA packets:   {data_count}")
    print(f"Duration:         {time.time() - start_time:.1f} seconds")
    print(f"Packet Rate:      {data_count / (time.time() - start_time):.2f} packets/sec")
    print()
    print(f"Log File:         telemetry.csv ({packet_count} rows)")
    print()

    # Validation
    success = True
    if init_count != 1:
        print("⚠️  WARNING: Expected 1 INIT packet, got", init_count)
        success = False
    else:
        print("✅ INIT packet count: OK")

    if data_count < DURATION * 0.9:  # Allow 10% tolerance
        print(f"⚠️  WARNING: Expected ~{DURATION} DATA packets, got {data_count}")
        success = False
    else:
        print("✅ DATA packet count: OK")

    if packet_count == init_count + data_count:
        print("✅ Packet accounting: OK")
    else:
        print("⚠️  WARNING: Packet count mismatch")
        success = False

    print()
    print("="*70)
    if success:
        print("✅ BASELINE TEST PASSED")
    else:
        print("⚠️  BASELINE TEST COMPLETED WITH WARNINGS")
    print("="*70)
    print()

    return success


if __name__ == '__main__':
    try:
        success = run_baseline_test()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nTest failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
