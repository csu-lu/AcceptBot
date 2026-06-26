@echo off
echo =======================================================
echo Preparing Portable Build for AcceptBot
echo =======================================================

echo.
echo Step 1/3: Configuring Playwright to install browser locally...
set PLAYWRIGHT_BROWSERS_PATH=0

echo.
echo Step 2/3: Installing Chromium (this will download ~150MB of browser)...
playwright install chromium

echo.
echo Step 3/3: Packaging the application with PyInstaller...
pip install pyinstaller

REM PyInstaller hook for playwright will automatically bundle the local browsers
pyinstaller --noconfirm --windowed --name "AcceptBot_Portable" main.py

echo.
echo =======================================================
echo Build complete! 
echo The completely portable executable is located in the "dist" folder.
echo You can copy that entire folder to any other Windows computer 
echo and it will work immediately, without needing Python or Playwright.
echo =======================================================
pause
