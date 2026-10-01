# Build the standalone exe: dist\VideoLibraryViewer.exe
# Usage (from repo root): powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\VideoLibraryViewer.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
Get-Item dist\VideoLibraryViewer.exe | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
