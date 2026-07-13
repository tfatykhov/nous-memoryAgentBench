@echo off
REM #558-era retest, two sequential arms (detached, resumable).
REM ARM 1 _558regress: compound current-nous (b3c97eb) vs published baseline —
REM   prod config, SA auto (off at eval density), pristine nous_mab_baseline.
REM   Measures the #555..#558 read-path cluster (seed-score threading is the
REM   headline live change; NOT a single-PR isolation — review C2).
REM ARM 2 _f053_spreadON_558: current SA stack (SUM->MAX + heart-fact seeds)
REM   over the repaired graph vs the prior f053+SA arm (0.684) — compound per
REM   review C3.
REM C1: MAB_SESSION_TIMEOUT_BACKSTOP is the knob that actually reaches the
REM   server (NOUS_SESSION_TIMEOUT in config files is reserved+overwritten).
cd /d E:\Projects\nous-memoryAgentBench
set MAB_NOUS_REPO=../nous
set MAB_NOUS_PYTHON=E:\Projects\nous\.venv\Scripts\python.exe
set MAB_CHUNK_CHARS=32000
set MAB_MAX_INGEST_CHUNKS=80
set MAB_TURN_DELAY_S=5
set MAB_HEALTH_TIMEOUT_S=300
set MAB_INGEST_SETTLE_TIMEOUT_S=1200
set MAB_SLEEP_SETTLE_TIMEOUT_S=1200
set MAB_SESSION_TIMEOUT_BACKSTOP=86400
set HF_HUB_DISABLE_PROGRESS_BARS=1
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
set MAB_RESUME=1

set MAB_DB_NAME=nous_mab_baseline
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\replay_cr_n320.py 40 _558regress configs/prod_memory.env >> reports\paper_baseline\cr_558regress.log 2>&1
echo ARM1_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\cr_558regress.log

set MAB_DB_NAME=nous_mab_f053
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\replay_cr_n320.py 40 _f053_spreadON_558 configs/prod_memory_f053_spreadon.env >> reports\paper_baseline\cr_f053_spreadON_558.log 2>&1
echo ARM2_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\cr_f053_spreadON_558.log
