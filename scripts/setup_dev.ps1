# Champions Club - Development Environment Setup for Windows PowerShell
# Usage: .\scripts\setup_dev.ps1

Write-Host "=== Setting up Champions Club Development Environment ===" -ForegroundColor Cyan

# 1. Check Python version
$pythonVersion = python --version 2>&1
Write-Host "Detected Python: $pythonVersion" -ForegroundColor Green

# 2. Setup Virtual Environment
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment in .venv..." -ForegroundColor Yellow
    python -m venv .venv
} else {
    Write-Host "Virtual environment .venv already exists." -ForegroundColor Green
}

# 3. Environment configuration file
if (-not (Test-Path ".env")) {
    Write-Host "Creating .env from .env.example..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    Write-Host ".env created with safe defaults." -ForegroundColor Green
} else {
    Write-Host ".env file already exists." -ForegroundColor Green
}

# 4. Activate virtual environment and install packages
Write-Host "Activating virtual environment and installing requirements..." -ForegroundColor Yellow
& ".\.venv\Scripts\Activate.ps1"
pip install -r requirements.txt

# 5. Database startup notice
Write-Host "`nTo start PostgreSQL container with Docker Compose:" -ForegroundColor Cyan
Write-Host "  docker compose up -d" -ForegroundColor White

Write-Host "`nTo run database migrations:" -ForegroundColor Cyan
Write-Host "  python manage.py migrate" -ForegroundColor White

Write-Host "`nTo launch development server:" -ForegroundColor Cyan
Write-Host "  python manage.py runserver" -ForegroundColor White

Write-Host "`n=== Setup instructions completed ===" -ForegroundColor Green
