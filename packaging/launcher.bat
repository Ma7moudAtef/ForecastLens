@echo off
REM ForecastLens launcher — starts the engine and opens the browser.
REM Writes only to %LOCALAPPDATA%\ForecastLens. No registry, no admin.
start "" "%~dp0ForecastLens.exe"
timeout /t 6 /nobreak >nul
start "" http://localhost:8501
