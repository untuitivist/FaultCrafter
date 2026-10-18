@echo off
setlocal
cd /d "%~dp0.."

if not defined FAULTCRAFTER_PYTHON set "FAULTCRAFTER_PYTHON=python"

"%FAULTCRAFTER_PYTHON%" -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
  echo PyInstaller is missing. Install desktop\requirements-build.txt first.
  exit /b 1
)

if exist "dist\FaultCrafter-JiT-4Device-Web" (
  echo Output already exists: dist\FaultCrafter-JiT-4Device-Web
  echo Move or remove it only after confirming that replacement is intended.
  exit /b 2
)

set "FAULTCRAFTER_BUILD_VARIANT=gpu"
"%FAULTCRAFTER_PYTHON%" -m PyInstaller --noconfirm --workpath build\FaultCrafter-4Device-Web-GPU desktop\FaultCrafter.spec
if errorlevel 1 exit /b 1

echo Build complete: dist\FaultCrafter-JiT-4Device-Web\FaultCrafter-JiT-4Device-Web.exe
endlocal
