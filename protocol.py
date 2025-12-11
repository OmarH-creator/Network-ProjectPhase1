from typing import List
import struct
import math 


VERSION = 0x01

# message types
MSG_INIT = 0x00
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# sensor types
SENSOR_TEMP = 0x01
SENSOR_HUM = 0x02
SENSOR_VOLT = 0x03

ALLOWED_DEVICE_IDS = {1, 2, 3}

# sizes
HEADER_SIZE = 13   # version(1), msg_type(1), device_id(2), seq_num(4), flags(1), timestamp(4)
READING_SIZE = 5   # sensor_type(1) + float(4)
PAYLOAD_LIMIT = 200


# -------------------- DATA CLASSES --------------------

class SensorReading:
    def __init__(self, sensor_type: int, value: float):
        self.sensor_type = sensor_type
        self.value = value


class TelemetryPacket:
    def __init__(self, version: int, msg_type: int, device_id: int, seq_num: int,
                 timestamp: int, readings: List[SensorReading], flags=0):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings
        self.flags = flags


# -------------------- ENCODING --------------------

def encode_header(version, msg_type, device_id, seq_num, timestamp):
    """Header: version, msg_type, device_id, seq_num, flags (0), timestamp"""
    flags = 0  # or set actual flags if needed
    return struct.pack('!BBHIBI', version, msg_type, device_id, seq_num, flags, timestamp)


def encode_reading(sensor_type, value):
    return struct.pack('!Bf', sensor_type, value)


def encode_packet(packet: TelemetryPacket):
    """
    INIT       -> header only
    HEARTBEAT  -> header only
    DATA       -> header + reading_count + reading blocks
    """
    data = encode_header(packet.version, packet.msg_type,
                         packet.device_id, packet.seq_num, packet.timestamp)

    # INIT and HEARTBEAT must never contain readings
    if packet.msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if len(packet.readings) != 0:
            raise ValueError("INIT/HEARTBEAT packets cannot contain readings")
        return data

    # DATA encoding (batching supported)
    if packet.msg_type == MSG_DATA:

        reading_count = len(packet.readings)
        if reading_count == 0:
            raise ValueError("DATA packets must have at least 1 reading")

        size = HEADER_SIZE + 1 + reading_count * READING_SIZE
        if size > PAYLOAD_LIMIT:
            raise ValueError("Packet exceeds size limit")

        # write reading_count
        data += struct.pack('!B', reading_count)

        # write each reading
        for reading in packet.readings:
            data += encode_reading(reading.sensor_type, reading.value)

        return data

    raise ValueError("Unknown msg_type during encoding")


# -------------------- DECODING --------------------

def decode_header(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("Packet shorter than header")
    return struct.unpack("!BBHIBI", data[:HEADER_SIZE])


def decode_reading(data):
    if len(data) < READING_SIZE:
        raise ValueError("Not enough bytes for reading")
    return struct.unpack("!Bf", data[:READING_SIZE])


def decode_packet(data):
    # ---------------- HEADER -----------------
    version, msg_type, device_id, seq_num, flags, timestamp = decode_header(data)

    # ---------------- HEADER VALIDATION -----------------
    if version != VERSION:
        raise ValueError("Version mismatch")

    if msg_type not in (MSG_INIT, MSG_DATA, MSG_HEARTBEAT):
        raise ValueError("Unknown msg_type")

    if device_id not in ALLOWED_DEVICE_IDS:
        raise ValueError("Invalid device_id")

    if seq_num < 0:
        raise ValueError("Invalid sequence number")

    # ---------------- PAYLOAD EXTRACTION -----------------
    payload = data[HEADER_SIZE:]
    payload_len = len(payload)

    # ---------------- INIT / HEARTBEAT -----------------
    if msg_type in (MSG_INIT, MSG_HEARTBEAT):
        if payload_len != 0:
            raise ValueError("INIT/HEARTBEAT must be header only")
        return TelemetryPacket(version, msg_type, device_id,
                               seq_num, timestamp, [], flags)

    # ---------------- DATA PACKETS -----------------
    if msg_type == MSG_DATA:

        # must have reading_count byte
        if payload_len < 1:
            raise ValueError("DATA missing reading_count")

        offset = 0

        # -------- reading_count --------
        reading_count = payload[offset]
        offset += 1

        if reading_count <= 0:
            raise ValueError("DATA must contain >= 1 reading")

        expected_size = 1 + reading_count * READING_SIZE

        # leftover / truncated
        if payload_len < expected_size:
            raise ValueError("Truncated DATA packet")
        if payload_len > expected_size:
            raise ValueError("Extra bytes in DATA packet")

        readings = []

        # -------- decode each reading --------
        for i in range(reading_count):

            # offset safety check
            if offset + READING_SIZE > payload_len:
                raise ValueError("Truncated reading block")

            sensor_type, value = decode_reading(
                payload[offset:offset + READING_SIZE])

            if sensor_type not in (SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT):
                raise ValueError("Invalid sensor_type")

            if not math.isfinite(value):
                raise ValueError("Invalid reading value")

            readings.append(SensorReading(sensor_type, value))
            offset += READING_SIZE

        # final leftover check
        if offset != payload_len:
            raise ValueError("Extra unused bytes found after readings")

        return TelemetryPacket(version, msg_type, device_id,
                               seq_num, timestamp, readings, flags)

    raise ValueError("Unreachable decoding state")


# -------------------- TESTING --------------------

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
    print("INIT:", data.hex())

    # TEST HEARTBEAT
    hb_packet = TelemetryPacket(
        VERSION, MSG_HEARTBEAT, 1, 3, 1234567895, []
    )
    hb_data = encode_packet(hb_packet)
    print("HEARTBEAT:", hb_data.hex())

    # TEST MULTI-READING DATA
    data_packet = TelemetryPacket(
        VERSION, MSG_DATA, 1, 10, 1234567899,
        readings=[
            SensorReading(SENSOR_TEMP, 25.0),
            SensorReading(SENSOR_HUM, 60.5),
            SensorReading(SENSOR_VOLT, 3.3)
        ]
    )

    data3 = encode_packet(data_packet)
    print("DATA:", data3.hex())

    decoded = decode_packet(data3)
    print("Decoded DATA:", [(r.sensor_type, r.value) for r in decoded.readings])
