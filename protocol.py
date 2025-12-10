from typing import List
import struct

VERSION = 0x01

# message type
MSG_INIT = 0x00
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

# sensor type
SENSOR_TEMP = 0x01
SENSOR_HUM = 0x02
SENSOR_VOLT = 0x03

# size in bytes
HEADER_SIZE = 12
READING_SIZE = 5
PAYLOAD_LIMIT = 200


class SensorReading:
    def __init__(self, sensor_type: int, value: float):
        self.sensor_type = sensor_type
        self.value = value


class TelemetryPacket:
    def __init__(self, version: int, msg_type: int, device_id: int, seq_num: int, timestamp: int,
                 readings: List[SensorReading]):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings


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
    DATA       -> header + reading_count + reading blocks"""

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


# decoding functions

def decode_header(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("Data too short for header")

    return struct.unpack('!BBHII', data[:HEADER_SIZE])


def decode_reading(data):
    return struct.unpack('!Bf', data[:READING_SIZE])


def decode_packet(data):
    # 1 Decode the 12-byte header
    version, msg_type, device_id, seq_num, timestamp = decode_header(data)
    # written like this bc decode header returns a tuple of 5 values

    # Step 2: Prepare to store readings
    readings = []

    # Step 3: If more than 12 bytes, it must have sensor data
    if len(data) > HEADER_SIZE:
        # Byte 13 = number of readings
        count = struct.unpack('!B', data[HEADER_SIZE:HEADER_SIZE + 1])[0]

        # Step 4: Decode each reading
        offset = HEADER_SIZE + 1
        for _ in range(count):
            sensor_type, value = decode_reading(data[offset:offset + READING_SIZE])
            readings.append(SensorReading(sensor_type, value))
            offset += READING_SIZE

    # Step 5: Return the TelemetryPacket
    return TelemetryPacket(version, msg_type, device_id, seq_num, timestamp, readings)


# main function testing
if __name__ == "__main__":

    # test init packet
    init_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_INIT,  # INIT message
        device_id=1001,
        seq_num=0,
        timestamp=1234567890,
        readings=[]  # No readings for INIT
    )

    data = encode_packet(init_packet)
    print(f"Encoded INIT packet size: {len(data)} bytes")
    print(f"Hex: {data.hex()}")

    # test data packet
    data_packet = TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,  # DATA message
        device_id=1001,
        seq_num=1,
        timestamp=1234567890,
        readings=[SensorReading(SENSOR_TEMP, 25.0),
                  SensorReading(SENSOR_HUM, 60.5),
                  SensorReading(SENSOR_VOLT, 3.3)]  # Example readings
    )

    data2 = encode_packet(data_packet)
    print(f"Encoded DATA packet size: {len(data2)} bytes")
    print(f"Hex: {data2.hex()}")

    # TEST DECODING STARTS HERE

    # Decode the INIT packet
    decoded_init = decode_packet(data)
    print("\nDecoded INIT packet:")
    print(f"Version: {decoded_init.version}")
    print(f"Msg Type: {decoded_init.msg_type}")
    print(f"Device ID: {decoded_init.device_id}")
    print(f"Seq Num: {decoded_init.seq_num}")
    print(f"Timestamp: {decoded_init.timestamp}")
    print(f"Readings: {len(decoded_init.readings)} (expected 0)")

    # Decode the DATA packet
    decoded_data = decode_packet(data2)
    print("\nDecoded DATA packet:")
    print(f"Version: {decoded_data.version}")
    print(f"Msg Type: {decoded_data.msg_type}")
    print(f"Device ID: {decoded_data.device_id}")
    print(f"Seq Num: {decoded_data.seq_num}")
    print(f"Timestamp: {decoded_data.timestamp}")
    print(f"Number of readings: {len(decoded_data.readings)}")
    for r in decoded_data.readings:
        print(f"  Sensor type: {r.sensor_type}, Value: {r.value:.2f}")