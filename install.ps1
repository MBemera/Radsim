# RadSim Windows Installer (PowerShell)
# Usage: .\install.ps1 [-WithExtras <all|openai|browser|memory>]
#
# Requirements: Python 3.10 or higher

param(
    [string]$WithExtras = ""
)

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
                if ($major -ge 3 -and $minor -ge 10) {
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
Write-Info "Checking pip..."
try {
    & $pythonCmd -m pip --version 2>&1 | Out-Null
    Write-Success "pip available"
}
catch {
    Write-ErrorMessage "pip is not installed."
    Write-Host "Please install pip: https://pip.pypa.io/en/stable/installation/"
    exit 1
}

# Step 3: Verify we're in the radsim repo
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pyprojectPath = Join-Path $scriptDir "pyproject.toml"

if (-not (Test-Path $pyprojectPath)) {
    Write-ErrorMessage "Cannot find pyproject.toml. Run this from the radsim repo directory."
    exit 1
}

# Step 4: Install radsim using pip
Write-Info "Installing RadSim..."

$installTarget = $scriptDir
if ($WithExtras -and $WithExtras -ne "") {
    $installTarget = "$scriptDir[$WithExtras]"
    Write-Info "Including extras: $WithExtras"
}

& $pythonCmd -m pip install "$installTarget" --quiet 2>&1 | Out-Null

if ($LASTEXITCODE -ne 0) {
    Write-ErrorMessage "Installation failed"
    exit 1
}

Write-Success "RadSim installed"

# Step 5: Verify command and update PATH if needed
$pathNeedsUpdate = $false

$radsimPath = & $pythonCmd -c "import shutil; print(shutil.which('radsim') or '')" 2>$null
if ($radsimPath) {
    Write-Success "'radsim' command is available"
}
else {
    # Add Python Scripts directory to PATH
    $scriptsDir = Join-Path (Split-Path -Parent (& $pythonCmd -c "import sys; print(sys.executable)")) "Scripts"

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
Write-Host '     radsim "Create a Python function to validate emails"' -ForegroundColor Cyan
Write-Host ""
Write-Host "  On first run, RadSim will guide you through setup" -ForegroundColor Gray
Write-Host "  (provider selection, API key, preferences)." -ForegroundColor Gray
Write-Host ""
