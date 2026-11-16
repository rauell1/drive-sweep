# Build DriveSweep Windows release artifacts.
#
# Stages let CI sign every executable in the right order:
#   Binaries   PyInstaller portable exe (dist\DriveSweep.exe) and folder bundle (dist\DriveSweep-win64\)
#   Package    zip of the (signed) folder bundle and the Inno Setup installer in dist\setup\
#   Checksums  copy the (signed) installer into dist\ and write dist\SHA256SUMS.txt
#   All        every stage in order (default, for local builds)
#
# The app is built with an asInvoker manifest (no --uac-admin): DriveSweep runs as a standard
# user and asks Windows for Administrator rights only when the user chooses a system task.
param(
    [ValidateSet("All", "Binaries", "Package", "Checksums")]
    [string]$Stage = "All"
)
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
$Dist = Join-Path $Root "dist"
$SetupOut = Join-Path $Dist "setup"

function Invoke-Checked([string]$Exe, [string[]]$Arguments) {
    & $Exe @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Exe failed with exit code $LASTEXITCODE" }
}

function Build-Binaries {
    if (-not (Test-Path $PyInstaller)) {
        throw "Virtual environment not found at $Root\.venv. Create it and install requirements-dev.lock first."
    }
    # 1. Generate multi-resolution app icon if missing
    Invoke-Checked $Python @("scripts\make_assets.py")

    $common = @(
        "--noconfirm", "--clean", "--windowed",
        "--icon", "assets\drivesweep.ico",
        "--version-file", "version_info.txt",
        "--add-data", "app\ui;app\ui",
        "--add-data", "assets;assets"
    )

    # 2. Portable single-file executable: dist\DriveSweep.exe
    Invoke-Checked $PyInstaller ($common + @("--onefile", "--name", "DriveSweep", "main.py"))

    # 3. Folder bundle (better AV reputation and installer input): dist\DriveSweep-win64\
    Invoke-Checked $PyInstaller ($common + @("--onedir", "--name", "DriveSweep-win64", "main.py"))

    # PyInstaller names the inner exe after --name; rename to DriveSweep.exe inside DriveSweep-win64
    $innerExe = Join-Path $Dist "DriveSweep-win64\DriveSweep-win64.exe"
    $targetExe = Join-Path $Dist "DriveSweep-win64\DriveSweep.exe"
    if (Test-Path $innerExe) {
        if (Test-Path $targetExe) { Remove-Item $targetExe -Force }
        Rename-Item -Path $innerExe -NewName "DriveSweep.exe"
    }
    # Regenerate third party notices from the exact packages that were bundled
    Invoke-Checked $Python @("scripts\collect_licenses.py")
    foreach ($doc in @("LICENSE", "THIRD_PARTY_NOTICES.txt", "PRIVACY.md")) {
        $src = Join-Path $Root $doc
        if (Test-Path $src) {
            Copy-Item -Path $src -Destination (Join-Path $Dist "DriveSweep-win64\$doc") -Force
        }
    }
}

function Build-Package {
    # 4. Distributable .zip of the folder bundle (after its exe has been signed in CI)
    $zipPath = Join-Path $Dist "DriveSweep-win64.zip"
    if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
    Compress-Archive -Path (Join-Path $Dist "DriveSweep-win64\*") -DestinationPath $zipPath -CompressionLevel Optimal

    # 5. Compile the Inno Setup installer into dist\setup\ so CI can sign it on its own
    $iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
    if (-not $iscc -and (Test-Path "C:\Program Files (x86)\Inno Setup 6\ISCC.exe")) {
        $iscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    }
    if ($iscc) {
        if (Test-Path $SetupOut) { Remove-Item $SetupOut -Recurse -Force }
        New-Item -ItemType Directory -Path $SetupOut | Out-Null
        Invoke-Checked $iscc @("/O$SetupOut", (Join-Path $Root "installer\DriveSweep.iss"))
    } else {
        Write-Host "Inno Setup (ISCC.exe) not found; skipped Setup.exe (installer\DriveSweep.iss is ready when Inno Setup is installed)." -ForegroundColor Yellow
    }
}

function Write-Checksums {
    # 6. Publish the (signed) installer next to the other assets and write SHA256SUMS.txt
    Get-ChildItem (Join-Path $SetupOut "DriveSweep-Setup-*.exe") -ErrorAction SilentlyContinue | ForEach-Object {
        Copy-Item -Path $_.FullName -Destination (Join-Path $Dist $_.Name) -Force
    }
    $hashLines = @()
    $targets = @("DriveSweep.exe", "DriveSweep-win64.zip") + @(Get-ChildItem (Join-Path $Dist "DriveSweep-Setup-*.exe") -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
    foreach ($name in $targets) {
        $full = Join-Path $Dist $name
        if (Test-Path $full) {
            $h = (Get-FileHash -Path $full -Algorithm SHA256).Hash.ToLower()
            $hashLines += "$h  $name"
        }
    }
    Set-Content -Path (Join-Path $Dist "SHA256SUMS.txt") -Value $hashLines -Encoding UTF8
}

Push-Location $Root
try {
    if ($Stage -in @("All", "Binaries")) { Build-Binaries }
    if ($Stage -in @("All", "Package")) { Build-Package }
    if ($Stage -in @("All", "Checksums")) { Write-Checksums }

    Write-Host ""
    Write-Host "Stage '$Stage' complete. Artifacts in dist\:" -ForegroundColor Green
    Get-ChildItem $Dist -File | Select-Object Name, @{N="SizeMB";E={[math]::Round($_.Length/1MB,2)}} | Format-Table -AutoSize
} finally {
    Pop-Location
}
