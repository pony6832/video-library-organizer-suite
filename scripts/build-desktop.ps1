param([ValidatePattern('^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$')][string]$BuildId = (Get-Date -Format 'yyyyMMdd-HHmmss'))
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$compiler = Join-Path $projectRoot '.tools\build\inno\ISCC.exe'
foreach ($toolPath in @($python, $compiler)) {
    if (-not (Test-Path -LiteralPath $toolPath -PathType Leaf)) { throw "Missing build tool: $toolPath" }
}
# Never clean or overwrite a previous build; validate every existing ancestor.
foreach ($relative in @('build', 'build\desktop', 'dist', "build\desktop\$BuildId", "dist\$BuildId")) {
    $candidate = [IO.Path]::GetFullPath((Join-Path $projectRoot $relative))
    if (-not $candidate.StartsWith($projectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Output escaped project' }
    if (Test-Path -LiteralPath $candidate) {
        $item = Get-Item -LiteralPath $candidate -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'Reparse output directory refused' }
        if (-not $item.PSIsContainer) { throw 'Output is not a directory' }
        if ($relative -eq "build\desktop\$BuildId" -or $relative -eq "dist\$BuildId") { throw 'Build ID already exists; choose a new ID' }
    }
}
$work = Join-Path $projectRoot "build\desktop\$BuildId"
$release = Join-Path $projectRoot "dist\$BuildId"
New-Item -ItemType Directory -Path $work, $release | Out-Null
Push-Location $projectRoot
try {
    & $python -m PyInstaller --noconfirm --workpath $work --distpath $release packaging/desktop.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }
    $bundle = Join-Path $release 'MediaCatalogVideoDesktop'
    Copy-Item -LiteralPath packaging/README-zh-TW.md, packaging/THIRD-PARTY-NOTICES.txt -Destination $bundle
    & $python packaging/audit_bundle.py $bundle --frozen-archive
    if ($LASTEXITCODE -ne 0) { throw 'Bundle audit failed' }
    # Smart App Control checks every executable file, so sign the whole bundle
    # when a certificate is configured (packaging/codesign.py says how).
    & $python packaging/codesign.py status
    & $python packaging/codesign.py sign $bundle
    if ($LASTEXITCODE -ne 0) { throw 'Signing the desktop bundle failed' }
    # pyproject.toml is the single source of the release version.
    $appVersion = (& $python -c "import sys, tomllib; print(tomllib.load(open(sys.argv[1], 'rb'))['project']['version'])" (Join-Path $projectRoot 'pyproject.toml')).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $appVersion) { throw 'Cannot read version from pyproject.toml' }
    # The media library panel (viewer\) is built from this repository and
    # installed beside the desktop app in {app}\viewer. Its own build script
    # keeps a separate virtual environment in viewer\.venv.
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $projectRoot 'viewer\packaging\build.ps1')
    if ($LASTEXITCODE -ne 0) { throw 'Viewer build failed' }
    $viewerDir = Join-Path $release 'viewer'
    New-Item -ItemType Directory -Path $viewerDir | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'viewer\dist\VideoLibraryViewer.exe'),
                           (Join-Path $projectRoot 'viewer\packaging\LAN-share.bat') -Destination $viewerDir
    $innoArgs = @('/Q', "/DBundleDir=$bundle", "/DReleaseDir=$release", "/DAppVersion=$appVersion", "/DViewerDir=$viewerDir")
    & $python -c "import sys; sys.path.insert(0, 'packaging'); import codesign; sys.exit(0 if codesign.configured() else 1)"
    if ($LASTEXITCODE -eq 0) {
        # Inno Setup signs the installer and the uninstaller it embeds through this command.
        $signer = Join-Path $projectRoot 'packaging\codesign.py'
        $innoArgs += @('/DSignInstaller', "/Svlosign=`$q$python`$q `$q$signer`$q sign `$f")
    }
    & $compiler @innoArgs packaging/MediaCatalogVideoDesktop.iss
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    # Report anything left unsigned; VLO_SIGN_REQUIRED=1 turns it into a failure.
    & $python packaging/codesign.py verify $bundle $viewerDir (Join-Path $release 'VideoLibraryOrganizer-Setup.exe')
    if ($LASTEXITCODE -ne 0) { throw 'Unsigned executable files remain' }
    $files = @(Get-ChildItem -LiteralPath $release -Recurse -File)
    $receipt = @($files | ForEach-Object {
        [ordered]@{ path = $_.FullName.Substring($release.Length + 1); bytes = $_.Length; sha256 = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash }
    })
    $receipt | ConvertTo-Json -Depth 3 | Set-Content -LiteralPath (Join-Path $release 'SHA256.json') -Encoding UTF8
    Write-Output "Release directory: $release"
} finally { Pop-Location }
