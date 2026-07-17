@echo off
cd /d E:\Projects\nous
set DB_HOST=127.0.0.1
set DB_PORT=5433
set DB_USER=nous
set DB_PASSWORD=nous_eval
set DB_NAME=nous_mab_wp
set PYTHONPATH=E:\Projects\nous
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
set NOUS_ENUMERATIVE_MAX_FACTS_PER_EPISODE=0
set NOUS_ENUMERATIVE_MAX_CHUNKS_PER_EPISODE=0
set NOUS_ENUMERATIVE_EXTRACTION_MAX_PER_HOUR=0
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "OPENAI_API_KEY" .env`) do set OPENAI_API_KEY=%%b
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "ANTHROPIC_AUTH_TOKEN" .env`) do set ANTHROPIC_AUTH_TOKEN=%%b
E:\Projects\nous\.venv\Scripts\python.exe scripts\backfill_enumerative_facts.py --agent-id mab-eval-prod_memory-39580836 --density-threshold 0.0 >> E:\Projects\nous-memoryAgentBench\reports\paper_baseline\backfill_sh262k.log 2>&1
echo SH262K_DONE rc=%ERRORLEVEL% >> E:\Projects\nous-memoryAgentBench\reports\paper_baseline\backfill_sh262k.log
