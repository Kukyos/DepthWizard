# DepthWizard - one command to run everything.
#
#   .\run.ps1            start the server and the viewer
#   .\run.ps1 -Setup     install dependencies (run this once)
#   .\run.ps1 -Test      unit tests and the eval harness, then exit
#   .\run.ps1 -Check     environment report only, installs nothing
#
# No Docker, no database, no services to configure. A teammate should be able to clone
# this repo and see it working in one step.

[CmdletBinding()]
param(
    [switch]$Setup,
    [switch]$Test,
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

function Say($message, $colour = "Cyan") { Write-Host "  $message" -ForegroundColor $colour }

Write-Host ""
Write-Host "  DepthWizard - single-view height estimation and 3D flythrough" -ForegroundColor White
Write-Host "  SIH 2026 - PS 26175 - ISRO / Department of Space" -ForegroundColor DarkGray
Write-Host ""

# --------------------------------------------------------------------- checks
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) { Say "Python is not on PATH. Install Python 3.11 or newer." "Red"; exit 1 }
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) { Say "Node is not on PATH. Install Node 20 or newer." "Red"; exit 1 }

# --------------------------------------------------------------------- setup
if ($Setup) {
    # torch first, and from PyTorch's own index. Installing it via requirements.txt pulls
    # the CPU-only build from PyPI, which is exactly the state this machine was found in:
    # an RTX 4060 present and torch.cuda.is_available() returning False. See D-01 in
    # docs/11-deferred.md.
    Say "Installing torch with CUDA 13 support (large download)..."
    python -m pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu130
    if ($LASTEXITCODE -ne 0) {
        Say "CUDA build failed. Falling back to the default index - CPU only." "Yellow"
        Say "The pipeline will work but every timing number will be meaningless." "Yellow"
        python -m pip install -q torch torchvision
    }

    Say "Installing Python packages..."
    python -m pip install -q -r "$root\server\requirements.txt"

    Say "Installing viewer packages..."
    Push-Location "$root\viewer"; npm install --silent; Pop-Location

    Write-Host ""
    Say "Environment report" "White"
    Push-Location "$root\server"; python -m tools.check_env; Pop-Location

    Write-Host ""
    Say "Setup complete." "Green"
    Say "GAMUS (~80 GB) is not downloaded by setup. See docs/07-build-plan.md Phase 0." "DarkGray"
    Write-Host ""
    exit 0
}

# --------------------------------------------------------------------- check
if ($Check) {
    Push-Location "$root\server"
    python -m tools.check_env
    $code = $LASTEXITCODE
    Pop-Location
    exit $code
}

# --------------------------------------------------------------------- tests
if ($Test) {
    Push-Location "$root\server"

    Say "Unit tests"
    python -m pytest tests -q
    $testsFailed = $LASTEXITCODE
    Write-Host ""

    # The harness is the authority on every number this project reports (hard rule 1).
    # It does not exist yet - Phase 1 builds it - so this stage reports that honestly
    # rather than passing silently and implying numbers exist.
    Say "Eval harness"
    if (Test-Path "$root\server\eval\run_eval.py") {
        python -m eval.run_eval
        $evalFailed = $LASTEXITCODE
    }
    else {
        Say "not built yet - Phase 1. No accuracy numbers exist." "DarkYellow"
        $evalFailed = 0
    }
    Pop-Location

    Write-Host ""
    Say "Viewer checks"
    if (Test-Path "$root\viewer\node_modules") {
        Push-Location "$root\viewer"
        npm run --silent check
        $viewerFailed = $LASTEXITCODE
        Pop-Location
    }
    else {
        Say "dependencies not installed - run .\run.ps1 -Setup" "DarkYellow"
        $viewerFailed = 0
    }

    Write-Host ""
    if ($testsFailed -ne 0 -or $evalFailed -ne 0 -or $viewerFailed -ne 0) {
        Say "FAILED" "Red"; exit 1
    }
    Say "All checks passed." "Green"
    exit 0
}

# --------------------------------------------------------------------- run
if (-not (Test-Path "$root\viewer\node_modules")) {
    Say "Dependencies are not installed. Run: .\run.ps1 -Setup" "Yellow"
    exit 1
}

if (-not (Test-Path "$root\.env")) {
    Say "No .env file. The core pipeline needs none - it runs fully offline." "DarkYellow"
    Say "Copy .env.example to .env to configure SRTM access and data paths." "DarkYellow"
    Write-Host ""
}

$jobs = @()

if (Test-Path "$root\server\depthwizard\api.py") {
    Say "Starting the server on http://localhost:8000"
    $jobs += Start-Process -PassThru -WindowStyle Minimized -WorkingDirectory "$root\server" `
        -FilePath "python" -ArgumentList "-m", "uvicorn", "depthwizard.api:app", "--port", "8000"
    Start-Sleep -Seconds 3
}
else {
    Say "Server not built yet - Phase 1. Starting the viewer alone." "DarkYellow"
}

Say "Starting the viewer on http://localhost:5173"
$jobs += Start-Process -PassThru -WindowStyle Minimized -WorkingDirectory "$root\viewer" `
    -FilePath "cmd" -ArgumentList "/c", "npm", "run", "dev"

Start-Sleep -Seconds 4
Write-Host ""
Say "Viewer          http://localhost:5173" "Green"
if (Test-Path "$root\server\depthwizard\api.py") {
    Say "Server health   http://localhost:8000/api/health" "Green"
}
Write-Host ""
Say "The viewer needs WebGL 2. Any current browser will do." "DarkGray"
Say "Press Ctrl+C to stop everything." "DarkGray"
Write-Host ""

Start-Process "http://localhost:5173"

try {
    while ($true) { Start-Sleep -Seconds 2 }
}
finally {
    Say "Stopping..." "DarkGray"
    foreach ($job in $jobs) {
        if ($job -and -not $job.HasExited) {
            Stop-Process -Id $job.Id -Force -ErrorAction SilentlyContinue
        }
    }
}
