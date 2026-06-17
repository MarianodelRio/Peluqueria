#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
HOST="http://localhost:8000"
BOT_PORT=8000
PHASES=(5 20 40 80 100 120 150)
PHASE_DURATION=60  # seconds per phase
RESULTS_FILE="tests/stress/results_$(date +%Y%m%d_%H%M%S).txt"

# ── Install dependencies ───────────────────────────────────────────────────────
echo "[run.sh] Installing locust and psutil..."
pip install --quiet locust psutil

# ── Start bot in stress mode ───────────────────────────────────────────────────
echo "[run.sh] Starting bot with STRESS_MODE=1..."
LOG_LEVEL=WARNING STRESS_MODE=1 uvicorn app.main:app \
    --port "$BOT_PORT" --log-level warning \
    > /tmp/stress_bot.log 2>&1 &
BOT_PID=$!
echo "[run.sh] Bot PID: $BOT_PID"

# ── Health check ──────────────────────────────────────────────────────────────
echo "[run.sh] Waiting for bot to be ready..."
for i in $(seq 1 30); do
    if curl -sf "$HOST/health" > /dev/null 2>&1; then
        echo "[run.sh] Bot is ready."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "[run.sh] ERROR: Bot did not become ready in time."
        kill "$BOT_PID" 2>/dev/null || true
        exit 1
    fi
    sleep 1
done

# ── Baseline RSS ──────────────────────────────────────────────────────────────
BASELINE_RSS=$(python3 -c "
import urllib.request, json
resp = urllib.request.urlopen('${HOST}/stress/stats')
data = json.loads(resp.read())
rss = data.get('rss_mb')
print(f'{rss:.1f}' if rss is not None else 'N/A')
")
echo "[run.sh] Baseline RSS: ${BASELINE_RSS} MB"
echo "[run.sh] Saving results to: $RESULTS_FILE"

# ── Intro ─────────────────────────────────────────────────────────────────────
{
printf "Stress Test — Escenario 1: Pico de concurrencia\n"
printf "Modo:        Calendar + WhatsApp mockeados (delays simulados)\n"
printf "Fecha:       %s\n" "$(date '+%Y-%m-%d %H:%M:%S')"
printf "STRESS_DATE: %s\n" "$(python3 -c 'from tests.stress.payloads import STRESS_DATE; print(STRESS_DATE)')"
printf "Fases:       %s usuarios / %ss por fase\n" "${PHASES[*]}" "$PHASE_DURATION"
printf "Baseline RSS: %s MB\n" "$BASELINE_RSS"
printf "%s\n" "$(printf '%.0s-' {1..80})"
} | tee "$RESULTS_FILE"

# ── Table header ──────────────────────────────────────────────────────────────
printf "\n%-8s %-10s %-10s %-10s %-10s %-10s %-10s %-10s\n" \
    "Users" "Count" "e2e_p50" "e2e_p95" "e2e_p99" "proc_p50" "Dropped" "RSS_MB" \
    | tee -a "$RESULTS_FILE"
printf "%s\n" "$(printf '%.0s-' {1..80})" | tee -a "$RESULTS_FILE"

# ── Run phases ────────────────────────────────────────────────────────────────
for USERS in "${PHASES[@]}"; do
    echo "[run.sh] Phase: $USERS users for ${PHASE_DURATION}s..."

    # Clear stats before each phase
    curl -sf -X DELETE "$HOST/stress/clear" > /dev/null

    # Run locust in headless mode
    locust \
        -f tests/stress/locustfile.py \
        --host "$HOST" \
        --users "$USERS" \
        --spawn-rate "$USERS" \
        --run-time "${PHASE_DURATION}s" \
        --headless \
        --only-summary \
        --loglevel WARNING \
        2>/dev/null || true

    # Wait a moment for in-flight requests to finish
    sleep 2

    # Collect stats from bot
    STATS=$(python3 -c "
import urllib.request, json
try:
    resp = urllib.request.urlopen('${HOST}/stress/stats')
    data = json.loads(resp.read())
    rss = data.get('rss_mb')
    rss_str = f'{rss:.1f}' if rss is not None else 'N/A'
    def ms(v): return str(int(round(v)))
    print(
        data.get('count', 0),
        ms(data['e2e_ms']['p50']),
        ms(data['e2e_ms']['p95']),
        ms(data['e2e_ms']['p99']),
        ms(data['processing_ms']['p50']),
        data.get('dropped', 0),
        rss_str,
    )
except Exception as e:
    print(0, 0, 0, 0, 0, 0, 'ERR')
")
    read COUNT E2E_P50 E2E_P95 E2E_P99 PROC_P50 DROPPED RSS_MB <<< "$STATS"

    printf "%-8s %-10s %-10s %-10s %-10s %-10s %-10s %-10s\n" \
        "$USERS" "$COUNT" "${E2E_P50}" "${E2E_P95}" "${E2E_P99}" \
        "${PROC_P50}" "$DROPPED" "${RSS_MB}" | tee -a "$RESULTS_FILE"
done

# ── RSS diff ──────────────────────────────────────────────────────────────────
FINAL_RSS=$(python3 -c "
import urllib.request, json
resp = urllib.request.urlopen('${HOST}/stress/stats')
data = json.loads(resp.read())
rss = data.get('rss_mb')
print(f'{rss:.1f}' if rss is not None else 'N/A')
")
printf "\nBaseline RSS: %s MB  |  Final RSS: %s MB\n" \
    "$BASELINE_RSS" "$FINAL_RSS" | tee -a "$RESULTS_FILE"
echo "[run.sh] Results saved to: $RESULTS_FILE"

# ── Teardown ──────────────────────────────────────────────────────────────────
echo "[run.sh] Killing bot (PID $BOT_PID)..."
kill "$BOT_PID" 2>/dev/null || true
wait "$BOT_PID" 2>/dev/null || true
echo "[run.sh] Done."
