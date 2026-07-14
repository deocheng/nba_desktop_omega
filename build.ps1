# NBACore Studio v8 — Build Executable
# Usage: .\build.ps1
# Output: dist\NBACore.exe

param([switch]$Clean)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  NBACore Studio v8 — Build EXE" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check PyInstaller
try {
    $pyinstaller = Get-Command pyinstaller -ErrorAction Stop
    Write-Host "[OK] PyInstaller found: $($pyinstaller.Source)" -ForegroundColor Green
} catch {
    Write-Host "[INSTALL] PyInstaller not found, installing..." -ForegroundColor Yellow
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[ERROR] Failed to install PyInstaller" -ForegroundColor Red
        exit 1
    }
}

# Clean build artifacts
if ($Clean) {
    Write-Host "[CLEAN] Removing build/ and dist/..." -ForegroundColor Yellow
    if (Test-Path build) { Remove-Item -Recurse -Force build }
    if (Test-Path dist) { Remove-Item -Recurse -Force dist }
}

# Build
Write-Host ""
Write-Host "[BUILD] Running PyInstaller..." -ForegroundColor Cyan
pyinstaller --clean nbacore.spec

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "[ERROR] Build failed!" -ForegroundColor Red
    exit 1
}

# Verify output
$exePath = Join-Path $ProjectRoot "dist\NBACore.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  BUILD SUCCESS!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  Output: $exePath" -ForegroundColor White
    Write-Host "  Size:   $sizeMB MB" -ForegroundColor White
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Note: Requires PostgreSQL running on" -ForegroundColor Yellow
    Write-Host "        localhost:5433 (database: nba)" -ForegroundColor Yellow
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[ERROR] EXE not found at $exePath" -ForegroundColor Red
    exit 1
}
