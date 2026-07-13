@echo off
REM 4th-cell completion, auto-starts after _559on finishes:
REM ARM C _f053_flagsoff: repaired graph, SA off (auto-gate), injection flags off
REM   -> isolates anchor effect on the DEFAULT path (Stage-4 one-hop, no SA).
REM ARM D _f053_559on: repaired graph + #559 injection flags = current-prod
REM   approximation (prod ran the F053 remediation + has the fix available).
cd /d E:\Projects\nous-memoryAgentBench
:wait
findstr /C:"ARMB_DONE" reports\paper_baseline\cr_559on.log >nul 2>&1 || (timeout /t 120 /nobreak >nul & goto wait)
set MAB_NOUS_REPO=../nous
set MAB_NOUS_PYTHON=E:\Projects\nous\.venv\Scripts\python.exe
set MAB_DB_NAME=nous_mab_f053
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
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\replay_cr_n320.py 40 _f053_flagsoff configs/prod_memory.env >> reports\paper_baseline\cr_f053_flagsoff.log 2>&1
echo ARMC_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\cr_f053_flagsoff.log
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\replay_cr_n320.py 40 _f053_559on configs/prod_memory_injection_fix.env >> reports\paper_baseline\cr_f053_559on.log 2>&1
echo ARMD_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\cr_f053_559on.log
