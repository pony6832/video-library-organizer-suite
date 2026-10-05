# Build the standalone exe: dist\VideoLibraryViewer.exe
# Usage (from repo root): powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if (-not (Test-Path .venv)) { python -m venv .venv }
.\.venv\Scripts\python -m pip install -q -r requirements.txt pyinstaller
.\.venv\Scripts\python -m PyInstaller --noconfirm --clean packaging\VideoLibraryViewer.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }
# Sign the exe itself when a code signing certificate is configured (packaging/codesign.py at the repo root)
$codesign = Join-Path (Split-Path (Get-Location) -Parent) 'packaging\codesign.py'
if (Test-Path $codesign) {
    .\.venv\Scripts\python $codesign sign dist\VideoLibraryViewer.exe
    if ($LASTEXITCODE -ne 0) { throw "Signing failed" }
}
Get-Item dist\VideoLibraryViewer.exe | Select-Object Name, @{n='MB';e={[math]::Round($_.Length/1MB,1)}}
