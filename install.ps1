# RadSim Windows Installer (PowerShell)
# Usage: .\install.ps1
#
# Requirements: Python 3.10 or higher

$ErrorActionPreference = "Stop"

function Write-Title {
    Write-Host ""
    Write-Host "  +-------------------------------------+" -ForegroundColor Cyan
    Write-Host "  |         RadSim Installer            |" -ForegroundColor Cyan
    Write-Host "  |   Radically Simple Code Generator   |" -ForegroundColor Cyan
    Write-Host "  +-------------------------------------+" -ForegroundColor Cyan
    Write-Host ""
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "[..] $Message" -ForegroundColor Yellow
}

function Write-ErrorMessage {
    param([string]$Message)
    Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-PythonVersion {
    $pythonCmd = $null

    foreach ($cmd in @("python", "python3", "py")) {
        try {
            $version = & $cmd --version 2>&1
            if ($version -match "Python (\d+)\.(\d+)\.(\d+)") {
                $major = [int]$Matches[1]
                $minor = [int]$Matches[2]
                if (($major -eq 3 -and $minor -ge 10) -or ($major -gt 3)) {
                    $pythonCmd = $cmd
                    break
                }
            }
        }
        catch {
            continue
        }
    }

    return $pythonCmd
}

function Get-PythonVersion {
    param([string]$PythonCmd)
    $version = & $PythonCmd --version 2>&1
    if ($version -match "Python (\d+\.\d+\.\d+)") {
        return $Matches[1]
    }
    return "unknown"
}

function Get-PipxArgs {
    param([string]$PythonCmd)
    # Prefer `python -m pipx`; it works right after a pip --user install
    # without depending on PATH being refreshed.
    $ErrorActionPreference = "Continue"
    & $PythonCmd -m pipx --version *> $null
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($code -eq 0) {
        return @("-m", "pipx")
    }
    return $null
}

function Install-Pipx {
    param([string]$PythonCmd)
    Write-Info "Installing pipx (recommended for isolated CLI installs)..."
    $ErrorActionPreference = "Continue"
    & $PythonCmd -m pip install --user --upgrade pipx --quiet *> $null
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    return ($code -eq 0)
}

# Main installation logic
Write-Title

# Step 1: Check Python version
Write-Info "Checking Python installation..."

$pythonCmd = Test-PythonVersion

if (-not $pythonCmd) {
    Write-ErrorMessage "Python 3.10 or higher is required but not found."
    Write-Host ""
    Write-Host "Please install Python from: https://www.python.org/downloads/"
    Write-Host "Make sure to check 'Add Python to PATH' during installation."
    Write-Host ""
    exit 1
}

$pythonVersion = Get-PythonVersion -PythonCmd $pythonCmd
Write-Success "Python $pythonVersion detected (using: $pythonCmd)"

# Step 2: Check pip
# Note: native stderr must not be redirected while ErrorActionPreference
# is "Stop" — Windows PowerShell 5.1 turns any stderr line (e.g. a pip
# upgrade notice) into a terminating error. Toggle to Continue and rely
# on exit codes instead.
Write-Info "Checking pip..."
$ErrorActionPreference = "Continue"
& $pythonCmd -m pip --version *> $null
$pipExitCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pipExitCode -ne 0) {
    Write-ErrorMessage "pip is not installed."
    Write-Host "Please install pip: https://pip.pypa.io/en/stable/installation/"
    exit 1
}
Write-Success "pip available"

# Step 3: Install RadSim, preferring an isolated pipx environment
$pipxArgs = Get-PipxArgs -PythonCmd $pythonCmd
if (-not $pipxArgs) {
    if (Install-Pipx -PythonCmd $pythonCmd) {
        $pipxArgs = Get-PipxArgs -PythonCmd $pythonCmd
    }
}

$installedWithPipx = $false
if ($pipxArgs) {
    Write-Info "Installing RadSim with pipx..."
    $ErrorActionPreference = "Continue"
    & $pythonCmd @pipxArgs install radsimcli
    $installExitCode = $LASTEXITCODE
    if ($installExitCode -ne 0) {
        # A non-zero result most often means RadSim is already installed.
        & $pythonCmd @pipxArgs upgrade radsimcli
        $installExitCode = $LASTEXITCODE
    }
    $ErrorActionPreference = "Stop"

    if ($installExitCode -eq 0) {
        $ErrorActionPreference = "Continue"
        & $pythonCmd @pipxArgs ensurepath *> $null
        $ErrorActionPreference = "Stop"
        $installedWithPipx = $true
        Write-Success "RadSim installed (pipx)"
    }
    else {
        Write-Info "pipx install failed; falling back to pip."
    }
}

if (-not $installedWithPipx) {
    Write-Info "Installing RadSim with pip..."
    $ErrorActionPreference = "Continue"
    $installOutput = & $pythonCmd -m pip install --user --upgrade radsimcli --quiet 2>&1
    $installExitCode = $LASTEXITCODE
    $ErrorActionPreference = "Stop"

    if ($installExitCode -ne 0) {
        Write-ErrorMessage "Installation failed:"
        $installOutput | ForEach-Object { Write-Host "  $_" }
        exit 1
    }
    Write-Success "RadSim installed"
}

# Step 5: Verify command and update PATH if needed
$pathNeedsUpdate = $false

$ErrorActionPreference = "Continue"
$radsimPath = & $pythonCmd -c "import shutil; print(shutil.which('radsim') or '')"
$ErrorActionPreference = "Stop"
if ($radsimPath) {
    Write-Success "'radsim' command is available"
}
elseif ($installedWithPipx) {
    # pipx ensurepath already added its bin dir to the user PATH.
    $pathNeedsUpdate = $true
    Write-Success "pipx configured PATH; restart your terminal to use 'radsim'"
}
else {
    # Per-user pip installs put radsim.exe in the USER scripts dir
    # (%APPDATA%\Python\PythonXY\Scripts), not <python>\Scripts —
    # prefer whichever actually contains radsim.exe.
    $userScripts = & $pythonCmd -c "import os, sysconfig; print(sysconfig.get_path('scripts', os.name + '_user'))"
    $sysScripts = & $pythonCmd -c "import sysconfig; print(sysconfig.get_path('scripts'))"
    $scriptsDir = $sysScripts
    if ($userScripts -and (Test-Path (Join-Path $userScripts "radsim.exe"))) {
        $scriptsDir = $userScripts
    }

    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$scriptsDir*") {
        $pathNeedsUpdate = $true
        $newPath = "$scriptsDir;$userPath"
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Success "Added $scriptsDir to user PATH"
    }
    else {
        Write-Success "PATH already configured"
    }
}

# Step 6: Done!
Write-Host ""
Write-Host "================================================" -ForegroundColor Green
Write-Host "  RadSim installed successfully!" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Green
Write-Host ""
Write-Host "To get started:" -ForegroundColor White
Write-Host ""

if ($pathNeedsUpdate) {
    Write-Host "  1. Restart your terminal" -ForegroundColor Yellow
    Write-Host ""
}

Write-Host "  Run RadSim:" -ForegroundColor White
Write-Host "     radsim" -ForegroundColor Cyan
Write-Host ""
Write-Host "  On first run, RadSim will guide you through setup" -ForegroundColor Gray
Write-Host "  (provider selection, API key, preferences)." -ForegroundColor Gray
Write-Host ""
