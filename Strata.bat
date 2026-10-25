@echo off
setlocal
rem Launches Strata. First run creates a virtual environment and installs dependencies.
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up Python environment...
    where py >nul 2>nul
    if %errorlevel%==0 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
    if not exist ".venv\Scripts\python.exe" (
        echo.
        echo Could not create the environment. Install Python 3.10+ from python.org
        echo and tick "Add python.exe to PATH" in the installer, then run this again.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo Installing dependencies failed - see the messages above.
        rmdir /s /q .venv
        pause
        exit /b 1
    )
)

rem Environments made before a dependency was added get it installed here (e.g. h5py for .spp import).
".venv\Scripts\python.exe" -c "import h5py" >nul 2>nul
if errorlevel 1 (
    echo Installing new dependencies...
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)

".venv\Scripts\python.exe" run.py %*
if errorlevel 1 (
    echo.
    echo Strata exited with an error - see the messages above.
    pause
)
