"""
Mock Protocol Module - Phase 1
Use this to test client/server before real protocol is ready
"""
import time

# Constants
VERSION = 0x01
MSG_TYPE_INIT = 0x00
MSG_TYPE_DATA = 0x01
SENSOR_TEMP = 0x01
SENSOR_HUMID = 0x02
SENSOR_VOLT = 0x03

# Human-readable names
MSG_NAMES = {
    MSG_TYPE_INIT: "INIT",
    MSG_TYPE_DATA: "DATA"
}

SENSOR_NAMES = {
    SENSOR_TEMP: "Temperature",
    SENSOR_HUMID: "Humidity",
    SENSOR_VOLT: "Voltage"
}


class SensorReading:
    """Holds one sensor reading"""
    def __init__(self, sensor_type, value):
        self.sensor_type = sensor_type
        self.value = value

    def __repr__(self):
        return f"SensorReading(type={self.sensor_type}, value={self.value:.2f})"


class TelemetryPacket:
    """Holds complete packet information"""
    def __init__(self, version, msg_type, device_id, seq_num, timestamp, readings):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings

    def __repr__(self):
        return (f"TelemetryPacket(device={self.device_id}, msg_type={self.msg_type}, "
                f"seq={self.seq_num}, readings={len(self.readings)})")


def encode_packet(packet):
    """
    Encodes a TelemetryPacket into binary format

    INIT: 12 bytes (header only)
    DATA: 12 + 1 + (5 * num_readings) bytes
    """
    import struct

    # Header (12 bytes): version(1) + type(1) + device_id(2) + seq(4) + timestamp(4)
    header = struct.pack('!BBHII',
                        packet.version,
                        packet.msg_type,
                        packet.device_id,
                        packet.seq_num,
                        packet.timestamp)

    if packet.msg_type == MSG_TYPE_INIT:
        # INIT message: header only
        return header
    else:
        # DATA message: header + count + readings
        count = bytes([len(packet.readings)])
        readings_bytes = b''

        # Each reading: type(1) + value(4 float)
        for reading in packet.readings:
            readings_bytes += struct.pack('!Bf', reading.sensor_type, reading.value)

        return header + count + readings_bytes


def decode_packet(data):
    """
    Decodes a TelemetryPacket from binary format
    """
    import struct

    if len(data) < 12:
        raise ValueError(f"Packet too short: {len(data)} bytes")

    # Decode header (12 bytes)
    version, msg_type, device_id, seq_num, timestamp = struct.unpack('!BBHII', data[:12])

    readings = []
    if msg_type == MSG_TYPE_DATA and len(data) > 12:
        count = data[12]
        offset = 13

        for i in range(count):
            if offset + 5 <= len(data):
                sensor_type = data[offset]
                value = struct.unpack('!f', data[offset+1:offset+5])[0]
                readings.append(SensorReading(sensor_type, value))
                offset += 5

    return TelemetryPacket(version, msg_type, device_id, seq_num, timestamp, readings)


# For testing
if __name__ == '__main__':
    import time

    # Test INIT
    init = TelemetryPacket(VERSION, MSG_TYPE_INIT, 1001, 0, int(time.time()), [])
    init_bytes = encode_packet(init)
    print(f"INIT: {len(init_bytes)} bytes")

    # Test DATA
    readings = [
        SensorReading(SENSOR_TEMP, 25.0),
        SensorReading(SENSOR_HUMID, 50.0),
        SensorReading(SENSOR_VOLT, 5.0)
    ]
    data = TelemetryPacket(VERSION, MSG_TYPE_DATA, 1001, 1, int(time.time()), readings)
    data_bytes = encode_packet(data)
    print(f"DATA: {len(data_bytes)} bytes")

    # Test decode
    decoded = decode_packet(data_bytes)
    print(f"Decoded: {decoded}")
