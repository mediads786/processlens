@echo off
setlocal
cd /d "%~dp0"
cls
echo ========================================
echo ProcessLens 1.0.3
echo ========================================
echo.

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "app\selfcheck.py"
  if errorlevel 1 goto :failed
  echo.
  py -3 "app\server.py"
  if errorlevel 1 goto :failed
  goto :end
)

where python >nul 2>nul
if %errorlevel%==0 (
  python "app\selfcheck.py"
  if errorlevel 1 goto :failed
  echo.
  python "app\server.py"
  if errorlevel 1 goto :failed
  goto :end
)

echo [FAIL] Python was not found in PATH.
goto :failed

:failed
echo.
echo ProcessLens could not start. The exact error is shown above.
pause
:end
endlocal
