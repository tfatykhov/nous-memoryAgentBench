@echo off
rem F085 Gate-1 repair chain (nous #564): per agent R1 re-run -> R2 re-run -> R3 all.
rem Rollback of the old R2 supersessions was executed separately (SQL) before launch.
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
set LOG=E:\Projects\nous-memoryAgentBench\reports\paper_baseline\repair_564_chain.log

call :one mab-eval-prod_memory-28b19787 sh_6k
call :one mab-eval-prod_memory-3ac49da7 sh_32k
call :one mab-eval-prod_memory-84e808c8 sh_64k
call :one mab-eval-prod_memory-39580836 sh_262k
call :one mab-eval-prod_memory-22353a27 mh_6k
call :one mab-eval-prod_memory-82ec74a5 mh_32k
call :one mab-eval-prod_memory-089599da mh_64k
call :one mab-eval-prod_memory-9a5951c2 mh_262k
echo CHAIN_ALL_DONE >> %LOG%
exit /b 0

:one
echo ===== %2 %1 R1 START ===== >> %LOG%
E:\Projects\nous\.venv\Scripts\python.exe scripts\backfill_enumerative_facts.py --agent-id %1 --density-threshold 0.0 >> %LOG% 2>&1
echo R1_%2_DONE rc=%ERRORLEVEL% >> %LOG%
echo ===== %2 %1 R2 START ===== >> %LOG%
E:\Projects\nous\.venv\Scripts\python.exe scripts\backfill_supersession.py --agent-id %1 --classifier-budget 0 >> %LOG% 2>&1
echo R2_%2_DONE rc=%ERRORLEVEL% >> %LOG%
echo ===== %2 %1 R3 START ===== >> %LOG%
E:\Projects\nous\.venv\Scripts\python.exe scripts\backfill_r3_entity_keys.py --agent-id %1 --phase all >> %LOG% 2>&1
echo R3_%2_DONE rc=%ERRORLEVEL% >> %LOG%
exit /b 0
