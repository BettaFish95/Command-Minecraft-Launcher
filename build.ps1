# Run as UTF-8; stop on failure
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Set-Location -LiteralPath $PSScriptRoot

Write-Host "[1/3] Building with PyInstaller (onedir, no extraction)..." -ForegroundColor Cyan
python -m PyInstaller `
    --noconfirm --clean --onedir --console `
    --icon "$PSScriptRoot\icons\cm-launcher.ico" `
    --name "CM Launcher" `
    --distpath "dist" `
    --workpath "build" `
    --specpath "build" `
    "CM Launcher.py"

Write-Host "[2/3] Copying _internal..." -ForegroundColor Cyan
if (Test-Path "_internal") { Remove-Item "_internal" -Recurse -Force }
Copy-Item -LiteralPath "dist\CM Launcher\_internal" -Destination "_internal" -Recurse -Force

Write-Host "[3/3] Copying CM Launcher.exe..." -ForegroundColor Cyan
Copy-Item -LiteralPath "dist\CM Launcher\CM Launcher.exe" -Destination "CM Launcher.exe" -Force
Write-Host "Done: $PSScriptRoot\CM Launcher.exe" -ForegroundColor Green
Write-Host "Note: CM Launcher.exe must be distributed together with the _internal folder." -ForegroundColor Yellow
