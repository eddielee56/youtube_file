@echo off
cd /d "%~dp0"
py -3.12 -B autorender_v43.py review
if errorlevel 1 pause
