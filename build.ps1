# Build DriveSweep Windows release artifacts (portable .exe, --onedir zip, SHA256SUMS, and optional Inno Setup installer)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"

if (-not (Test-Path $PyInstaller)) {
    throw "Virtual environment not found at $Root\.venv. Create it and install requirements-dev.txt first."
}

Push-Location $Root
try {
    # 1. Generate multi-resolution app icon if missing
    & $Python "scripts\make_assets.py"

    # 2. Build portable single-file executable: dist\DriveSweep.exe
    & $PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onefile `
        --uac-admin `
        --name "DriveSweep" `
        --icon "assets\drivesweep.ico" `
        --version-file "version_info.txt" `
        --add-data "app\ui;app\ui" `
        --add-data "assets;assets" `
        "main.py"

    # 3. Build --onedir bundle (better AV reputation & installer input): dist\DriveSweep-win64\
    & $PyInstaller `
        --noconfirm `
        --clean `
        --windowed `
        --onedir `
        --uac-admin `
        --name "DriveSweep-win64" `
        --icon "assets\drivesweep.ico" `
        --version-file "version_info.txt" `
        --add-data "app\ui;app\ui" `
        --add-data "assets;assets" `
        "main.py"

    # PyInstaller names the inner exe after --name; rename to DriveSweep.exe inside DriveSweep-win64
    $innerExe = Join-Path $Root "dist\DriveSweep-win64\DriveSweep-win64.exe"
    $targetExe = Join-Path $Root "dist\DriveSweep-win64\DriveSweep.exe"
    if (Test-Path $innerExe) {
        if (Test-Path $targetExe) { Remove-Item $targetExe -Force }
        Rename-Item -Path $innerExe -NewName "DriveSweep.exe"
    }
    if (Test-Path (Join-Path $Root "LICENSE")) {
        Copy-Item -Path (Join-Path $Root "LICENSE") -Destination (Join-Path $Root "dist\DriveSweep-win64\LICENSE") -Force
    }

    # 4. Create distributable .zip of the --onedir folder
    $zipPath = Join-Path $Root "dist\DriveSweep-win64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $Root "dist\DriveSweep-win64\*") -DestinationPath $zipPath -CompressionLevel Optimal

    # 5. Compile Inno Setup installer if ISCC.exe is installed
    $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if (-not $iscc -and (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe")) {
        $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    }
    if ($iscc) {
        & $iscc (Join-Path $Root "installer\DriveSweep.iss")
    } else {
        Write-Host "Inno Setup (ISCC.exe) not found; skipped Setup.exe (installer\DriveSweep.iss is ready when Inno Setup is installed)." -ForegroundColor Yellow
    }

    # 6. Write SHA256SUMS.txt
    $hashLines = @()
    $targets = @("dist\DriveSweep.exe", "dist\DriveSweep-win64.zip") + @(Get-ChildItem (Join-Path $Root "dist\DriveSweep-Setup-*.exe") -ErrorAction SilentlyContinue | ForEach-Object { "dist\$($_.Name)" })
    foreach ($file in $targets) {
        $full = Join-Path $Root $file
        if (Test-Path $full) {
            $h = (Get-FileHash -Path $full -Algorithm SHA256).Hash.ToLower()
            $hashLines += "$h  $(Split-Path $full -Leaf)"
        }
    }
    Set-Content -Path (Join-Path $Root "dist\SHA256SUMS.txt") -Value $hashLines -Encoding UTF8

    Write-Host ""
    Write-Host "Build complete! Artifacts in dist\:" -ForegroundColor Green
    Get-ChildItem (Join-Path $Root "dist") -File | Select-Object Name, @{N="SizeMB";E={[math]::Round($_.Length/1MB,2)}} | Format-Table -AutoSize
} finally {
    Pop-Location
}
