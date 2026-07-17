@echo off
rem hearth — Windows shim; prefers the py launcher so the Microsoft Store
rem "python" alias stub can't swallow the command on fresh machines.
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0hearth.py" %*
) else (
  python "%~dp0hearth.py" %*
)
