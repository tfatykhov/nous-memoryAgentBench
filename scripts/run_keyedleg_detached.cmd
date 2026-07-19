@echo off
cd /d E:\Projects\nous-memoryAgentBench
set MAB_NOUS_REPO=../nous
set MAB_NOUS_PYTHON=E:\Projects\nous\.venv\Scripts\python.exe
set MAB_DB_NAME=nous_mab_wp
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
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\replay_cr_n320.py 40 _keyedleg configs/prod_memory_keyedleg.env >> reports\paper_baseline\cr_keyedleg.log 2>&1
echo KEYEDLEG_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\cr_keyedleg.log
