@echo off
rem Launch Dida365 desktop task widget
setlocal
set "PYW=C:\Program Files\Python313\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%~dp0dida_widget.py"
