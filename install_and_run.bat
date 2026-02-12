@echo off
setlocal

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python is not installed. Please install Python 3.8+ and try again.
    pause
    exit /b
)

:: Create virtual environment if it doesn't exist
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate virtual environment
call venv\Scripts\activate

:: Install requirements
echo Installing requirements...
pip install -r requirements.txt

:: Run the application
echo Starting the application...
start http://localhost:8501
streamlit run app.py

:: Deactivate (though script will end)
deactivate

endlocal
