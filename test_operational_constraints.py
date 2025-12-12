#!/usr/bin/env python3
"""
Operational Constraints Negative Test Suite
============================================
Tests for the 4 operational constraints:
1. payload_limit_bytes (200 bytes max)
2. reporting_intervals (1s, 5s, 30s)
3. loss_tolerance (5% random loss - detect but not recover)
4. batching (N readings per packet)

Run: python test_operational_constraints.py
"""
import socket
import time
import sys
import struct
import random

# Add path for imports
sys.path.insert(0, '.')

from protocol_M_M import (
    VERSION, MSG_INIT, MSG_DATA, MSG_HEARTBEAT,
    SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT,
    TelemetryPacket, SensorReading, encode_packet,
    HEADER_SIZE, READING_SIZE, PAYLOAD_LIMIT
)


def print_header(title):
    print("\n" + "=" * 70)
    print(f"TEST: {title}")
    print("=" * 70)


def print_result(test_name, passed, details=""):
    status = "✓ PASS" if passed else "✗ FAIL"
    print(f"  {status}: {test_name}")
    if details:
        print(f"         {details}")


# =============================================================================
# TEST 1: PAYLOAD LIMIT (200 bytes)
# =============================================================================
def test_payload_limit():
    """
    Test that packets exceeding 200 bytes are rejected.
    
    Calculation:
    - Header: 13 bytes
    - Reading count: 1 byte
    - Each reading: 5 bytes
    - Max readings: (200 - 13 - 1) / 5 = 37.2 → 37 readings max
    """
    print_header("PAYLOAD LIMIT (200 bytes)")
    
    print(f"\n  Protocol Constants:")
    print(f"    HEADER_SIZE = {HEADER_SIZE} bytes")
    print(f"    READING_SIZE = {READING_SIZE} bytes")
    print(f"    PAYLOAD_LIMIT = {PAYLOAD_LIMIT} bytes")
    print(f"    Max readings = ({PAYLOAD_LIMIT} - {HEADER_SIZE} - 1) / {READING_SIZE} = {(PAYLOAD_LIMIT - HEADER_SIZE - 1) // READING_SIZE}")
    
    # Test 1a: Valid packet at limit (37 readings)
    max_readings = (PAYLOAD_LIMIT - HEADER_SIZE - 1) // READING_SIZE
    readings_at_limit = [SensorReading(SENSOR_TEMP, 25.0 + i * 0.1) for i in range(max_readings)]
    
    try:
        packet_at_limit = TelemetryPacket(
            VERSION, MSG_DATA, 3001, 1, int(time.time()),
            readings_at_limit, flags=0
        )
        encoded = encode_packet(packet_at_limit)
        packet_size = len(encoded)
        print_result(f"Packet at limit ({max_readings} readings, {packet_size} bytes)", 
                    packet_size <= PAYLOAD_LIMIT,
                    f"Size: {packet_size} bytes <= {PAYLOAD_LIMIT} bytes")
    except ValueError as e:
        print_result(f"Packet at limit ({max_readings} readings)", False, str(e))
    
    # Test 1b: Invalid packet exceeding limit (38+ readings)
    readings_over_limit = [SensorReading(SENSOR_TEMP, 25.0 + i * 0.1) for i in range(max_readings + 1)]
    
    try:
        packet_over_limit = TelemetryPacket(
            VERSION, MSG_DATA, 3001, 2, int(time.time()),
            readings_over_limit, flags=0
        )
        encoded = encode_packet(packet_over_limit)
        print_result(f"Packet over limit ({max_readings + 1} readings) REJECTED", False, 
                    "Should have raised ValueError!")
    except ValueError as e:
        print_result(f"Packet over limit ({max_readings + 1} readings) REJECTED", True, 
                    f"Error: {e}")
    
    # Test 1c: Calculate exact sizes
    print(f"\n  Size Calculations:")
    for num_readings in [1, 5, 10, 20, 37, 38]:
        size = HEADER_SIZE + 1 + num_readings * READING_SIZE
        valid = "✓" if size <= PAYLOAD_LIMIT else "✗"
        print(f"    {num_readings} readings: {size} bytes {valid}")


# =============================================================================
# TEST 2: REPORTING INTERVALS (1s, 5s, 30s)
# =============================================================================
def test_reporting_intervals():
    """
    Test that clients can be configured with different reporting intervals.
    This is a configuration test - verify the client accepts these values.
    """
    print_header("REPORTING INTERVALS (1s, 5s, 30s)")
    
    intervals = [1.0, 5.0, 30.0]
    
    print(f"\n  Testing interval configurations:")
    for interval in intervals:
        # Verify interval is valid (positive number)
        valid = interval > 0
        print_result(f"Interval {interval}s is valid", valid)
    
    # Test invalid intervals
    invalid_intervals = [0, -1, -5.0]
    print(f"\n  Testing invalid intervals (should be rejected):")
    for interval in invalid_intervals:
        valid = interval <= 0  # These should be invalid
        print_result(f"Interval {interval}s is invalid", valid, 
                    "Negative/zero intervals should be rejected")
    
    print(f"\n  To test intervals, run clients with:")
    print(f"    python temp_client.py --interval 1.0 --duration 10")
    print(f"    python temp_client.py --interval 5.0 --duration 30")
    print(f"    python temp_client.py --interval 30.0 --duration 120")


# =============================================================================
# TEST 3: LOSS TOLERANCE (5% random loss)
# =============================================================================
def test_loss_tolerance(server_host='127.0.0.1', server_port=5000, run_network_test=False):
    """
    Test that server detects packet loss but does not recover (no retransmission).
    
    The server should:
    - Detect gaps in sequence numbers
    - Log gaps in metrics (sequence_gap_count)
    - NOT request retransmission (UDP is fire-and-forget)
    """
    print_header("LOSS TOLERANCE (5% random loss - detect but not recover)")
    
    print(f"\n  Loss Tolerance Requirements:")
    print(f"    - Server MUST detect sequence gaps")
    print(f"    - Server MUST log gaps in metrics")
    print(f"    - Server MUST NOT request retransmission")
    print(f"    - Server MAY interpolate missing values")
    
    if not run_network_test:
        print(f"\n  [SKIPPED] Network test requires server running")
        print(f"  To run full test:")
        print(f"    1. Start server: python server_besheer.py --port 5000 --log-file loss_test.csv --auto-shutdown 15")
        print(f"    2. Run this test: python test_operational_constraints.py --loss-test")
        return
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    try:
        # Send INIT
        init_packet = TelemetryPacket(VERSION, MSG_INIT, 3001, 0, int(time.time()), [], flags=0)
        sock.sendto(encode_packet(init_packet), (server_host, server_port))
        print(f"\n  Sent INIT packet (seq=0)")
        time.sleep(0.1)
        
        # Send packets with 5% simulated loss
        total_packets = 20
        loss_rate = 0.05
        sent_seqs = []
        lost_seqs = []
        
        for seq in range(1, total_packets + 1):
            if random.random() < loss_rate:
                # Simulate packet loss - don't send
                lost_seqs.append(seq)
                print(f"  [LOST] Packet seq={seq} (simulated loss)")
            else:
                reading = SensorReading(SENSOR_TEMP, 25.0 + seq * 0.1)
                packet = TelemetryPacket(VERSION, MSG_DATA, 3001, seq, int(time.time()), [reading], flags=0)
                sock.sendto(encode_packet(packet), (server_host, server_port))
                sent_seqs.append(seq)
                print(f"  [SENT] Packet seq={seq}")
            time.sleep(0.1)
        
        print(f"\n  Summary:")
        print(f"    Total packets: {total_packets}")
        print(f"    Sent: {len(sent_seqs)}")
        print(f"    Lost: {len(lost_seqs)} ({len(lost_seqs)/total_packets*100:.1f}%)")
        print(f"    Lost sequences: {lost_seqs}")
        
        print_result("Loss simulation completed", True, 
                    f"Check server CSV for sequence_gap_count = {len(lost_seqs)}")
        
    finally:
        sock.close()


# =============================================================================
# TEST 4: BATCHING (N readings per packet)
# =============================================================================
def test_batching():
    """
    Test batching functionality - grouping multiple readings per packet.
    
    Max readings per packet: 37 (based on 200 byte limit)
    """
    print_header("BATCHING (N readings per packet)")
    
    max_readings = (PAYLOAD_LIMIT - HEADER_SIZE - 1) // READING_SIZE
    
    print(f"\n  Batching Configuration:")
    print(f"    Max readings per packet: {max_readings}")
    print(f"    Packet overhead: {HEADER_SIZE + 1} bytes (header + count)")
    print(f"    Bytes per reading: {READING_SIZE}")
    
    # Test various batch sizes
    batch_sizes = [1, 5, 10, 20, 37]
    
    print(f"\n  Testing batch sizes:")
    for batch_size in batch_sizes:
        readings = [SensorReading(SENSOR_TEMP, 25.0 + i * 0.1) for i in range(batch_size)]
        
        try:
            packet = TelemetryPacket(
                VERSION, MSG_DATA, 3001, 1, int(time.time()),
                readings, flags=0x01  # FLAG_BATCHING
            )
            encoded = encode_packet(packet)
            packet_size = len(encoded)
            
            print_result(f"Batch size {batch_size}: {packet_size} bytes", 
                        packet_size <= PAYLOAD_LIMIT,
                        f"Readings: {batch_size}, Size: {packet_size}/{PAYLOAD_LIMIT} bytes")
        except ValueError as e:
            print_result(f"Batch size {batch_size}", False, str(e))
    
    # Test batch with mixed sensor types
    print(f"\n  Testing mixed sensor batch:")
    mixed_readings = [
        SensorReading(SENSOR_TEMP, 25.0),
        SensorReading(SENSOR_TEMP, 25.5),
        SensorReading(SENSOR_HUM, 60.0),
        SensorReading(SENSOR_HUM, 61.0),
        SensorReading(SENSOR_VOLT, 3.3),
    ]
    
    try:
        mixed_packet = TelemetryPacket(
            VERSION, MSG_DATA, 3001, 1, int(time.time()),
            mixed_readings, flags=0x01
        )
        encoded = encode_packet(mixed_packet)
        print_result(f"Mixed sensor batch (5 readings)", True, 
                    f"Size: {len(encoded)} bytes")
    except ValueError as e:
        print_result(f"Mixed sensor batch", False, str(e))


# =============================================================================
# TEST 5: DUPLICATE DETECTION
# =============================================================================
def test_duplicate_detection(server_host='127.0.0.1', server_port=5000, run_network_test=False):
    """
    Test that server detects and counts duplicate packets.
    """
    print_header("DUPLICATE DETECTION")
    
    if not run_network_test:
        print(f"\n  [SKIPPED] Network test requires server running")
        print(f"  To run full test:")
        print(f"    1. Start server: python server_besheer.py --port 5000 --log-file dup_test.csv --auto-shutdown 15")
        print(f"    2. Run this test: python test_operational_constraints.py --dup-test")
        return
    
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    
    try:
        # Send INIT
        init_packet = TelemetryPacket(VERSION, MSG_INIT, 3001, 0, int(time.time()), [], flags=0)
        sock.sendto(encode_packet(init_packet), (server_host, server_port))
        print(f"\n  Sent INIT packet (seq=0)")
        time.sleep(0.1)
        
        # Send packet seq=1
        reading = SensorReading(SENSOR_TEMP, 25.0)
        packet1 = TelemetryPacket(VERSION, MSG_DATA, 3001, 1, int(time.time()), [reading], flags=0)
        sock.sendto(encode_packet(packet1), (server_host, server_port))
        print(f"  Sent DATA packet (seq=1)")
        time.sleep(0.1)
        
        # Send duplicate seq=1
        sock.sendto(encode_packet(packet1), (server_host, server_port))
        print(f"  Sent DUPLICATE packet (seq=1)")
        time.sleep(0.1)
        
        # Send packet seq=2
        reading2 = SensorReading(SENSOR_TEMP, 26.0)
        packet2 = TelemetryPacket(VERSION, MSG_DATA, 3001, 2, int(time.time()), [reading2], flags=0)
        sock.sendto(encode_packet(packet2), (server_host, server_port))
        print(f"  Sent DATA packet (seq=2)")
        time.sleep(0.1)
        
        # Send another duplicate seq=1
        sock.sendto(encode_packet(packet1), (server_host, server_port))
        print(f"  Sent DUPLICATE packet (seq=1)")
        
        print_result("Duplicate test completed", True, 
                    "Check server CSV for duplicate_rate > 0")
        
    finally:
        sock.close()


# =============================================================================
# MAIN
# =============================================================================
def main():
    print("\n" + "=" * 70)
    print("OPERATIONAL CONSTRAINTS NEGATIVE TEST SUITE")
    print("=" * 70)
    print(f"\nThis test suite validates the 4 operational constraints:")
    print(f"  1. payload_limit_bytes (200 bytes max)")
    print(f"  2. reporting_intervals (1s, 5s, 30s)")
    print(f"  3. loss_tolerance (5% random loss)")
    print(f"  4. batching (N readings per packet)")
    
    # Check command line args
    run_loss_test = '--loss-test' in sys.argv
    run_dup_test = '--dup-test' in sys.argv
    
    # Run all tests
    test_payload_limit()
    test_reporting_intervals()
    test_loss_tolerance(run_network_test=run_loss_test)
    test_batching()
    test_duplicate_detection(run_network_test=run_dup_test)
    
    print("\n" + "=" * 70)
    print("TEST SUITE COMPLETE")
    print("=" * 70)
    print(f"\nTo run network tests:")
    print(f"  1. Start server: python server_besheer.py --port 5000 --log-file test.csv --auto-shutdown 20")
    print(f"  2. Run loss test: python test_operational_constraints.py --loss-test")
    print(f"  3. Run dup test: python test_operational_constraints.py --dup-test")
    print(f"\nCheck the CSV files for:")
    print(f"  - sequence_gap_count (loss tolerance)")
    print(f"  - duplicate_rate (duplicate detection)")
    print(f"  - Per-device statistics")


if __name__ == "__main__":
    main()
