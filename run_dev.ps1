# Champions Club - Development Server Runner
Write-Host "Starting PostgreSQL cluster on port 5433..." -ForegroundColor Cyan

if (Test-Path ".pgdata\postmaster.pid") {
    $conn = Get-NetTCPConnection -LocalPort 5433 -ErrorAction SilentlyContinue
    if (-not $conn) {
        Remove-Item ".pgdata\postmaster.pid" -Force -ErrorAction SilentlyContinue
    }
}

$pgConn = Get-NetTCPConnection -LocalPort 5433 -ErrorAction SilentlyContinue
if (-not $pgConn) {
    Start-Process -FilePath "C:\Program Files\PostgreSQL\17\bin\postgres.exe" -ArgumentList "-D", ".\.pgdata", "-p", "5433" -WindowStyle Hidden
    Start-Sleep -Seconds 2
}

$djangoConn = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue
if ($djangoConn) {
    Write-Host "Django Development Server is ALREADY RUNNING and active on http://127.0.0.1:8000/" -ForegroundColor Green
    Write-Host "PostgreSQL 17 is active on port 5433." -ForegroundColor Cyan
    Write-Host "Live Court Matrix: http://127.0.0.1:8000/club/availability/" -ForegroundColor Yellow
    Write-Host "Dashboard:         http://127.0.0.1:8000/" -ForegroundColor Yellow
} else {
    Write-Host "Starting Django Development Server at http://127.0.0.1:8000/ ..." -ForegroundColor Green
    & ".\.venv\Scripts\python.exe" manage.py runserver 127.0.0.1:8000
}
