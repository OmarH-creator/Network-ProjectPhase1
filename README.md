# 🛰️ TinyTelemetry v1

TinyTelemetry is a lightweight **UDP-based telemetry protocol** designed for IoT and embedded devices.  
It allows low-power sensors to send periodic readings (like temperature, humidity, and voltage) to a central data collector efficiently, using a compact binary message format.

This project includes:
- A **server** that collects and logs telemetry data.
- A **client** that simulates IoT sensor devices.
- A **protocol module** defining the message structure and encoding.
- An **automated experiment script** that runs both client and server together for testing and reproducibility.

---

## 🧠 Overview

TinyTelemetry v1 (TTv1) follows a simple **client–server model**:
- Each **client** represents a sensor device that periodically sends data packets to a **server**.
- Communication is **stateless** and uses **UDP**, meaning there are no retransmissions or acknowledgments — some packet loss is acceptable.
- Messages are encoded in binary using a fixed 12-byte header followed by compact sensor readings.

**Supported sensor types:**
- 🌡️ Temperature (`0x01`)
- 💧 Humidity (`0x02`)
- ⚡ Voltage (`0x03`)

---

## 🧩 Repository Structure
```bash
TinyTelemetry/
│
├── protocol.py # Defines the packet format, header fields, and encoding/decoding
├── server.py # Collects incoming telemetry packets and logs them to CSV
├── client.py # Simulates IoT devices sending periodic readings
├── auto_script_run.py # Automates the client-server experiment (cross-platform)
│
├── telemetry.csv # (Generated) Server data log
├── server_log.txt # (Generated) Server console output
├── client_log.txt # (Generated) Client console output
│
└── README.md # Project documentation
```

---

## ⚙️ Requirements

### ✅ Python Version
- Works on **Python 3.8+**
- Compatible with both **Windows** and **Linux**

### 📦 Dependencies
No external libraries are required beyond the Python standard library.

---

## 🚀 Running the Components
#### NOTE: each of these commands works with `python3` instead of `python` on linux distro.
### **1️⃣ Run the Server Manually**

```bash
python server.py --port 5000 --log-file telemetry.csv
```

By default, the server:
  -Listens on UDP **port 5000**
  and Logs data to **telemetry.csv**

### **2️⃣ Run a Client Manually**

```bash
python client.py --device-id 1 --server-host 127.0.0.1 --server-port 5000 --interval 1 --duration 10 --seed 123
```

| Argument        | Description                            | Required | Default |
| --------------- | -------------------------------------- | -------- | ------- |
| `--device-id`   | Unique device identifier               | ✅        | —       |
| `--server-host` | IP address or hostname of the server   | ✅        | —       |
| `--server-port` | UDP port number                        | ✅        | —       |
| `--interval`    | Time (in seconds) between readings     | ❌        | `1.0`   |
| `--duration`    | Duration of the experiment             | ❌        | `10.0`  |
| `--seed`        | Random seed for deterministic readings | ❌        | None    |


### **3️⃣ Run Both Automatically (Recommended)**
To simplify testing, use the automated runner script:
```bash
python auto_script_run.py --device-id 1 --server-host 127.0.0.1 --server-port 5000 --interval 1 --duration 10 --seed 123  --server-log-file telemetry.csv
```

This script will:
1. Launch the server automatically in the background.
2. Wait for it to start.
3. Launch the client with the given parameters.
4. Stream both outputs live to your terminal and log them to:
  ```bash
  server_log.txt
  client_log.txt
  ```
5. Stop the server automatically after completion.



### **Reproducibility**

To ensure deterministic behavior in experiments:

Each client can use the --seed parameter.
Running the client with the same seed will generate identical random readings each time.
Example:
```bash
python client.py --device-id 2 --server-host 127.0.0.1 --server-port 5000 --seed 42
```


🧱 Project Highlights

  Lightweight UDP telemetry protocol.
  Binary-encoded message structure for efficiency.
  Deterministic random generation for reproducible experiments.
  Automatic orchestration script with live streaming and logging.
  Cross-platform compatibility (Windows & Linux).


