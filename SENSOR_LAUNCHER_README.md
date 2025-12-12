# Sensor Launcher - Quick Start Guide

## What it does
Runs temperature, humidity, and/or voltage sensor clients easily.

## Basic Usage

### 1. Start the server first:
```bash
python server.py
```

### 2. Run clients:

**Single client:**
```bash
python sensor_launcher.py --temp
python sensor_launcher.py --humid  
python sensor_launcher.py --volt
```

**All clients together:**
```bash
python sensor_launcher.py --all
```

**Custom settings:**
```bash
python sensor_launcher.py --all --duration 30 --interval 1.0
```

## Advanced Features

### Heartbeat (keep-alive):
```bash
python sensor_launcher.py --all --enable-heartbeat
```

### Batching (multiple readings per packet):
```bash
python sensor_launcher.py --all --enable-batching --batching-interval 10.0
```

### Custom device IDs:
```bash
python sensor_launcher.py --temp --temp-id 5001 --humid --humid-id 5002
```

## Common Options
- `--duration 20.0` - How long to run (seconds)
- `--interval 2.0` - Time between readings (seconds)  
- `--server-port 5000` - Server port
- `--sequential` - Run clients one after another (default: parallel)

## Examples

**Quick test (20 seconds):**
```bash
python sensor_launcher.py --all
```

**Long test with batching:**
```bash
python sensor_launcher.py --all --duration 60 --enable-batching --batching-interval 15.0 --interval 1.0
```

**Temperature only with heartbeat:**
```bash
python sensor_launcher.py --temp --enable-heartbeat --duration 30
```

## Output Files
- `sensor_test.csv` - Main data file
- `sensor_test_batch_details.csv` - Individual batch readings (if batching enabled)

## Help
```bash
python sensor_launcher.py --help
```