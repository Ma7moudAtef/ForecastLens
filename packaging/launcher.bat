@echo off
REM ForecastLens launcher — starts the engine and opens the browser.
REM Writes only to %LOCALAPPDATA%\ForecastLens. No registry, no admin.
echo Starting ForecastLens...
start "" "%~dp0ForecastLens.exe"
timeout /t 8 /nobreak >nul
start "" http://localhost:8501
echo.
echo If the browser did not open, go to http://localhost:8501
echo Leave the console window open while you use the app.
