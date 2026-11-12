@echo off
rem Launch Dida365 desktop task widget
setlocal
set "PYW=pythonw"
start "" "%PYW%" "%~dp0dida_widget.py"
