from typing import List, Dict, Optional
import struct
import math

VERSION = 0x01

# message type
MSG_INIT = 0x00
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# sensor type
SENSOR_TEMP = 0x01
SENSOR_HUM = 0x02
SENSOR_VOLT = 0x03

ALLOWED_DEVICE_IDS = {3001, 3002, 3003}

# size in bytes
HEADER_SIZE = 13  # version(1) + msg_type(1) + flags(1) + device_id(2) + seq_num(4) + timestamp(4)
READING_SIZE = 5
PAYLOAD_LIMIT = 200

# flags
FLAG_BATCHING = 0x01  # bit 0: batching enabled


class SensorReading:
    def __init__(self, sensor_type: int, value: float):
        self.sensor_type = sensor_type
        self.value = value


class TelemetryPacket:
    def __init__(self, version: int, msg_type: int, device_id: int,
                 seq_num: int, timestamp: int, readings: List[SensorReading], flags: int = 0):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings
        self.flags = flags


# encoding functions
def encode_header(version: int, msg_type: int, flags: int, device_id: int,
                  seq_num: int, timestamp: int) -> bytes:
    # format: version(1B) + msg_type(1B) + flags(1B) + device_id(2H) + seq_num(4I) + timestamp(4I) = 13 bytes
    return struct.pack('!BBBHII', version, msg_type, flags, device_id, seq_num, timestamp)


def encode_reading(sensor_type: int, value: float) -> bytes:
    return struct.pack('!Bf', sensor_type, value)


def encode_packet(packet: TelemetryPacket) -> bytes:
    """ turn complete packet into bytes and save it in data
    packet = header (13 bytes) + reading count (1 byte) * readings (5 bytes)"""

    # validation before encoding
    if packet.version != VERSION:
        raise ValueError(f"Invalid version: {packet.version}")

    if packet.msg_type not in (MSG_INIT, MSG_DATA, MSG_HEARTBEAT):
        raise ValueError(f"Unknown message type: {packet.msg_type}")

    if packet.device_id not in ALLOWED_DEVICE_IDS:
        raise ValueError(f"Invalid device ID: {packet.device_id}")

    if packet.seq_num is None or packet.seq_num < 0:
        raise ValueError(f"Invalid sequence number: {packet.seq_num}")

    # always encode header with correct field order (version, msg_type, flags, device_id, seq_num, timestamp)
    data = encode_header(packet.version, packet.msg_type, packet.flags,
                         packet.device_id, packet.seq_num, packet.timestamp)

    # INIT or HEARTBEAT
    if packet.msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if len(packet.readings) != 0:
            raise ValueError(f"{('INIT' if packet.msg_type == MSG_INIT else 'HEARTBEAT')} "
                             "packets must not contain readings")
        return data

    # encode readings
    if packet.msg_type == MSG_DATA:
        reading_count = len(packet.readings)

        if reading_count == 0:
            raise ValueError("DATA packet must contain at least one reading")

        # check total size
        total_size = HEADER_SIZE + 1 + reading_count * READING_SIZE
        if total_size > PAYLOAD_LIMIT:
            raise ValueError(f"Packet exceeds payload limit: {total_size} > {PAYLOAD_LIMIT}")

        # validate each reading list
        for idx, reading in enumerate(packet.readings):
            # invalid sensor type
            if reading.sensor_type not in (SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT):
                raise ValueError(f"Invalid sensor type in reading {idx}: {reading.sensor_type}")

            # invalid value (not finite or not int, float)
            if not isinstance(reading.value, (int, float)) or not math.isfinite(reading.value):
                raise ValueError(f"Invalid reading value in reading {idx}: {reading.value}")

        data += struct.pack('!B', reading_count)  # count how many readings 1 byte

        for reading in packet.readings:
            data += encode_reading(reading.sensor_type, reading.value)

        return data

    raise ValueError(f"Unreachable encoding state for msg_type: {packet.msg_type}")


# decoding functions

def decode_header(data: bytes) -> tuple:
    if len(data) < HEADER_SIZE:
        raise ValueError(f"Data too short for header: {len(data)} < {HEADER_SIZE}")
    # format: version, msg_type, flags, device_id, seq_num, timestamp (13 bytes total)
    return struct.unpack('!BBBHII', data[:HEADER_SIZE])


def decode_reading(data: bytes) -> tuple:
    if len(data) < READING_SIZE:
        raise ValueError(f"Not enough bytes for reading: {len(data)} < {READING_SIZE}")

    return struct.unpack('!Bf', data[:READING_SIZE])


def decode_packet(data: bytes) -> TelemetryPacket:
    # 1 Decode the 13-byte header (version, msg_type, flags, device_id, seq_num, timestamp)
    version, msg_type, flags, device_id, seq_num, timestamp = decode_header(data)
    # written like this bc decode header returns a tuple of 6 values

    # Step 2: Prepare to store readings
    readings = []

    # header validation
    if version != VERSION:
        raise ValueError(f"Version mismatch: expected {VERSION}, got {version}")

    if msg_type not in (MSG_INIT, MSG_DATA, MSG_HEARTBEAT):
        raise ValueError(f"Unknown msg_type: {msg_type}")

    if device_id not in ALLOWED_DEVICE_IDS:
        raise ValueError(f"Invalid device_id: {device_id}")

    if seq_num < 0:
        raise ValueError(f"Invalid sequence number: {seq_num}")

    # payload extraction
    payload = data[HEADER_SIZE:]
    payload_len = len(payload)

    # INIT / HEARTBEAT
    if msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if payload_len != 0:
            raise ValueError(f"{('INIT' if msg_type == MSG_INIT else 'HEARTBEAT')} "
                             "packets must have no payload")
        return TelemetryPacket(version, msg_type, device_id, seq_num, timestamp, [], flags)

    # DATA PACKETS
    if msg_type == MSG_DATA:
        # Step 3: If more than 12 bytes, it must have sensor data
        if payload_len < 1:
            raise ValueError("DATA packet missing reading_count byte")

        # Byte 13 = number of readings
        reading_count = payload[0]

        if reading_count <= 0:
            raise ValueError("DATA packet must contain at least 1 reading")

        expected_size = 1 + reading_count * READING_SIZE

        # leftover / truncated
        if payload_len < expected_size:
            raise ValueError(f"Truncated DATA packet: expected {expected_size}, got {payload_len}")

        if payload_len > expected_size:
            raise ValueError(f"Extra bytes in DATA packet: expected {expected_size}, got {payload_len}")

        # Step 4: Decode each reading
        offset = 1

        for i in range(reading_count):
            # offset safety check
            if offset + READING_SIZE > payload_len:
                raise ValueError(f"Truncated reading block at index {i}")

            sensor_type, value = decode_reading(payload[offset:offset + READING_SIZE])

            if sensor_type not in (SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT):
                raise ValueError(f"Invalid sensor_type in reading {i}: {sensor_type}")

            if not math.isfinite(value):
                raise ValueError(f"Invalid reading value in reading {i}: {value}")

            readings.append(SensorReading(sensor_type, value))
            offset += READING_SIZE

        # final leftover check
        if offset != payload_len:
            raise ValueError(f"Unused bytes after readings: {payload_len - offset} bytes remaining")

        # Step 5: Return the TelemetryPacket with flags
        return TelemetryPacket(version, msg_type, device_id, seq_num, timestamp, readings, flags)

    raise ValueError(f"Unreachable decoding state for msg_type: {msg_type}")


# batching functions
def create_reading_packet(sensor_type: int, value: float, device_id: int,
                          seq_num: int, timestamp: int) -> TelemetryPacket:
    # create a DATA packet containing one sensor reading (flags=0, not batched)
    reading = SensorReading(sensor_type, value)
    return TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=device_id,
        seq_num=seq_num,
        timestamp=timestamp,
        readings=[reading],
        flags=0
    )


def batch_packets(packets: List[TelemetryPacket]) -> TelemetryPacket:
    # merge N DATA packets in one packet when batching is ON
    if not packets:
        raise ValueError("No packets are present for batching")

    for idx, p in enumerate(packets):
        if p.msg_type != MSG_DATA:
            raise ValueError(f"Packet {idx} is not DATA so cannot batch {p.msg_type}")

    # error if readings to be batched not from the same device
    device_ids = {p.device_id for p in packets}
    if len(device_ids) != 1:
        raise ValueError(f"Cannot batch packets from different devices: {device_ids}")

    combined_readings: List[SensorReading] = []
    for p in packets:
        combined_readings.extend(p.readings)

    device_id = packets[0].device_id
    seq_num = max((p.seq_num for p in packets if p.seq_num is not None), default=0)
    timestamp = max((p.timestamp for p in packets if p.timestamp is not None), default=0)

    size = HEADER_SIZE + 1 + len(combined_readings) * READING_SIZE
    if size > PAYLOAD_LIMIT:
        raise ValueError(f"Batched packet exceeds payload limit: {size} > {PAYLOAD_LIMIT}")

    return TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=device_id,
        seq_num=seq_num,
        timestamp=timestamp,
        readings=combined_readings,
        flags=FLAG_BATCHING
    )


# function used by client
def send_packet(packets: List[TelemetryPacket], batching: Optional[bool] = None) -> List[bytes]:
    # check if batching should be enabled based on flags if not specified
    if batching is None:
        # check if any packet has batching flag set
        batching = any(p.flags & FLAG_BATCHING for p in packets)

    # no batching so call encode packet function
    if not batching:
        out = []
        for p in packets:
            out.append(encode_packet(p))

        return out

    # batching enabled
    groups: Dict[int, List[TelemetryPacket]] = {}
    for p in packets:
        if p.msg_type != MSG_DATA:
            raise ValueError("Batching only supports DATA packets")
        groups.setdefault(p.device_id, []).append(p)

    out_bytes: List[bytes] = []
    for device_id, plist in groups.items():
        # batch_packets() sets flags=FLAG_BATCHING
        batched = batch_packets(plist)
        out_bytes.append(encode_packet(batched))

    return out_bytes


# main function testing
if __name__ == "__main__":
    print("=" * 60)
    print("TESTING IOT TELEMETRY PROTOCOL")
    print("=" * 60)

    # ========== TEST 1: INIT PACKET ==========
    print("\n[TEST 1] INIT Packet")
    init_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_INIT,
        device_id=3001,
        seq_num=0,
        timestamp=1234567890,
        readings=[]
    )

    init_data = encode_packet(init_packet)
    print(f"✓ Encoded INIT packet: {len(init_data)} bytes")
    print(f"  Hex: {init_data.hex()}")

    decoded_init = decode_packet(init_data)
    print(f"✓ Decoded INIT packet:")
    print(f"  Device ID: {decoded_init.device_id}, Seq: {decoded_init.seq_num}")
    print(f"  Readings: {len(decoded_init.readings)} (expected 0)")

    # ========== TEST 2: HEARTBEAT PACKET ==========
    print("\n[TEST 2] HEARTBEAT Packet")
    hb_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_HEARTBEAT,
        device_id=3002,
        seq_num=5,
        timestamp=1234567895,
        readings=[]
    )

    hb_data = encode_packet(hb_packet)
    print(f"✓ Encoded HEARTBEAT packet: {len(hb_data)} bytes")
    print(f"  Hex: {hb_data.hex()}")

    decoded_hb = decode_packet(hb_data)
    print(f"✓ Decoded HEARTBEAT packet:")
    print(f"  Device ID: {decoded_hb.device_id}, Seq: {decoded_hb.seq_num}")

    # ========== TEST 3: DATA PACKET (SINGLE READING) ==========
    print("\n[TEST 3] DATA Packet (Single Reading)")
    single_data = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=3001,
        seq_num=1,
        timestamp=1234567900,
        readings=[SensorReading(SENSOR_TEMP, 25.5)]
    )

    single_data_bytes = encode_packet(single_data)
    print(f"✓ Encoded DATA packet: {len(single_data_bytes)} bytes")
    print(f"  Hex: {single_data_bytes.hex()}")

    decoded_single = decode_packet(single_data_bytes)
    print(f"✓ Decoded DATA packet:")
    print(f"  Device ID: {decoded_single.device_id}, Seq: {decoded_single.seq_num}")
    print(f"  Readings: {len(decoded_single.readings)}")
    for r in decoded_single.readings:
        print(f"    Sensor {r.sensor_type}: {r.value:.2f}")

    # ========== TEST 4: DATA PACKET (MULTIPLE READINGS) ==========
    print("\n[TEST 4] DATA Packet (Multiple Readings - Batched)")
    multi_data = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=3003,
        seq_num=10,
        timestamp=1234567910,
        readings=[
            SensorReading(SENSOR_TEMP, 25.0),
            SensorReading(SENSOR_HUM, 60.5),
            SensorReading(SENSOR_VOLT, 3.3)
        ]
    )

    multi_data_bytes = encode_packet(multi_data)
    print(f"✓ Encoded batched DATA packet: {len(multi_data_bytes)} bytes")
    print(f"  Hex: {multi_data_bytes.hex()}")

    decoded_multi = decode_packet(multi_data_bytes)
    print(f"✓ Decoded batched DATA packet:")
    print(f"  Device ID: {decoded_multi.device_id}, Seq: {decoded_multi.seq_num}")
    print(f"  Readings: {len(decoded_multi.readings)}")
    for r in decoded_multi.readings:
        sensor_name = {SENSOR_TEMP: "TEMP", SENSOR_HUM: "HUM", SENSOR_VOLT: "VOLT"}[r.sensor_type]
        print(f"    {sensor_name}: {r.value:.2f}")

    # ========== TEST 5: BATCHING FUNCTION ==========
    print("\n[TEST 5] Batching Multiple Packets")
    p1 = create_reading_packet(SENSOR_TEMP, 22.0, 3001, 20, 1234567920)
    p2 = create_reading_packet(SENSOR_TEMP, 23.0, 3001, 21, 1234567921)
    p3 = create_reading_packet(SENSOR_TEMP, 24.0, 3001, 22, 1234567922)

    batched = batch_packets([p1, p2, p3])
    print(f"✓ Batched 3 packets into 1")
    print(f"  Combined readings: {len(batched.readings)}")
    print(f"  Seq num (latest): {batched.seq_num}")
    print(f"  Flags: {batched.flags} (should be {FLAG_BATCHING})")

    batched_bytes = encode_packet(batched)
    print(f"✓ Encoded batched packet: {len(batched_bytes)} bytes")

    # ========== TEST 6: SEND_PACKET FUNCTION ==========
    print("\n[TEST 6] send_packet() Function")
    packets_to_send = [p1, p2, p3]

    # Without batching
    no_batch_bytes = send_packet(packets_to_send, batching=False)
    print(f"✓ Without batching: {len(no_batch_bytes)} packets encoded")

    # With batching
    with_batch_bytes = send_packet(packets_to_send, batching=True)
    print(f"✓ With batching: {len(with_batch_bytes)} packets encoded")

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED ✓")
    print("=" * 60)