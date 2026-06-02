# XJTLU RAG System - Start Script
$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  XJTLU RAG System Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check .env
Write-Host "[1/3] Checking config..." -ForegroundColor Yellow
if (-not (Test-Path ".env")) {
    Copy-Item .env.example .env
    Write-Host "  Please edit .env file first" -ForegroundColor Red
    exit 1
} else {
    Write-Host "  Config OK" -ForegroundColor Green
}

# Check database
Write-Host ""
Write-Host "[2/3] Checking database..." -ForegroundColor Yellow
if (-not (Test-Path "xjtlu_knowledge.db")) {
    Write-Host "  Warning: xjtlu_knowledge.db not found" -ForegroundColor Yellow
} else {
    Write-Host "  Database OK" -ForegroundColor Green
}

# Start service
Write-Host ""
Write-Host "[3/3] Starting service..." -ForegroundColor Yellow
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  FastAPI Service" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  URL:      http://127.0.0.1:8000" -ForegroundColor Green
Write-Host "  API Doc:  http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "Press Ctrl+C to stop" -ForegroundColor Yellow
Write-Host ""

python -m uvicorn app:app --host 0.0.0.0 --port 8000 --reload
