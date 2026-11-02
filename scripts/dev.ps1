# Локальный запуск без Docker: открывает API, сайт и админку в отдельных окнах PowerShell.
# Перед первым запуском выполните шаги из docs/run-windows.md (база, .env, venv, npm install, создание владельца).
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root "services\api"

if (-not (Test-Path (Join-Path $api ".venv\Scripts\python.exe"))) {
    Write-Host "Не найдено виртуальное окружение services\api\.venv — см. docs\run-windows.md" -ForegroundColor Red
    exit 1
}
if (-not (Test-Path (Join-Path $api ".env"))) {
    Write-Host "Не найден services\api\.env — скопируйте services\api\.env.example и укажите DATABASE_URL" -ForegroundColor Red
    exit 1
}

Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$api'; .\.venv\Scripts\python.exe -m alembic upgrade head; .\.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; npm run dev:client"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; npm run dev:admin"

Write-Host "API:      http://localhost:8000/api/docs"
Write-Host "Сайт:     http://localhost:3000"
Write-Host "Админка:  http://localhost:3001"
