@echo off
REM ForecastEngine launcher — starts the engine and opens the browser.
REM Writes only to %LOCALAPPDATA%\ForecastEngine. No registry, no admin.
echo Starting ForecastEngine...
start "" "%~dp0ForecastEngine.exe"
timeout /t 8 /nobreak >nul
start "" http://localhost:8501
echo.
echo If the browser did not open, go to http://localhost:8501
echo Leave the console window open while you use the app.
