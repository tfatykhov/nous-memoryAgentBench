@echo off
cd /d E:\Projects\nous-memoryAgentBench
set HF_HUB_DISABLE_PROGRESS_BARS=1
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\probe_ce_rerank_sim.py >> reports\paper_baseline\probe_ce_sim.log 2>&1
echo CE_SIM_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\probe_ce_sim.log
