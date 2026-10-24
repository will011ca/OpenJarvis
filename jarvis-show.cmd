@echo off
setlocal
set "ROOT=%~dp0"
"%ROOT%.venv\Scripts\python.exe" "%ROOT%jarvis_show.py" %*
exit /b %ERRORLEVEL%
