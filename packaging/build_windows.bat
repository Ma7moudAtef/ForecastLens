@echo off
REM Build the portable ForecastLens Windows bundle (one-dir + zip).
REM Run from the repository root on a Windows machine with Python 3.11:
REM     packaging\build_windows.bat

setlocal
cd /d "%~dp0.."

echo === Installing build dependencies ===
python -m pip install --upgrade pip || exit /b 1
pip install -e . pyinstaller || exit /b 1

echo === Building one-dir bundle ===
pyinstaller packaging\forecast.spec --noconfirm --distpath packaging\dist --workpath packaging\build || exit /b 1

echo === Adding launcher ===
copy /y packaging\launcher.bat packaging\dist\ForecastEngine\ForecastEngine-Start.bat || exit /b 1

echo === Zipping ===
powershell -NoProfile -Command "Compress-Archive -Path 'packaging/dist/ForecastEngine' -DestinationPath 'packaging/dist/ForecastEngine.zip' -Force" || exit /b 1

echo.
echo Done: packaging\dist\ForecastEngine.zip
echo Unzip anywhere, run ForecastEngine-Start.bat. No install, no admin.
endlocal
