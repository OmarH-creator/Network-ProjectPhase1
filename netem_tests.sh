#!/bin/bash

# ==============================================================================
# 1. SETUP
# ==============================================================================
INTERFACE="lo"

# Robust Directory Handling
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_SCRIPT="$SCRIPT_DIR/server_besheer.py"
CLIENT_SCRIPT="$SCRIPT_DIR/sensor_launcher.py"
LOG_DIR="$SCRIPT_DIR/test_results"


# --- DEFAULT PARAMETERS ---
INTERVAL=0.2
DURATION=30.0
HB_INTERVAL=3.0
HB_PERIOD=2.0
ENABLE_HEARTBEAT="false"
SEQUENTIAL="false"

ENABLE_BATCHING="false"
BATCH_INTERVAL=0.5
# Server Params
AUTO_SHUTDOWN=""

# Test Scenario
SCENARIO=""
# ==============================================================================
# 2. ARGUMENT PARSING
# ==============================================================================

while [[ $# -gt 0 ]]; do
  case "$1" in
    --baseline) SCENARIO="baseline"; shift ;;
    --duplicate) SCENARIO="duplicate"; shift ;;
    --delay) SCENARIO="delay"; shift ;;
    --loss) SCENARIO="loss"; shift ;;
    --reorder) SCENARIO="reorder"; shift ;;
    --all) SCENARIO="all"; shift ;;

    --interval) INTERVAL="$2"; shift; shift ;;
    --duration) DURATION="$2"; shift; shift ;;
    --heartbeat-interval) HB_INTERVAL="$2"; shift; shift ;;
    --period-heartbeat) HB_PERIOD="$2"; shift; shift ;;
    --batching-interval) BATCH_INTERVAL="$2"; shift; shift ;;

    --enable-heartbeat) ENABLE_HEARTBEAT="true"; shift ;;
    --enable-batching) ENABLE_BATCHING="true"; shift ;;
    --sequential) SEQUENTIAL="true"; shift ;;

    --auto-shutdown) AUTO_SHUTDOWN="$2"; shift; shift ;;

    -h|--help)
      echo "Usage: ./run_tests.sh [SCENARIO] [OPTIONS]"
      exit 0
      ;;
    *) echo "Unknown: $1"; exit 1 ;;
  esac
done

if [ -z "$SCENARIO" ]; then
    echo "Error: No scenario selected."
    exit 1
fi

if [ -z "$AUTO_SHUTDOWN" ]; then
    AUTO_SHUTDOWN=$(python3 -c "print(int($DURATION+5))")
fi

mkdir -p "$LOG_DIR"

# ==============================================================================
# 3. HELPER FUNCTIONS
# ==============================================================================

cleanup_netem() {
    sudo tc qdisc del dev $INTERFACE root 2>/dev/null
}

run_single_test() {
    local TEST_NAME=$1
    local NETEM_CMD=$2

    local CSV_FILE="$LOG_DIR/telemetry_${TEST_NAME}.csv"
    local SERVER_LOG="$LOG_DIR/server_${TEST_NAME}.log"
    local CLIENT_LOG="$LOG_DIR/client_${TEST_NAME}.log"

    # --- FIX: Extract simple filenames for display ---
    local S_LOG_NAME=$(basename "$SERVER_LOG")
    local C_LOG_NAME=$(basename "$CLIENT_LOG")
    local CSV_NAME=$(basename "$CSV_FILE")

    echo ""
    echo "############################################################"
    echo "  RUNNING TEST: $TEST_NAME"
    echo "  Netem Rule: ${NETEM_CMD:-None}"
    echo "  Server Log: $S_LOG_NAME (Background)"
    echo "  Client Log: $C_LOG_NAME (Foreground)"
    echo "  CSV Output: $CSV_NAME"
    echo "############################################################"
    echo ""

    # 1. Apply Netem
    cleanup_netem
    if [ ! -z "$NETEM_CMD" ]; then
        echo "[NETWORK] Applying rule..."
        sudo tc qdisc add dev $INTERFACE root netem $NETEM_CMD
        if [ $? -ne 0 ]; then
            echo "[ERROR] Netem failed. Sudo required."
            return 1
        fi
    fi

    # 2. Start Server (BACKGROUND)
    # Output is directed to the log file so it doesn't clutter the screen
    echo "[SYSTEM] Starting Server..."
    python3 -u "$SERVER_SCRIPT" \
        --port 5000 \
        --log-file "$CSV_FILE" \
        --max-buffer 1000 \
        --max-gap-wait 5 \
        --auto-shutdown "$AUTO_SHUTDOWN" > "$SERVER_LOG" 2>&1 &
    SERVER_PID=$!

    # Give it a moment to boot
    sleep 2

    # 3. Build Client Command
    # We use -u for unbuffered output so logs update in real-time
    CLIENT_CMD=(python3 -u "$CLIENT_SCRIPT")
    CLIENT_CMD+=( --all)
    CLIENT_CMD+=( --interval "$INTERVAL" --duration "$DURATION")

    if [ "$ENABLE_HEARTBEAT" == "true" ]; then
        CLIENT_CMD+=(--enable-heartbeat --heartbeat-interval "$HB_INTERVAL" --period-heartbeat "$HB_PERIOD")
    fi

#    CLIENT_CMD+=(--enable-heartbeat --heartbeat-interval 5 --period-heartbeat 3)
#    CLIENT_CMD+=(--temp-id 3001 --humid-id 3002 --volt-id 3003)
#    CLIENT_CMD+=(--interval "$INTERVAL" --duration "$DURATION")
#    # Heartbeat enabled by default (Interval: 5, Period: 3)


    if [ "$ENABLE_BATCHING" == "true" ]; then
        CLIENT_CMD+=(--enable-batching --batching-interval "$BATCH_INTERVAL")
    fi

    if [ "$SEQUENTIAL" == "true" ]; then
        CLIENT_CMD+=(--sequential)
    fi

    # 4. Start Client (FOREGROUND)
    echo "[SYSTEM] Starting Clients..."
    echo "DEBUG: EXECUTING THE FOLLOWING:"
    echo "${CLIENT_CMD[@]}"
    # CRITICAL FIX:
    # 1. echo "" sends an "Enter" keypress to the python script so it doesn't get stuck.
    # 2. | tee saves output to file AND shows it on screen.
    echo "" | "${CLIENT_CMD[@]}" | tee "$CLIENT_LOG"

    CLIENT_EXIT=${PIPESTATUS[1]} # Check python exit code (index 1 because of the pipe)

    # 5. Cleanup
    echo "[SYSTEM] Waiting for Server Auto-shutdown..."
    wait $SERVER_PID

    cleanup_netem

    if [ $CLIENT_EXIT -eq 0 ]; then
        echo "[SUCCESS] Test '$TEST_NAME' Finished."
    else
        echo "[FAILURE] Clients crashed. Check $CLIENT_LOG."
    fi
}

# ==============================================================================
# 4. EXECUTION
# ==============================================================================

cleanup_netem

case "$SCENARIO" in
    baseline)  run_single_test "baseline" "" ;;
    duplicate) run_single_test "duplicate" "duplicate 15%" ;;
    loss)      run_single_test "loss" "loss 20%" ;;
    delay)     run_single_test "delay" "delay 1200ms 150ms distribution normal reorder 25% 50%" ;;
    reorder)   run_single_test "reorder" "delay 100ms reorder 25% 50%" ;;
    all)
        run_single_test "baseline" ""
        sleep 2
        run_single_test "duplicate" "duplicate 5%"
        sleep 2
        run_single_test "loss" "loss 5%"
        sleep 2
        run_single_test "delay" "delay 200ms 150ms distribution normal"
        sleep 2
        run_single_test "reorder" "delay 100ms reorder 25% 50%"
        ;;
esac