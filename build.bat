@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [1/3] Building with PyInstaller (onedir, no extraction)...
python -m PyInstaller --noconfirm --clean --onedir --console --icon "%~dp0icons\cm-launcher.ico" --name "CM Launcher" --distpath "dist" --workpath "build" --specpath "build" "CM Launcher.py"
if errorlevel 1 goto :failed
echo [2/3] Copying _internal...
if exist "_internal" rmdir /s /q "_internal"
xcopy "dist\CM Launcher\_internal" "_internal\" /E /I /Y >nul
if errorlevel 1 goto :failed
echo [3/3] Copying CM Launcher.exe...
copy /y "dist\CM Launcher\CM Launcher.exe" "CM Launcher.exe" >nul
if errorlevel 1 goto :failed
echo Done: %~dp0CM Launcher.exe
echo Note: CM Launcher.exe must be distributed together with the _internal folder.
goto :eof
:failed
echo Build failed.
exit /b 1
