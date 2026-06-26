@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Packaging the application...
:: --windowed hides the console window
:: --noconfirm overwrites previous builds
:: --icon can be used if you have an icon, e.g., --icon=app.ico
pyinstaller --noconfirm --windowed --name "AcceptBot" main.py

echo.
echo =======================================================
echo Build complete! The executable is located in the "dist" folder.
echo Note: If Playwright fails to find the browser when running the exe, 
echo you may need to run "playwright install" on the target machine,
echo or package the browsers along with the executable.
echo =======================================================
pause
