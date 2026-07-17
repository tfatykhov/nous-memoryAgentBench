@echo off
REM R2 supersession backfill (8 canonical agents) -> coverage probe -> STOP.
REM No replay in this chain (quota pause per Timur).
cd /d E:\Projects\nous
set DB_HOST=127.0.0.1
set DB_PORT=5433
set DB_USER=nous
set DB_PASSWORD=nous_eval
set DB_NAME=nous_mab_wp
set PYTHONPATH=E:\Projects\nous
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "ANTHROPIC_AUTH_TOKEN" .env`) do set ANTHROPIC_AUTH_TOKEN=%%b
for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "OPENAI_API_KEY" .env`) do set OPENAI_API_KEY=%%b
set LOG=E:\Projects\nous-memoryAgentBench\reports\paper_baseline\backfill_r2.log
for %%A in (mab-eval-prod_memory-22353a27 mab-eval-prod_memory-82ec74a5 mab-eval-prod_memory-089599da mab-eval-prod_memory-9a5951c2 mab-eval-prod_memory-28b19787 mab-eval-prod_memory-3ac49da7 mab-eval-prod_memory-84e808c8 mab-eval-prod_memory-39580836) do (
  echo ### %%A >> %LOG%
  E:\Projects\nous\.venv\Scripts\python.exe scripts\backfill_supersession.py --agent-id %%A >> %LOG% 2>&1
)
echo R2_DONE >> %LOG%
cd /d E:\Projects\nous-memoryAgentBench
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\probe_query_dilution.py > reports\paper_baseline\probe_post_r2.log 2>&1
echo PROBE_POST_R2_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\probe_post_r2.log
