@echo off
cd /d E:\Projects\nous-memoryAgentBench
set HF_HUB_DISABLE_PROGRESS_BARS=1
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
E:\Projects\nous-memoryAgentBench\.venv\Scripts\python.exe scripts\probe_query_dilution.py > reports\paper_baseline\probe_coverage_gate.log 2>&1
echo GATE_DONE rc=%ERRORLEVEL% >> reports\paper_baseline\probe_coverage_gate.log
