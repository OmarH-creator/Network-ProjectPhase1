import subprocess
import time
import os
import signal
import platform
import argparse
import sys
import threading
import shutil

# === ANSI COLORS ===
RESET = "\033[0m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RED = "\033[91m"
CYAN = "\033[96m"

# --- Detect Python executable (works on both Windows & Linux) ---
PYTHON_CMD = shutil.which("python") or shutil.which("python3")
if not PYTHON_CMD:
    print(f"{RED}[ERROR]{RESET} Could not find Python executable.")
    sys.exit(1)

SERVER_CMD = [PYTHON_CMD, "-u", "server.py"]


def stream_output(proc, prefix, logfile, color):
    """Reads subprocess stdout line-by-line and streams to console + logfile."""
    for line in iter(proc.stdout.readline, ''):
        sys.stdout.write(f"{color}{prefix}{RESET} {line}")
        logfile.write(line)
        logfile.flush()
    proc.stdout.close()


def run_baseline(args):
    print(f"{CYAN}=== Starting Baseline Test ==={RESET}")
    print(f"{BLUE}Launching server...{RESET}")

    server_log = open("server_log.txt", "w", buffering=1)
    client_log = open("client_log.txt", "w", buffering=1)

    # Start server in background and capture its output
    server_proc = subprocess.Popen(
        SERVER_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True
    )

    # Stream server output in background
    threading.Thread(
        target=stream_output,
        args=(server_proc, "[SERVER]", server_log, YELLOW),
        daemon=True
    ).start()

    # Wait for server startup
    time.sleep(2)
    print(f"{GREEN}[OK]{RESET} Server is running. Launching client...\n")

    client_cmd = [
        PYTHON_CMD, "-u", "client.py",
        "--device-id", str(args.device_id),
        "--server-host", args.server_host,
        "--server-port", str(args.server_port),
        "--interval", str(args.interval),
        "--duration", str(args.duration)
    ]

    try:
        # Start client and stream its output live
        client_proc = subprocess.Popen(
            client_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        for line in iter(client_proc.stdout.readline, ''):
            sys.stdout.write(f"{CYAN}[CLIENT]{RESET} {line}")
            client_log.write(line)
            client_log.flush()

        client_proc.wait()
        print(f"{GREEN}[SUCCESS]{RESET} Client finished execution.")
    except Exception as e:
        print(f"{RED}[ERROR]{RESET} {e}")
    finally:
        print(f"{YELLOW}Stopping server...{RESET}")
        try:
            if platform.system() == "Windows":
                server_proc.terminate()
            else:
                os.kill(server_proc.pid, signal.SIGTERM)
            server_proc.wait(timeout=2)
            print(f"{GREEN}[OK]{RESET} Server stopped.")
        except Exception as e:
            print(f"{RED}[WARN]{RESET} Could not stop server: {e}")

        server_log.close()
        client_log.close()

    print(f"\n{CYAN}=== Test Completed ==={RESET}")
    print(f"{BLUE}Logs saved to:{RESET}")
    print("  → server_log.txt")
    print("  → client_log.txt\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run baseline telemetry test")
    parser.add_argument("--device-id", type=int, default=1)
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=5000)
    parser.add_argument("--interval", type=int, default=1)
    parser.add_argument("--duration", type=int, default=10)
    args = parser.parse_args()
    run_baseline(args)
