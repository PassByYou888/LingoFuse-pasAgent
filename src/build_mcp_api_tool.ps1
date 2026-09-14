# =============================================================================
# build_mcp_api_tool.ps1
# -----------------------------------------------------------------------------
# Use PyInstaller to compile two Python scripts into standalone Windows
# executables:
#
#   1. mcp_api_tool.py   ->  mcp_api_tool.exe
#        MCP gateway that bridges an MCP client (LM Studio, Claude Desktop,
#        Continue.dev, Jan, ...) to a LingoFuse backend tool provider.
#        Uses FastMCP and language_middleware, and bundles the local
#        `lingofuse` Python package as data.
#
#   2. mcp_api_proxy.py  ->  mcp_api_proxy.exe
#        Transparent stdio debug forwarder. Sits between the MCP client
#        and mcp_api_tool.exe (or mcp_api_tool.py) and logs every byte
#        exchanged to proxy.log and to stderr.
#
# Prerequisites:
#   - Python 3.8+ (3.10 ~ 3.12 recommended)
#   - PyInstaller installed: pip install pyinstaller
#   - Runtime dependencies installed (fastmcp, pydantic, tzdata, ...)
#   - The local `lingofuse` package must be present next to mcp_api_tool.py
#
# Usage (run from the src directory that contains the .py files):
#   powershell -ExecutionPolicy Bypass -File .\build_mcp_api_tool.ps1
#
# Optional parameters:
#   -SourceDir <path>   Directory containing the two .py source files and
#                       the `lingofuse` package. Default: the directory of
#                       this script.
#   -OutputDir <path>   Directory for the produced EXEs.
#                       Default: <SourceDir>\dist
#   -BuildDir  <path>   PyInstaller work directory (also receives the
#                       generated .spec files).
#                       Default: <SourceDir>\build
#   -SkipTool           Skip building mcp_api_tool.exe
#   -SkipProxy          Skip building mcp_api_proxy.exe
#
# Output (default):
#   .\dist\mcp_api_tool.exe
#   .\dist\mcp_api_proxy.exe
#
# =============================================================================

[CmdletBinding()]
param(
    [string]$SourceDir,
    [string]$OutputDir,
    [string]$BuildDir,
    [switch]$SkipTool,
    [switch]$SkipProxy
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Resolve directories
# ---------------------------------------------------------------------------
if (-not $SourceDir -or $SourceDir.Trim() -eq "") {
    if ($PSScriptRoot -and $PSScriptRoot.Trim() -ne "") {
        $SourceDir = $PSScriptRoot
    } else {
        $SourceDir = (Get-Location).Path
    }
}
$SourceDir = (Resolve-Path -LiteralPath $SourceDir).Path

if (-not $OutputDir -or $OutputDir.Trim() -eq "") {
    $OutputDir = Join-Path $SourceDir "dist"
}
if (-not $BuildDir -or $BuildDir.Trim() -eq "") {
    $BuildDir = Join-Path $SourceDir "build"
}

# ---------------------------------------------------------------------------
# Source file paths
# ---------------------------------------------------------------------------
$ToolScript  = Join-Path $SourceDir "mcp_api_tool.py"
$ProxyScript = Join-Path $SourceDir "mcp_api_proxy.py"

# The `lingofuse` package must exist next to mcp_api_tool.py so that
# `--add-data` can bundle it into the executable.
$LingoFusePkgDir = Join-Path $SourceDir "lingofuse"

# Spec file names. They are written into $BuildDir (see --specpath below).
$SpecFiles = @(
    "mcp_api_tool.spec",
    "mcp_api_proxy.spec"
)

# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------
Write-Host ""
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " LingoFuse MCP API Tool Build Script" -ForegroundColor Cyan
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host "  Source directory : $SourceDir" -ForegroundColor Gray
Write-Host "  Output directory : $OutputDir" -ForegroundColor Gray
Write-Host "  Build  directory : $BuildDir" -ForegroundColor Gray
Write-Host ""

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
Write-Host "[Check] PyInstaller ..." -ForegroundColor Yellow
try {
    $pyiVersion = (pyinstaller --version) 2>&1
    Write-Host "  PyInstaller version: $pyiVersion" -ForegroundColor Green
} catch {
    Write-Host "  [ERROR] PyInstaller is not installed. Please run:" -ForegroundColor Red
    Write-Host "          pip install pyinstaller" -ForegroundColor Red
    exit 1
}

Write-Host "[Check] Python ..." -ForegroundColor Yellow
try {
    $pyVersion = (python --version) 2>&1
    Write-Host "  $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] 'python' command not found on PATH." -ForegroundColor Yellow
    Write-Host "         The build may still succeed if PyInstaller is on PATH." -ForegroundColor Yellow
}

Write-Host "[Check] Source files ..." -ForegroundColor Yellow
$required = @()
if (-not $SkipTool)  { $required += $ToolScript }
if (-not $SkipProxy) { $required += $ProxyScript }

if ($required.Count -eq 0) {
    Write-Host "  [ERROR] All build targets were skipped. Nothing to do." -ForegroundColor Red
    exit 1
}

foreach ($f in $required) {
    if (-not (Test-Path -LiteralPath $f)) {
        Write-Host "  [ERROR] Source file not found: $f" -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] $f" -ForegroundColor Green
}

# `mcp_api_tool.py` bundles the `lingofuse` package as data, so the
# package directory must be present. Skip the check when the tool build
# is disabled.
if (-not $SkipTool) {
    if (-not (Test-Path -LiteralPath $LingoFusePkgDir)) {
        Write-Host "  [ERROR] Required package directory not found:" -ForegroundColor Red
        Write-Host "          $LingoFusePkgDir" -ForegroundColor Red
        Write-Host "          The 'lingofuse' package must be next to mcp_api_tool.py." -ForegroundColor Red
        exit 1
    }
    Write-Host "  [OK] $LingoFusePkgDir" -ForegroundColor Green
}

Write-Host ""

# ---------------------------------------------------------------------------
# Clean old build artifacts
# ---------------------------------------------------------------------------
if (Test-Path -LiteralPath $BuildDir) {
    Write-Host "[Clean] Removing old build directory ..." -ForegroundColor Yellow
    Remove-Item -LiteralPath $BuildDir -Recurse -Force
}

# Also remove any stale .spec files that may have been written into the
# current working directory by a previous run of this script.
foreach ($spec in $SpecFiles) {
    if (Test-Path -LiteralPath $spec) {
        Remove-Item -LiteralPath $spec -Force
        Write-Host "[Clean] Removed $spec" -ForegroundColor Yellow
    }
}

Write-Host ""

# ---------------------------------------------------------------------------
# Helper: run one PyInstaller invocation and fail fast on error
# ---------------------------------------------------------------------------
function Invoke-PyInstaller {
    param(
        [Parameter(Mandatory = $true)]
        [string] $Label,

        [Parameter(Mandatory = $true)]
        [string[]] $Arguments
    )

    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host " $Label" -ForegroundColor Cyan
    Write-Host "===========================================================" -ForegroundColor Cyan
    Write-Host ""

    & pyinstaller @Arguments

    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "[ERROR] $Label failed (exit code $LASTEXITCODE)." -ForegroundColor Red
        exit $LASTEXITCODE
    }

    Write-Host ""
    Write-Host "[OK] $Label complete" -ForegroundColor Green
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Common PyInstaller flags
#
# --distpath / --workpath / --specpath keep all build products inside the
# resolved directories, so the caller's current working directory is not
# polluted. This makes the script safe to invoke from arbitrary locations
# (for example, a CI job).
# ---------------------------------------------------------------------------
$CommonFlags = @(
    "--noconfirm",
    "--clean",
    "--distpath", $OutputDir,
    "--workpath", $BuildDir,
    "--specpath", $BuildDir
)

# ---------------------------------------------------------------------------
# 1. Build mcp_api_tool.exe
#
#    - fastmcp, pydantic and tzdata are collected in full: they ship
#      metadata and data files that PyInstaller's static analysis would
#      otherwise drop.
#    - language_middleware is imported under a try/except guard in the
#      source, so PyInstaller cannot see it statically. It is declared
#      as a hidden import explicitly.
#    - generate_agent_json is also imported under a try/except guard and
#      is required for `--generate-configs`. Declared as a hidden import.
#    - The local `lingofuse` package is copied in as data so that the
#      native-ABI ctypes module and the pure-Python wrappers are both
#      available at runtime.
# ---------------------------------------------------------------------------
if (-not $SkipTool) {
    $toolArgs = @(
        "--onefile",
        "--name", "mcp_api_tool",
        "--paths", $SourceDir,
        "--collect-all", "fastmcp",
        "--collect-all", "pydantic",
        "--collect-all", "tzdata",
        "--hidden-import", "language_middleware",
        "--hidden-import", "generate_agent_json",
        "--add-data", "$LingoFusePkgDir;lingofuse"
    ) + $CommonFlags + @($ToolScript)

    Invoke-PyInstaller -Label "[1/2] Building mcp_api_tool.exe" -Arguments $toolArgs
} else {
    Write-Host "[Skip] mcp_api_tool.exe (disabled by -SkipTool)" -ForegroundColor DarkGray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# 2. Build mcp_api_proxy.exe
#
#    A tiny stdio forwarder with no third-party dependencies. It only
#    uses the Python standard library, so no --collect-all or --paths
#    flags are required.
# ---------------------------------------------------------------------------
if (-not $SkipProxy) {
    $proxyArgs = @(
        "--onefile",
        "--name", "mcp_api_proxy"
    ) + $CommonFlags + @($ProxyScript)

    Invoke-PyInstaller -Label "[2/2] Building mcp_api_proxy.exe" -Arguments $proxyArgs
} else {
    Write-Host "[Skip] mcp_api_proxy.exe (disabled by -SkipProxy)" -ForegroundColor DarkGray
    Write-Host ""
}

# ---------------------------------------------------------------------------
# Build result summary
# ---------------------------------------------------------------------------
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host " Build complete" -ForegroundColor Green
Write-Host "===========================================================" -ForegroundColor Cyan
Write-Host ""

$expected = @()
if (-not $SkipTool)  { $expected += "mcp_api_tool.exe" }
if (-not $SkipProxy) { $expected += "mcp_api_proxy.exe" }

$missing = 0
foreach ($name in $expected) {
    $path = Join-Path $OutputDir $name
    if (Test-Path -LiteralPath $path) {
        $sizeMB = [math]::Round((Get-Item -LiteralPath $path).Length / 1MB, 2)
        Write-Host ("  [OK] {0,-24} ({1} MB)" -f $name, $sizeMB) -ForegroundColor Green
    } else {
        Write-Host ("  [MISSING] {0}" -f $name) -ForegroundColor Red
        $missing++
    }
}

Write-Host ""
Write-Host "Output directory: $OutputDir" -ForegroundColor Yellow
Write-Host ""

if ($missing -gt 0) {
    Write-Host "One or more expected executables were not produced." -ForegroundColor Red
    exit 1
}

Write-Host "Runtime requirements (must be present on PATH or next to the EXEs):" -ForegroundColor Yellow
Write-Host "  - LingoFuse64.dll        LingoFuse core dynamic library" -ForegroundColor Gray
Write-Host "  - z_ipc_64.dll           IPC engine dependency" -ForegroundColor Gray
Write-Host "  - VC++ Redistributable   Visual Studio 2022 runtime" -ForegroundColor Gray
Write-Host ""

Write-Host "mcp_api_tool.exe additionally requires:" -ForegroundColor Yellow
Write-Host "  - A running tool provider on the LingoFuse network:" -ForegroundColor Gray
Write-Host "        pascal_agent_service.exe  (beacon, ipc:agent)" -ForegroundColor Gray
Write-Host "        pascal_agent_api.exe      (tool provider)" -ForegroundColor Gray
Write-Host "  - Or run with --generate-configs to emit client config files" -ForegroundColor Gray
Write-Host "    without connecting to a backend." -ForegroundColor Gray
Write-Host ""

Write-Host "mcp_api_proxy.exe additionally requires:" -ForegroundColor Yellow
Write-Host "  - A child command to launch and forward to, e.g.:" -ForegroundColor Gray
Write-Host "        mcp_api_proxy.exe mcp_api_tool.exe --transport stdio" -ForegroundColor Gray
Write-Host "  - All exchanged bytes are written to proxy.log next to the EXE." -ForegroundColor Gray
Write-Host ""

Write-Host "Done." -ForegroundColor Green
Write-Host ""