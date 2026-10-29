@echo off
rem Flash a stock AHD2NET converter while keeping its MAC address.
rem Usage:  flash.cmd --port COM6
rem Runs flash_ahd2net.py with uv's Python, so no separate Python install is needed.
uv run "%~dp0flash_ahd2net.py" %*
