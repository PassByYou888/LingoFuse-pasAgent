# =============================================================================
# build_llm_service.ps1
# -----------------------------------------------------------------------------
# Use PyInstaller to compile three Python scripts into standalone Windows
# executables:
#
#   1. llm_service.py   ->  llm_service.exe
#        Local LLM inference service (llama.cpp backend)
#
#   2. llm_proxy.py     ->  llm_proxy.exe
#        OpenAI-compatible backend forwarder (LM Studio / Ollama / cloud APIs)
#
#   3. llm_test.py      ->  llm_test.exe
#        Interactive multi-session test client
#
# Prerequisites:
#   - Python 3.8+ (3.10 ~ 3.12 recommended)
#   - PyInstaller installed: pip install pyinstaller
#   - Runtime dependencies installed: pip install -r requirements.txt
#   - Source files located under .\llm-service\
#
# Usage (run from the project root or the src directory):
#   powershell -ExecutionPolicy Bypass -File .\build_llm_service.ps1
#
# Output:
#   .\dist\llm_service.exe
#   .\dist\llm_proxy.exe
#   .\dist\llm_test.exe
#
# =============================================================================

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Configuration: source directory, output directory, program names
# ---------------------------------------------------------------------------
$SourceDir   = ".\llm-service"
$OutputDir   = ".\dist"
$BuildDir    = ".\build"

$ServiceScript = Join-Path $SourceDir "llm_service.py"
$ProxyScript   = Join-Path $SourceDir "llm_proxy.py"
$TestScript    = Join-Path $SourceDir "llm_test.py"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " LingoFuse LLM Toolchain Build Script" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

# Check whether PyInstaller is installed
Write-Host "[Check] PyInstaller ..." -ForegroundColor Yellow
try {
    $pyiVersion = (pyinstaller --version) 2>&1
    Write-Host "  PyInstaller version: $pyiVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] PyInstaller is not installed. Please run:" -ForegroundColor Red
    Write-Host "          pip install pyinstaller" -ForegroundColor Red
    exit 1
}

# Check whether the three source files exist
Write-Host "[Check] Source files ..." -ForegroundColor Yellow
foreach ($f in @($ServiceScript, $ProxyScript, $TestScript)) {
    if (-not (Test-Path $f)) {
        Write-Host "  [ERROR] Source file not found: $f" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] $f" -ForegroundColor Green
}

Write-Host ""

# ---------------------------------------------------------------------------
# Clean old build artifacts (optional)
# ---------------------------------------------------------------------------
if (Test-Path $BuildDir) {
    Write-Host "[Clean] Removing old build directory ..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force $BuildDir
}
# Remove only the three .spec files that this run will generate
foreach ($spec in @("llm_service.spec", "llm_proxy.spec", "llm_test.spec")) {
    if (Test-Path $spec) {
        Remove-Item -Force $spec
        Write-Host "[Clean] Removed $spec" -ForegroundColor Yellow
    }
}

Write-Host ""

# ---------------------------------------------------------------------------
# 1. Build llm_service.exe
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " [1/3] Building llm_service.exe" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

pyinstaller --onefile `
    --name llm_service `
    --paths . `
    --paths $SourceDir `
    --collect-all llama_cpp `
    --collect-all lingofuse `
    --hidden-import llama_cpp `
    --hidden-import lingofuse `
    --hidden-import jinja2 `
    --noconfirm `
    $ServiceScript

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to build llm_service.exe" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "[OK] llm_service.exe build complete" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# 2. Build llm_proxy.exe
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " [2/3] Building llm_proxy.exe" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

pyinstaller --onefile `
    --name llm_proxy `
    --paths . `
    --paths $SourceDir `
    --collect-all lingofuse `
    --hidden-import lingofuse `
    --hidden-import requests `
    --hidden-import http.client `
    --hidden-import ssl `
    --noconfirm `
    $ProxyScript

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to build llm_proxy.exe" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "[OK] llm_proxy.exe build complete" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# 3. Build llm_test.exe
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " [3/3] Building llm_test.exe" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

pyinstaller --onefile `
    --name llm_test `
    --paths . `
    --paths $SourceDir `
    --collect-all lingofuse `
    --hidden-import lingofuse `
    --noconfirm `
    $TestScript

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Failed to build llm_test.exe" -ForegroundColor Red
    exit 1
}
Write-Host ""
Write-Host "[OK] llm_test.exe build complete" -ForegroundColor Green
Write-Host ""

# ---------------------------------------------------------------------------
# Build result summary
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " Build complete" -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

$produced = @()
foreach ($name in @("llm_service.exe", "llm_proxy.exe", "llm_test.exe")) {
    $path = Join-Path $OutputDir $name
    if (Test-Path $path) {
        $sizeMB = [math]::Round((Get-Item $path).Length / 1MB, 2)
        Write-Host ("  [OK] {0,-20} ({1} MB)" -f $name, $sizeMB) -ForegroundColor Green
        $produced += $path
    } else {
        Write-Host ("  [MISSING] {0}" -f $name) -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Output directory: $OutputDir" -ForegroundColor Yellow
Write-Host ""
Write-Host "Before running, ensure the following files are in the same" -ForegroundColor Yellow
Write-Host "directory as the EXEs or on the system PATH:" -ForegroundColor Yellow
Write-Host "  - LingoFuse64.dll        (LingoFuse core dynamic library)" -ForegroundColor Gray
Write-Host "  - z_ipc_64.dll           (IPC engine dependency)" -ForegroundColor Gray
Write-Host "  - VC++ Redistributable   (Visual Studio 2022 runtime)" -ForegroundColor Gray
Write-Host ""
Write-Host "llm_service.exe additionally requires:" -ForegroundColor Yellow
Write-Host "  - A GGUF model file (default: NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf)" -ForegroundColor Gray
Write-Host "  - Or specify a path via --model-path" -ForegroundColor Gray
Write-Host ""
Write-Host "llm_proxy.exe additionally requires:" -ForegroundColor Yellow
Write-Host "  - An OpenAI-compatible backend (LM Studio / Ollama / vLLM / cloud API)" -ForegroundColor Gray
Write-Host "  - Specify the backend address via --backend-url" -ForegroundColor Gray
Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host ""