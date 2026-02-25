@echo off
setlocal

:: Change to the script's directory
cd /d "%~dp0"

echo ==========================================
echo    SHARES AUDIT VERIFICATION TOOL SETUP
echo ==========================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not found! Please install Python and add it to PATH.
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
) else (
    echo Virtual environment found.
)

:: Activate virtual environment
call venv\Scripts\activate

:: Upgrade pip
python -m pip install --upgrade pip

:: Install requirements
echo Installing required libraries...
pip install -r requirements.txt

:: Run Streamlit app
echo Starting the application...
echo The browser should open automatically. If not, go to http://localhost:8501
streamlit run app.py --server.headless false
