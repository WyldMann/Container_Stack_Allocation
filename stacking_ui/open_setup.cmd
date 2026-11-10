@echo off
setlocal
pushd "%~dp0.." || exit /b 1
".venv\Scripts\python.exe" -B -m stacking_ui
set "stacking_setup_exit=%errorlevel%"
popd
if not "%stacking_setup_exit%"=="0" pause
exit /b %stacking_setup_exit%
