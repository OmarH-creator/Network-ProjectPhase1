from typing import List, Dict, Optional
import struct
import math


VERSION = 0x01

#message type 
MSG_INIT = 0x00
MSG_DATA = 0x01
MSG_HEARTBEAT = 0x02

#sensor type 
SENSOR_TEMP = 0x01
SENSOR_HUM = 0x02
SENSOR_VOLT = 0x03

#size in bytes
HEADER_SIZE = 12 
READING_SIZE = 5 
PAYLOAD_LIMIT = 200

class SensorReading:
    def __init__(self, sensor_type: int, value: float):
        self.sensor_type = sensor_type
        self.value = value

class TelemetryPacket:
    def __init__(self, version: int, msg_type: int, device_id: int, seq_num: int, timestamp: int, readings: List[SensorReading]):
        self.version = version
        self.msg_type = msg_type
        self.device_id = device_id
        self.seq_num = seq_num
        self.timestamp = timestamp
        self.readings = readings



#encoding functions
def encode_header(version, msg_type, device_id, seq_num, timestamp):    
    return struct.pack('!BBHII', version, msg_type, device_id, seq_num, timestamp)

def encode_reading(sensor_type, value):
    return struct.pack('!Bf', sensor_type, value)

def encode_packet(packet: TelemetryPacket):

    """ turn complete packet into bytes and save it in data 
    packet = header (12 bytes) + reading count (1 byte) * readings (5 bytes)"""

    #validation before encoding
    if packet.version != VERSION:
        raise ValueError(f"Invalid version: {packet.version}")
    
    if packet.msg_type not in (MSG_INIT, MSG_DATA, MSG_HEARTBEAT):
        raise ValueError(f"Unknown message type: {packet.msg_type}")

    if packet.device_id <= 0 or packet.device_id > 0xFFFF:
        raise ValueError(f"Invalid device ID: {packet.device_id}")

    if packet.seq_num is None or packet.seq_num < 0:
        raise ValueError(f"Invalid sequence number: {packet.seq_num}")
    
    
    #validate readings exsit or not according to msg type
    if packet.msg_type == MSG_DATA:
        reading_count = len(packet.readings)
        if reading_count == 0:
            raise ValueError(f"DATA packet must contain at least one reading")
        
        #check total size
        size = HEADER_SIZE + 1 + reading_count * READING_SIZE
        if size > PAYLOAD_LIMIT:
            raise ValueError("Packet exceeds payload limit")

        #validate each reading list 
        for idx, reading in enumerate(packet.readings):
            #invalid sensor type
            if reading.sensor_type not in (SENSOR_TEMP, SENSOR_HUM, SENSOR_VOLT):
                raise ValueError(f"Invalid sensor type in reading {idx}: {reading.sensor_type}")
            
            #invalid value (not finite or not int, float)
            if not isinstance(reading.value, (int, float)) or not math.isfinite(reading.value):
                raise ValueError(f"Invalid reading value in reading {idx}: {reading.value}")

    #INIT or HEARTBEAT
    else:
        if packet.msg_type == MSG_INIT:
            if packet.readings:
                raise ValueError("INIT packets must not contain readings")
            
        if packet.msg_type == MSG_HEARTBEAT:
            if packet.readings:
                raise ValueError("HEARTBEAT packets must not contain readings")


    #always encode header
    data = encode_header(packet.version, packet.msg_type, packet.device_id, packet.seq_num, packet.timestamp)

    #encode readings
    if packet.msg_type == MSG_DATA:
        reading_count = len(packet.readings)

        #error checks
        size = HEADER_SIZE + 1 + reading_count * READING_SIZE
        if size > PAYLOAD_LIMIT:
            raise ValueError("Packet exceeds payload limit")

        data += struct.pack('!B', len(packet.readings)) #count how many readings 1 byte

        for reading in packet.readings:
            data += encode_reading(reading.sensor_type, reading.value)
    
    return data



#decoding functions

def decode_header(data):
    if len(data) < HEADER_SIZE:
        raise ValueError("Data too short for header")
    
    return struct.unpack('!BBHII', data[:HEADER_SIZE])

def decode_reading(data):
    return struct.unpack('!Bf', data[:READING_SIZE])

def decode_packet(data):
    #1 Decode the 12-byte header
    version, msg_type, device_id, seq_num, timestamp = decode_header(data)
    #written like this bc decode header returns a tuple of 5 values

    # Step 2: Prepare to store readings
    readings = []

    # Step 3: If more than 12 bytes, it must have sensor data
    if len(data) > HEADER_SIZE:
        # Byte 13 = number of readings
        count = struct.unpack('!B', data[HEADER_SIZE:HEADER_SIZE+1])[0]

        # Step 4: Decode each reading
        offset = HEADER_SIZE + 1
        for _ in range(count):
            sensor_type, value = decode_reading(data[offset:offset+READING_SIZE])
            readings.append(SensorReading(sensor_type, value))
            offset += READING_SIZE

    # Step 5: Return the TelemetryPacket
    return TelemetryPacket(version, msg_type, device_id, seq_num, timestamp, readings)




#batching functions
def create_reading_packet(sensor_type: int, value: float, device_id: int, seq_num: int, timestamp: int) -> TelemetryPacket:
    #create a DATA packet containing one sensor reading
    reading = SensorReading(sensor_type, value)
    return TelemetryPacket(
        version = VERSION,
        msg_type = MSG_DATA,
        device_id = device_id,
        seq_num = seq_num,
        timestamp = timestamp,
        readings = [reading]
    )

def batch_packet(packets: List[TelemetryPacket]) -> TelemetryPacket:
    #merge N DATA packets in one packet when batching is ON
    if not packets:
        raise ValueError("No packets are present for batching")
    
    for idx, p in enumerate(packets):
        if p.msg_type != MSG_DATA:
            raise ValueError(f"Packet {idx} is not DATA so cannot batch {p.msg_type}")

    #error if readings to be batched not from the same device
    device_ids = {p.device_id for p in packets}
    if len(device_ids) != 1:
        raise ValueError("Can only batch packets from the same device id")
    
    combined_readings: List[SensorReading] = []
    for p in packets:
        combined_readings.extend(p.readings)

    device_id = packets[0].device_id
    seq_num = max((p.seq_num for p in packets if p.seq_num is not None), default = 0)
    timestamp = max((p.timestamp for p in packets if p.timestamp is not None), default = 0)

    size = HEADER_SIZE + 1 + len(combined_readings) * READING_SIZE
    if size > PAYLOAD_LIMIT:
        raise ValueError(f"Batched packet exceeds payload limit ({size} > {PAYLOAD_LIMIT})")
    
    return TelemetryPacket(
        version=VERSION,
        msg_type=MSG_DATA,
        device_id=device_id,
        seq_num=seq_num,
        timestamp=timestamp,
        readings=combined_readings
    )

def chunk_packets(packets: List[TelemetryPacket]) -> List[TelemetryPacket]:
    if not packets:
        return[]

    for idx, p in enumerate(packets):
        if p.msg_type != MSG_DATA:
            raise ValueError(f"Packet {idx} is not DATA chunking not supported for {p.msg_type}")  
    
    #group packets by device id
    groups: Dict[int, List[TelemetryPacket]] = {}
    for p in packets:
        groups.setdefault(p.device_id, []).append(p)


    #calculate max reading per packet
    result: List[TelemetryPacket] = []
    max_packet_readings = (PAYLOAD_LIMIT - HEADER_SIZE - 1) // READING_SIZE
    if max_packet_readings <= 0:
        raise ValueError("PAYLOAD_LIMIT too small to fit any readings")
    
    #process each device's packets
    for device_id, plist in groups.items():
        all_readings: List[SensorReading] = []
        seq_nums: List[int] = []
        timestamps: List[int] = []
        for p in plist:
            all_readings.extend(p.readings)
            if p.seq_num is not None:
                seq_nums.append(p.seq_num)
            if p.timestamp is not None:
                timestamps.append(p.timestamp)

        for i in range(0, len(all_readings), max_packet_readings):
            chunk = all_readings[i:i + max_packet_readings]
            seq_num = max(seq_nums) if seq_nums else 0
            timestamp = max(timestamps) if timestamps else 0
            pkt = TelemetryPacket(
                version=VERSION,
                msg_type=MSG_DATA,
                device_id=device_id,
                seq_num=seq_num,
                timestamp=timestamp,
                readings=chunk
            )
            result.append(pkt)

    return result


#main function testing 
if __name__ == "__main__":
   
    #test init packet
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
    
 
    #test data packet
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
