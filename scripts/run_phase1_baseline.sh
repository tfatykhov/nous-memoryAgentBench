#!/usr/bin/env bash
# Phase 1 prod baseline: prod_memory config across the pinned sample, all four
# competencies, sequential (cheapest/most-relevant first). Each competency writes
# its own md+json report when it finishes.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

export MAB_NOUS_REPO=../nous
export MAB_NOUS_PYTHON="$(pwd)/../nous/.venv/Scripts/python.exe"
export MAB_DB_NAME=nous_mab
# Pacing for opus rate limits: larger chunks (fewer turns -> less system-prompt
# overhead -> lower total tokens) + per-turn delay + backoff retry (built in).
export MAB_CHUNK_CHARS=32000
export MAB_MAX_INGEST_CHUNKS=80
export MAB_TURN_DELAY_S=10
export MAB_HEALTH_TIMEOUT_S=300
export MAB_INGEST_SETTLE_TIMEOUT_S=900
export MAB_SLEEP_SETTLE_TIMEOUT_S=900
export HF_HUB_DISABLE_PROGRESS_BARS=1
PY=./.venv/Scripts/python.exe
CFG="--config-env-file configs/prod_memory.env --max-questions 8"

run() {
  local comp="$1"; shift
  echo "##### BEGIN ${comp} $(date -u +%H:%M:%S) #####"
  $PY -m mab.cli run --competency "$comp" "$@" $CFG
  echo "##### END ${comp} rc=$? $(date -u +%H:%M:%S) #####"
}

run conflict_resolution --max-instances 8
run accurate_retrieval --sources eventqa_65536 --max-instances 5
run test_time_learning --max-instances 3
run long_range_understanding --max-instances 5
echo "##### PHASE1 BASELINE DONE $(date -u +%H:%M:%S) #####"
