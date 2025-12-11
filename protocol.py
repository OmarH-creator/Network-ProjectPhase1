from typing import List
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

ALLOWED_DEVICE_IDS = {1, 2, 3}

# size in bytes
HEADER_SIZE = 13  # header size: version(1), msg_type(1), device_id(2), seq_num(4), flags(1), timestamp(4)
READING_SIZE = 5
PAYLOAD_LIMIT = 200


class SensorReading:
    def __init__(self, sensor_type: int, value: float):
        self.sensor_type = sensor_type
        self.value = value


class TelemetryPacket:
    def __init__(self, version: int, msg_type: int, device_id: int, seq_num: int, timestamp: int,
                 readings: List[SensorReading], flags = 0):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings
        self.flags = flags


# --------------- encoding functions -------------

def encode_header(version, msg_type, device_id, seq_num, timestamp):
    return struct.pack('!BBHII', version, msg_type, device_id, seq_num, timestamp)


def encode_reading(sensor_type, value):
    return struct.pack('!Bf', sensor_type, value)


def encode_packet(packet: TelemetryPacket):
    """ turn complete packet into bytes and save it in data
    packet = header (12 bytes) + reading count (1 byte) * readings (5 bytes)
    NIT       -> header only
    HEARTBEAT -> header only
    DATA       -> header + reading_count + reading blocks """

    # always encode header
    data = encode_header(packet.version, packet.msg_type, packet.device_id, packet.seq_num, packet.timestamp)

    # makes sure no readings for INIT and HEARTBEAT
    if packet.msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if len(packet.readings) != 0:
            raise ValueError("INIT/HEARTBEAT packets cannot contain readings")
        return data

    # encode readings
    if packet.msg_type == MSG_DATA:
        reading_count = len(packet.readings)

        if reading_count == 0:
            raise ValueError("DATA packets must contain at least 1 reading")

        # error checks
        size = HEADER_SIZE + 1 + reading_count * READING_SIZE
        if size > PAYLOAD_LIMIT:
            raise ValueError("Packet exceeds payload limit")

        data += struct.pack('!B', len(packet.readings))  # count how many readings 1 byte

        for reading in packet.readings:
            data += encode_reading(reading.sensor_type, reading.value)

    return data


# --------------decoding functions---------------

def decode_header(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("Packet shorter than header")

    return struct.unpack("!BBHIBI", data[:HEADER_SIZE])


def decode_reading(data):
    if len(data) < READING_SIZE:
        raise ValueError("Not enough bytes for reading")
    return struct.unpack("!Bf", data[:READING_SIZE])


def decode_packet(data):
    # ------ DECODE HEADER ------
    version, msg_type, device_id, seq_num, flags, timestamp = decode_header(data)

    # ------ HEADER VALIDATION ------
    if version != VERSION:
        raise ValueError("Version mismatch")

    if msg_type not in (MSG_INIT, MSG_DATA, MSG_HEARTBEAT):
        raise ValueError("Unknown msg_type")

    if device_id not in ALLOWED_DEVICE_IDS:
        raise ValueError("Invalid device_id")

    if seq_num < 0:
        raise ValueError("Invalid sequence number")

    # extract payload
    payload = data[HEADER_SIZE:]
    payload_len = len(payload)

    # INIT / HEARTBEAT check - must be header only
    if msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if payload_len != 0:
            raise ValueError("INIT/HEARTBEAT must be header only")
        return TelemetryPacket(version, msg_type, device_id, seq_num,
                                timestamp, [], flags)
    

    # ------ DATA PACKETS ------
    if msg_type == MSG_DATA:

        # must have at least 1 byte for reading_count
        if payload_len < 1:
            raise ValueError("DATA missing reading_count")

        reading_count = payload[0]

        # must be EXACTLY 1 (no batching)
        if reading_count != 1:
            raise ValueError("DATA packet must contain exactly 1 reading")

        expected_size = 1 + READING_SIZE  # exactly 6 bytes
        if payload_len < expected_size:
            raise ValueError("Truncated DATA packet")
        if payload_len > expected_size:
            raise ValueError("Extra bytes in DATA packet")

        # decode the single reading
        sensor_type, value = decode_reading(payload[1:1 + READING_SIZE])

        if sensor_type not in (SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT):
            raise ValueError("Invalid sensor_type")

        if not math.isfinite(value):
            raise ValueError("Invalid reading value")

        reading = SensorReading(sensor_type, value)

        return TelemetryPacket(version, msg_type, device_id,
                               seq_num, timestamp, [reading], flags)

    raise ValueError("Unreachable")

# main function testing
if __name__ == "__main__":

    # TEST INIT
    init_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_INIT,
        device_id=1,
        seq_num=0,
        timestamp=1234567890,
        readings=[]
    )

    data = encode_packet(init_packet)
    print(f"INIT ({len(data)} bytes) -> {data.hex()}")

    # TEST HEARTBEAT
    heartbeat_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_HEARTBEAT,
        device_id=1,
        seq_num=5,
        timestamp=1234567895,
        readings=[]
    )

    hb_data = encode_packet(heartbeat_packet)
    print(f"HEARTBEAT ({len(hb_data)} bytes) -> {hb_data.hex()}")

    # TEST DATA
    data_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=1,
        seq_num=1,
        timestamp=1234567890,
        readings=[SensorReading(SENSOR_TEMP, 25.0)]
    )

    data2 = encode_packet(data_packet)
    print(f"DATA ({len(data2)} bytes) -> {data2.hex()}")

    # DECODE TESTS
    print("\nDecoded HEARTBEAT:")
    decoded_hb = decode_packet(hb_data)
    print(vars(decoded_hb))