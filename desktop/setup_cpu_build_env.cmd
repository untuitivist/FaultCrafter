@echo off
setlocal
cd /d "%~dp0.."

if not defined FAULTCRAFTER_PYTHON set "FAULTCRAFTER_PYTHON=python"

if not exist ".venv-build-cpu\Scripts\python.exe" (
  "%FAULTCRAFTER_PYTHON%" -m venv .venv-build-cpu
  if errorlevel 1 exit /b 1
)

".venv-build-cpu\Scripts\python.exe" -m pip install --disable-pip-version-check -r desktop\requirements-build-cpu.txt
if errorlevel 1 exit /b 1

".venv-build-cpu\Scripts\python.exe" -c "import torch; assert torch.version.cuda is None; print('CPU build environment ready:', torch.__version__)"
if errorlevel 1 exit /b 1

endlocal
