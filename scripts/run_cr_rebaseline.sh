#!/usr/bin/env bash
# CR re-baseline under the sonnet-5 / date-leg / multi-cycle-consolidation config.
# Conflict_Resolution only (the clean, parametric-resistant competency), full
# pinned sample of 8 instances, memory-lift methodology (control arm on).
#
# Prereqs: ../nous checked out to origin/main (has date-leg F075/F076); eval DB
# nous_mab migrated & running on :5433.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

export MAB_NOUS_REPO=../nous
export MAB_NOUS_PYTHON="$(pwd)/../nous/.venv/Scripts/python.exe"
export MAB_DB_NAME=nous_mab
# Pacing (built-in backoff retry on 5xx; larger chunks = fewer turns).
export MAB_CHUNK_CHARS=32000
export MAB_MAX_INGEST_CHUNKS=80
export MAB_TURN_DELAY_S=10
export MAB_HEALTH_TIMEOUT_S=300
export MAB_INGEST_SETTLE_TIMEOUT_S=900
export MAB_SLEEP_SETTLE_TIMEOUT_S=900
# Multi-cycle consolidation: a single sleep may not create all connections.
export MAB_SLEEP_CYCLES=3
export HF_HUB_DISABLE_PROGRESS_BARS=1

PY=./.venv/Scripts/python.exe
echo "##### BEGIN CR re-baseline $(date -u +%H:%M:%S) #####"
$PY -m mab.cli run --competency conflict_resolution --max-instances 8 \
  --config-env-file configs/prod_memory.env --max-questions 8
echo "##### END CR re-baseline rc=$? $(date -u +%H:%M:%S) #####"
