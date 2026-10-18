@echo off
setlocal
cd /d "%~dp0.."

set "CPU_BUILD_PYTHON=.venv-build-cpu\Scripts\python.exe"
if not exist "%CPU_BUILD_PYTHON%" (
  echo CPU build environment is missing. Run desktop\setup_cpu_build_env.cmd first.
  exit /b 1
)

"%CPU_BUILD_PYTHON%" -c "import PyInstaller, torch; assert torch.version.cuda is None" >nul 2>nul
if errorlevel 1 (
  echo CPU-only Torch or PyInstaller is missing from the build environment.
  exit /b 1
)

if exist "dist\FaultCrafter-JiT-4Device-Web-CPU-Batch" (
  echo Output already exists: dist\FaultCrafter-JiT-4Device-Web-CPU-Batch
  echo Move or remove it only after confirming that replacement is intended.
  exit /b 2
)

set "FAULTCRAFTER_BUILD_VARIANT=cpu_batch"
"%CPU_BUILD_PYTHON%" -m PyInstaller --noconfirm --workpath build\FaultCrafter-4Device-Web-CPU-Batch desktop\FaultCrafter.spec
if errorlevel 1 exit /b 1

echo Build complete: dist\FaultCrafter-JiT-4Device-Web-CPU-Batch\FaultCrafter-JiT-4Device-Web-CPU-Batch.exe
endlocal
