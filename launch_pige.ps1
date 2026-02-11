# ============================================================================
# PIGE Launcher - PowerShell Script
# ============================================================================
# This script ensures Python is installed, creates a virtual environment,
# installs dependencies, and launches the PIGE GUI application.
# ============================================================================

param(
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$PassThruArgs
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"  # Faster downloads

# ============================================================================
# CONFIGURATION
# ============================================================================

$MIN_PYTHON_VERSION = [version]"3.11.0"
$PYTHON_DOWNLOAD_URL = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
$DOWNLOAD_TIMEOUT = 30  # seconds

# Paths
$PROJECT_ROOT = $PSScriptRoot

$PIGE_DATA_DIR = Join-Path $env:LOCALAPPDATA "PIGE"
$VENV_PATH = Join-Path $PIGE_DATA_DIR ".venv"
$VENV_PYTHON = Join-Path $VENV_PATH "Scripts\python.exe"
$DEPS_STAMP_FILE = Join-Path $PIGE_DATA_DIR "deps.sha256"
$LOCK_FILE = Join-Path $PIGE_DATA_DIR "launcher.lock"
$LOG_FILE = Join-Path $PIGE_DATA_DIR "launcher.log"

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

function Write-Log {
    param([string]$Message, [string]$Level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logMessage = "[$timestamp] [$Level] $Message"
    
    # Console output with color
    switch ($Level) {
        "ERROR" { Write-Host $logMessage -ForegroundColor Red }
        "WARN"  { Write-Host $logMessage -ForegroundColor Yellow }
        "SUCCESS" { Write-Host $logMessage -ForegroundColor Green }
        default { Write-Host $logMessage }
    }
    
    # File logging
    try {
        if (-not (Test-Path $PIGE_DATA_DIR)) {
            New-Item -ItemType Directory -Path $PIGE_DATA_DIR -Force | Out-Null
        }
        Add-Content -Path $LOG_FILE -Value $logMessage -ErrorAction SilentlyContinue
    } catch {
        # Ignore logging errors
    }
}

function Get-PythonExecutable {
    Write-Log "Detecting Python installation..."
    
    # Try py launcher first (recommended for Windows)
    try {
        $pyOutput = & py -3 --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $version = [regex]::Match($pyOutput, '\d+\.\d+\.\d+').Value
            if ($version -and ([version]$version -ge $MIN_PYTHON_VERSION)) {
                Write-Log "Found Python $version via 'py' launcher" "SUCCESS"
                return "py", "-3"
            }
        }
    } catch {
        Write-Log "py launcher not available or failed" "WARN"
    }
    
    # Try python command
    try {
        $pythonOutput = & python --version 2>&1
        if ($LASTEXITCODE -eq 0) {
            $version = [regex]::Match($pythonOutput, '\d+\.\d+\.\d+').Value
            if ($version -and ([version]$version -ge $MIN_PYTHON_VERSION)) {
                Write-Log "Found Python $version via 'python' command" "SUCCESS"
                return "python", $null
            } else {
                Write-Log "Python $version is too old (need >= $MIN_PYTHON_VERSION)" "WARN"
            }
        }
    } catch {
        Write-Log "python command not available" "WARN"
    }
    
    return $null, $null
}

function Install-PythonViaWinget {
    Write-Log "Attempting to install Python via winget..."
    
    # Check if winget is available
    try {
        $null = & winget --version 2>&1
        if ($LASTEXITCODE -ne 0) { throw }
    } catch {
        Write-Log "winget not available" "WARN"
        return $false
    }
    
    # Try with --silent first
    Write-Log "Installing Python 3.12 (this may take a few minutes)..."
    try {
        & winget install -e --id Python.Python.3.12 --source winget --scope user --accept-source-agreements --accept-package-agreements --silent 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Python installed successfully via winget" "SUCCESS"
            return $true
        }
    } catch {
        Write-Log "Silent install failed, retrying without --silent..." "WARN"
    }
    
    # Retry without --silent
    try {
        & winget install -e --id Python.Python.3.12 --source winget --scope user --accept-source-agreements --accept-package-agreements 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Log "Python installed successfully via winget" "SUCCESS"
            return $true
        }
    } catch {
        Write-Log "winget installation failed" "ERROR"
    }
    
    return $false
}

function Install-PythonDirect {
    Write-Log "Downloading Python installer from python.org..."
    
    $installerPath = Join-Path $env:TEMP "python_installer.exe"
    
    try {
        # Download with timeout
        $webClient = New-Object System.Net.WebClient
        $webClient.DownloadFile($PYTHON_DOWNLOAD_URL, $installerPath)
        
        if (-not (Test-Path $installerPath)) {
            throw "Download failed - file not found"
        }
        
        Write-Log "Installing Python (silent mode, no admin required)..."
        $installArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0"
        
        $process = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru -NoNewWindow
        
        if ($process.ExitCode -eq 0) {
            Write-Log "Python installed successfully" "SUCCESS"
            return $true
        } else {
            Write-Log "Python installer returned exit code: $($process.ExitCode)" "ERROR"
            return $false
        }
    } catch {
        Write-Log "Direct installation failed: $_" "ERROR"
        return $false
    } finally {
        # Cleanup
        if (Test-Path $installerPath) {
            Remove-Item $installerPath -Force -ErrorAction SilentlyContinue
        }
    }
}

function Ensure-Python {
    $pythonCmd, $pythonArg = Get-PythonExecutable
    
    if ($pythonCmd) {
        return $pythonCmd, $pythonArg
    }
    
    Write-Log "Python >= $MIN_PYTHON_VERSION not found. Installing..." "WARN"
    
    # Try winget first
    $wingetSuccess = Install-PythonViaWinget
    
    if (-not $wingetSuccess) {
        # Fallback to direct download
        $directSuccess = Install-PythonDirect
        
        if (-not $directSuccess) {
            Write-Log "Failed to install Python automatically" "ERROR"
            Write-Log "Please install Python manually from: https://www.python.org/downloads/" "ERROR"
            exit 1
        }
    }
    
    # Refresh PATH
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "User") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    
    # Re-check
    Start-Sleep -Seconds 2
    $pythonCmd, $pythonArg = Get-PythonExecutable
    
    if (-not $pythonCmd) {
        Write-Log "Python installation completed but python command still not available" "ERROR"
        Write-Log "Try restarting your terminal or computer" "ERROR"
        exit 1
    }
    
    return $pythonCmd, $pythonArg
}

function Ensure-VirtualEnvironment {
    param([string]$PythonCmd, [string]$PythonArg)
    
    if (Test-Path $VENV_PYTHON) {
        Write-Log "Virtual environment already exists at: $VENV_PATH"
        return
    }
    
    Write-Log "Creating virtual environment at: $VENV_PATH"
    
    # Create parent directory
    if (-not (Test-Path $PIGE_DATA_DIR)) {
        New-Item -ItemType Directory -Path $PIGE_DATA_DIR -Force | Out-Null
    }
    
    # Create venv
    $venvArgs = @()
    if ($PythonArg) { $venvArgs += $PythonArg }
    $venvArgs += @("-m", "venv", $VENV_PATH)
    
    $process = Start-Process -FilePath $PythonCmd -ArgumentList $venvArgs -Wait -PassThru -NoNewWindow
    
    if ($process.ExitCode -ne 0 -or -not (Test-Path $VENV_PYTHON)) {
        Write-Log "Failed to create virtual environment" "ERROR"
        exit 2
    }
    
    Write-Log "Virtual environment created successfully" "SUCCESS"
}

function Get-FileHash-SHA256 {
    param([string]$FilePath)
    
    if (-not (Test-Path $FilePath)) {
        return ""
    }
    
    $hash = Get-FileHash -Path $FilePath -Algorithm SHA256
    return $hash.Hash
}

function Get-DependenciesHash {
    $reqFile = Join-Path $PROJECT_ROOT "requirements.txt"
    $pyprojectFile = Join-Path $PROJECT_ROOT "pyproject.toml"
    
    $combinedHash = ""
    
    if (Test-Path $reqFile) {
        $combinedHash += Get-FileHash-SHA256 $reqFile
    }
    
    if (Test-Path $pyprojectFile) {
        $combinedHash += Get-FileHash-SHA256 $pyprojectFile
    }
    
    if ($combinedHash) {
        $hasher = [System.Security.Cryptography.SHA256]::Create()
        $hashBytes = $hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($combinedHash))
        return [System.BitConverter]::ToString($hashBytes).Replace("-", "").ToLower()
    }
    
    return ""
}

function Install-Dependencies {
    $currentHash = Get-DependenciesHash
    
    # Check if installation needed
    if (Test-Path $DEPS_STAMP_FILE) {
        $savedHash = Get-Content $DEPS_STAMP_FILE -Raw -ErrorAction SilentlyContinue
        if ($savedHash -eq $currentHash) {
            Write-Log "Dependencies are up to date (hash match)"
            return
        } else {
            Write-Log "Dependencies changed - reinstalling..." "WARN"
        }
    } else {
        Write-Log "First run - installing dependencies..."
    }
    
    # Upgrade pip, setuptools, wheel
    Write-Log "Upgrading pip, setuptools, wheel..."
    & $VENV_PYTHON -m pip install --upgrade pip setuptools wheel --quiet
    
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to upgrade pip/setuptools/wheel" "ERROR"
        exit 2
    }
    
    # Install requirements.txt if exists
    $reqFile = Join-Path $PROJECT_ROOT "requirements.txt"
    if (Test-Path $reqFile) {
        Write-Log "Installing requirements from requirements.txt..."
        & $VENV_PYTHON -m pip install -r $reqFile --quiet
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "Failed to install requirements" "ERROR"
            exit 2
        }
    }
    
    # Install project in editable mode
    Write-Log "Installing PIGE project in editable mode..."
    & $VENV_PYTHON -m pip install -e $PROJECT_ROOT --quiet
    
    if ($LASTEXITCODE -ne 0) {
        Write-Log "Failed to install PIGE project" "ERROR"
        exit 2
    }
    
    # Save hash
    $currentHash | Set-Content -Path $DEPS_STAMP_FILE -NoNewline
    Write-Log "Dependencies installed successfully" "SUCCESS"
}

function Acquire-Lock {
    $maxWait = 30  # seconds
    $waited = 0
    
    while ((Test-Path $LOCK_FILE) -and ($waited -lt $maxWait)) {
        Write-Log "Another instance is running, waiting..." "WARN"
        Start-Sleep -Seconds 2
        $waited += 2
    }
    
    if (Test-Path $LOCK_FILE) {
        Write-Log "Could not acquire lock after ${maxWait}s - aborting" "ERROR"
        exit 3
    }
    
    # Create lock
    "locked" | Set-Content -Path $LOCK_FILE -NoNewline
}

function Release-Lock {
    if (Test-Path $LOCK_FILE) {
        Remove-Item $LOCK_FILE -Force -ErrorAction SilentlyContinue
    }
}

function Launch-PIGE {
    Write-Log "Launching PIGE GUI..."
    
    # Change to project root
    Push-Location $PROJECT_ROOT
    
    try {
        # Build arguments
        $launchArgs = @("-m", "pige", "gui")
        if ($PassThruArgs) {
            $launchArgs += $PassThruArgs
        }
        
        # Launch (blocking)
        & $VENV_PYTHON @launchArgs
        
        if ($LASTEXITCODE -ne 0) {
            Write-Log "PIGE GUI exited with code: $LASTEXITCODE" "WARN"
        }
    } catch {
        Write-Log "Failed to launch PIGE: $_" "ERROR"
        exit 3
    } finally {
        Pop-Location
    }
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================

try {
    Write-Log "========================================" 
    Write-Log "PIGE Launcher Starting"
    Write-Log "========================================"
    Write-Log "Project Root: $PROJECT_ROOT"
    Write-Log "Data Directory: $PIGE_DATA_DIR"
    
    # Acquire lock
    Acquire-Lock
    
    # Ensure Python is installed
    $pythonCmd, $pythonArg = Ensure-Python
    
    # Ensure virtual environment exists
    Ensure-VirtualEnvironment -PythonCmd $pythonCmd -PythonArg $pythonArg
    
    # Install/update dependencies if needed
    Install-Dependencies
    
    # Release lock before launching
    Release-Lock
    
    # Launch the application
    Launch-PIGE
    
    Write-Log "PIGE Launcher finished successfully" "SUCCESS"
    exit 0
    
} catch {
    Write-Log "Unexpected error: $_" "ERROR"
    Write-Log $_.ScriptStackTrace "ERROR"
    exit 99
} finally {
    Release-Lock
}