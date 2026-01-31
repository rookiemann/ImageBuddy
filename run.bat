@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Check if Python exists
if not exist "python\python.exe" (
    echo ERROR: Portable Python not found!
    echo Please ensure the 'python' folder is present.
    pause
    exit /b 1
)

:: Check if base dependencies are installed
python\python.exe -c "import flask" 2>nul
if errorlevel 1 (
    echo.
    echo ============================================
    echo   ImageBuddy - First Time Setup
    echo ============================================
    echo.
    echo Installing base dependencies...
    python\python.exe -m pip install -q -r requirements-base.txt
    if errorlevel 1 (
        echo ERROR: Failed to install base dependencies.
        pause
        exit /b 1
    )
    echo Base dependencies installed.
    echo.
)

:: Check if PyTorch is installed
python\python.exe -c "import torch" 2>nul
if errorlevel 1 (
    echo.
    echo ============================================
    echo   AI Dependencies Required
    echo ============================================
    echo.
    echo PyTorch is required for AI image captioning.
    echo.
    echo Choose your installation:
    echo   [1] GPU - NVIDIA CUDA ~2.5GB (Recommended for NVIDIA GPUs, 10-50x faster)
    echo   [2] CPU - ~200MB (Works on any system, slower processing)
    echo   [3] Skip - Run without AI features
    echo.
    set /p choice="Enter choice (1/2/3): "

    if "!choice!"=="1" (
        echo.
        echo Installing PyTorch with CUDA support...
        echo This may take several minutes depending on your internet speed.
        echo.
        python\python.exe -m pip install -r requirements-gpu.txt
        if errorlevel 1 (
            echo.
            echo WARNING: GPU installation failed. You can try CPU version later.
            pause
        ) else (
            echo.
            echo GPU dependencies installed successfully!
        )
    ) else if "!choice!"=="2" (
        echo.
        echo Installing PyTorch CPU version...
        echo This may take a few minutes.
        echo.
        python\python.exe -m pip install -r requirements-cpu.txt
        if errorlevel 1 (
            echo.
            echo WARNING: CPU installation failed.
            pause
        ) else (
            echo.
            echo CPU dependencies installed successfully!
        )
    ) else (
        echo.
        echo Skipping AI dependencies. You can install them later from Settings.
    )
    echo.
)

:: Launch the app
echo Starting ImageBuddy...
start "" "python\pythonw.exe" app.py
