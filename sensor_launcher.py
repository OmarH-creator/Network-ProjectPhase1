#!/usr/bin/env python3
"""
Sensor Client Launcher
Run temperature, humidity, and/or voltage clients individually or together
"""
import subprocess
import threading
import time
import sys
import argparse

def run_client_script(script_name, device_id, host, port, interval, duration, seed=None, heartbeat_interval=None, enable_heartbeat=False, period_heartbeat=None):
    """Run a client script with specified parameters"""
    
    cmd = [
        sys.executable, script_name,
        "--device-id", str(device_id),
        "--server-host", host,
        "--server-port", str(port),
        "--interval", str(interval),
        "--duration", str(duration)
    ]
    
    if seed is not None:
        cmd.extend(["--seed", str(seed)])
    
    if enable_heartbeat:
        cmd.append("--enable-heartbeat")
        if heartbeat_interval is not None:
            cmd.extend(["--heartbeat-interval", str(heartbeat_interval)])
        if period_heartbeat is not None:
            cmd.extend(["--period-heartbeat", str(period_heartbeat)])
    
    print(f"[LAUNCHER] Starting {script_name} with device ID {device_id}")
    
    try:
        # Run the client and capture output
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Print output in real-time
        for line in process.stdout:
            print(line.strip())
        
        process.wait()
        return process.returncode
        
    except Exception as e:
        print(f"[LAUNCHER] Error running {script_name}: {e}")
        return 1

def run_client_parallel(script_name, device_id, host, port, interval, duration, seed=None, heartbeat_interval=None, enable_heartbeat=False, period_heartbeat=None):
    """Run client in parallel thread"""
    return run_client_script(script_name, device_id, host, port, interval, duration, seed, heartbeat_interval, enable_heartbeat, period_heartbeat)

def main():
    parser = argparse.ArgumentParser(
        description="Sensor Client Launcher - Run temperature, humidity, and/or voltage clients",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run only temperature client
  python sensor_launcher.py --temp
  
  # Run only humidity client  
  python sensor_launcher.py --humid
  
  # Run temperature and voltage clients together
  python sensor_launcher.py --temp --volt
  
  # Run all three clients simultaneously
  python sensor_launcher.py --temp --humid --volt
  
  # Run with custom settings
  python sensor_launcher.py --temp --humid --duration 30 --interval 1.5
  
  # Run with heartbeat enabled (keep-alive functionality)
  python sensor_launcher.py --all --enable-heartbeat --heartbeat-interval 5.0 --period-heartbeat 2.0
  
  # Run with custom device IDs
  python sensor_launcher.py --temp --temp-id 4001 --humid --humid-id 4002
        """
    )
    
    # Client selection
    parser.add_argument("--temp", action="store_true", help="Run temperature client")
    parser.add_argument("--humid", action="store_true", help="Run humidity client")
    parser.add_argument("--volt", action="store_true", help="Run voltage client")
    parser.add_argument("--all", action="store_true", help="Run all three clients")
    
    # Device IDs
    parser.add_argument("--temp-id", type=int, default=3001, help="Temperature client device ID (default: 3001)")
    parser.add_argument("--humid-id", type=int, default=3002, help="Humidity client device ID (default: 3002)")
    parser.add_argument("--volt-id", type=int, default=3003, help="Voltage client device ID (default: 3003)")
    
    # Connection settings
    parser.add_argument("--server-host", default="127.0.0.1", help="Server hostname (default: 127.0.0.1)")
    parser.add_argument("--server-port", type=int, default=5000, help="Server port (default: 5000)")
    
    # Timing settings
    parser.add_argument("--interval", type=float, default=2.0, help="Interval between readings (default: 2.0s)")
    parser.add_argument("--duration", type=float, default=20.0, help="Total duration (default: 20.0s)")
    
    # Heartbeat settings
    parser.add_argument("--heartbeat-interval", type=float, default=10.0, help="Heartbeat interval when idle (default: 10.0s)")
    parser.add_argument("--period-heartbeat", type=float, default=3.0, help="Period between heartbeats during idle time (default: 3.0s)")
    parser.add_argument("--enable-heartbeat", action="store_true", help="Enable heartbeat functionality")
    
    # Seeds for reproducibility
    parser.add_argument("--temp-seed", type=int, help="Temperature client seed")
    parser.add_argument("--humid-seed", type=int, help="Humidity client seed")
    parser.add_argument("--volt-seed", type=int, help="Voltage client seed")
    
    # Execution mode
    parser.add_argument("--sequential", action="store_true", help="Run clients sequentially instead of parallel")
    
    args = parser.parse_args()
    
    # If --all is specified, enable all clients
    if args.all:
        args.temp = args.humid = args.volt = True
    
    # Check if at least one client is selected
    if not (args.temp or args.humid or args.volt):
        print("Error: You must specify at least one client to run.")
        print("Use --temp, --humid, --volt, or --all")
        print("Use --help for more information.")
        return
    
    # Prepare client configurations
    clients_to_run = []
    
    if args.temp:
        clients_to_run.append({
            'script': 'temp_client.py',
            'device_id': args.temp_id,
            'seed': args.temp_seed,
            'name': 'Temperature'
        })
    
    if args.humid:
        clients_to_run.append({
            'script': 'humid_client.py',
            'device_id': args.humid_id,
            'seed': args.humid_seed,
            'name': 'Humidity'
        })
    
    if args.volt:
        clients_to_run.append({
            'script': 'volt_client.py',
            'device_id': args.volt_id,
            'seed': args.volt_seed,
            'name': 'Voltage'
        })
    
    # Display configuration
    print("="*70)
    print("SENSOR CLIENT LAUNCHER")
    print("="*70)
    print(f"Server: {args.server_host}:{args.server_port}")
    print(f"Duration: {args.duration}s, Interval: {args.interval}s")
    print(f"Execution mode: {'Sequential' if args.sequential else 'Parallel'}")
    if args.enable_heartbeat:
        print(f"Heartbeat: Enabled, idle threshold: {args.heartbeat_interval}s, period: {args.period_heartbeat}s")
    else:
        print("Heartbeat: Disabled")
    print()
    print("Clients to run:")
    for client in clients_to_run:
        seed_info = f" (seed: {client['seed']})" if client['seed'] else " (default seed)"
        print(f"  - {client['name']} Client (ID: {client['device_id']}){seed_info}")
    print("="*70)
    
    # Check if server is ready
    print("\nMake sure server is running:")
    print(f"  python Network-ProjectPhase1/server.py --port {args.server_port} --log-file sensor_test.csv")
    print()
    
    try:
        input("Press Enter when server is ready (Ctrl+C to cancel)...")
    except KeyboardInterrupt:
        print("\nCancelled by user")
        return
    
    # Run clients
    if args.sequential:
        # Run clients one after another
        print(f"\n[LAUNCHER] Running {len(clients_to_run)} clients sequentially...")
        for client in clients_to_run:
            print(f"\n--- Starting {client['name']} Client ---")
            run_client_script(
                client['script'], client['device_id'], 
                args.server_host, args.server_port,
                args.interval, args.duration, client['seed'],
                args.heartbeat_interval, args.enable_heartbeat, args.period_heartbeat
            )
    else:
        # Run clients in parallel
        print(f"\n[LAUNCHER] Starting {len(clients_to_run)} clients in parallel...")
        
        threads = []
        for client in clients_to_run:
            thread = threading.Thread(
                target=run_client_parallel,
                args=(client['script'], client['device_id'], 
                      args.server_host, args.server_port,
                      args.interval, args.duration, client['seed'],
                      args.heartbeat_interval, args.enable_heartbeat, args.period_heartbeat)
            )
            thread.start()
            threads.append(thread)
        
        # Wait for all clients to complete
        for thread in threads:
            thread.join()
    
    print(f"\n[LAUNCHER] All clients completed!")
    print("Check sensor_test.csv for results!")

if __name__ == "__main__":
    main()