@echo off
:: Build a single-file TestHubStudio.exe (run this ONCE on your machine).
:: Keep the exe where it lands, testhubui\dist\ — the Studio finds the
:: accelerators beside testhubui by walking up from the exe, so the whole
:: repo layout ships with it. End users need nothing else installed.
cd /d "%~dp0"
py -3 -m pip install --quiet pyinstaller flask openpyxl || python -m pip install --quiet pyinstaller flask openpyxl
pyinstaller --onefile --name TestHubStudio ^
    --add-data "static;static" ^
    --hidden-import openpyxl ^
    app.py
echo.
echo Done — dist\TestHubStudio.exe is your distributable. Double-click to launch.
pause
