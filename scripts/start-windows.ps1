#requires -Version 5.1
[CmdletBinding()]
param([switch]$Stop)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

function Invoke-Compose {
    param([string[]]$Arguments)
    & docker compose --env-file (Join-Path $ProjectRoot '.env') -f (Join-Path $ProjectRoot 'docker-compose.yml') @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose завершился с ошибкой ($LASTEXITCODE)." }
}

function Wait-LocalPage {
    param([string]$Url, [int]$TimeoutSeconds = 180)
    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $Response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5
            if ($Response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $Deadline)
    throw "Не дождался ответа $Url. Проверьте состояние контейнеров: docker compose ps"
}

try {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Сначала установите и откройте Docker Desktop: https://docs.docker.com/desktop/setup/install/windows-install/'
    }
    $DockerEndpoint = & docker context inspect --format '{{json .Endpoints.docker.Host}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось определить контекст Docker. Откройте Docker Desktop.' }
    $DockerEndpoint = ($DockerEndpoint | Out-String).Trim() | ConvertFrom-Json
    if ($DockerEndpoint -notmatch '^(npipe:////\./pipe/|unix:///)') {
        throw 'Выбран удалённый Docker. Переключите Docker Desktop на локальный контекст desktop-linux.'
    }
    $DockerOs = & docker info --format '{{.OSType}}' 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Docker ещё не запущен. Откройте Docker Desktop, дождитесь запуска и повторите.' }
    if (($DockerOs | Out-String).Trim() -ne 'linux') {
        throw 'Docker должен работать в режиме Linux containers (WSL 2).'
    }
    & docker compose version
    if ($LASTEXITCODE -ne 0) { throw 'Нужен Docker Compose v2 из Docker Desktop.' }

    $EnvironmentFile = Join-Path $ProjectRoot '.env'
    if ($Stop) {
        if (-not (Test-Path -LiteralPath $EnvironmentFile)) { throw 'Приложение ещё не настроено: файл .env отсутствует.' }
        Invoke-Compose -Arguments @('stop')
        Write-Host 'Приложение остановлено. Клиенты, договоры, файлы и резервные копии сохранены.'
        exit 0
    }
    if (-not (Test-Path -LiteralPath $EnvironmentFile)) {
        $Random = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $Bytes = New-Object byte[] 32
            $Random.GetBytes($Bytes)
            $DatabasePassword = [BitConverter]::ToString($Bytes).Replace('-', '').ToLowerInvariant()
        } finally { $Random.Dispose() }
        $Settings = @(
            "POSTGRES_PASSWORD=$DatabasePassword", 'COMPOSE_PROJECT_NAME=islam-car',
            'ENVIRONMENT=development', 'COOKIE_SECURE=false',
            'ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001',
            'CLIENT_PUBLIC_URL=http://localhost:3000', 'PUBLIC_CLIENT_URL=http://localhost:3000',
            'RUN_MIGRATIONS=true', 'SMS_PROVIDER=', 'EMAIL_PROVIDER=', 'PAYMENT_PROVIDER=',
            'BACKUP_RETENTION_DAYS=30'
        )
        [IO.File]::WriteAllLines($EnvironmentFile, $Settings, (New-Object Text.UTF8Encoding($false)))
        $DatabasePassword = $null
        Write-Host 'Создана локальная конфигурация со случайным паролем базы.'
    } else {
        $SettingsText = [IO.File]::ReadAllText($EnvironmentFile)
        if ($SettingsText -match '(?m)^\s*ENVIRONMENT\s*=\s*["'']?production') {
            throw 'Этот запуск предназначен для локальной разработки. В .env указан production: используйте отдельную локальную копию.'
        }
        if ($SettingsText -match '(?m)^\s*POSTGRES_PASSWORD\s*=\s*(?:["'']?change-me|["'']?\s*$)') {
            throw 'В существующем .env не задан собственный POSTGRES_PASSWORD. Настройте его перед первым запуском; пароль существующей базы не меняйте без подготовки.'
        }
        Write-Host 'Использую существующую .env. Настройки и данные сохраняются.'
    }

    Write-Host 'Запускаю базу, сервер, обработчик, сайт и админку. Первая сборка может занять несколько минут.'
    Invoke-Compose -Arguments @('up', '-d', '--build')
    Wait-LocalPage -Url 'http://localhost:8000/api/health'
    Wait-LocalPage -Url 'http://localhost:3001/login'
    Wait-LocalPage -Url 'http://localhost:3000/login'

    $OwnerCheck = 'from sqlalchemy import select; from app.db import SessionLocal; from app.models import User, Role; db=SessionLocal(); print(int(db.scalar(select(User.id).where(User.role == Role.owner, User.is_active.is_(True))) is not None)); db.close()'
    $HasOwner = & docker compose --env-file $EnvironmentFile -f (Join-Path $ProjectRoot 'docker-compose.yml') exec -T api python -c $OwnerCheck
    if ($LASTEXITCODE -ne 0) { throw 'Не удалось проверить первую учётную запись. Смотрите docker compose logs api.' }
    if (($HasOwner | Out-String).Trim() -eq '0') {
        Write-Host 'Создаём владельца с полными правами администратора. Пароль вводится скрыто.'
        $OwnerLogin = Read-Host 'Логин администратора (например, ваш email)'
        $OwnerName = Read-Host 'Ваше имя'
        if ([string]::IsNullOrWhiteSpace($OwnerLogin) -or [string]::IsNullOrWhiteSpace($OwnerName)) {
            throw 'Логин и имя должны быть заполнены. Повторите запуск.'
        }
        Invoke-Compose -Arguments @('exec', 'api', 'python', '-m', 'scripts.create_owner', '--login', $OwnerLogin, '--name', $OwnerName)
    }

    Start-Process 'http://localhost:3001/login'
    Start-Process 'http://localhost:3000/'
    Write-Host ''
    Write-Host 'Администратор: http://localhost:3001/login'
    Write-Host 'Клиентский сайт: http://localhost:3000/'
    Write-Host 'Вход клиента: http://localhost:3000/login'
    Write-Host 'Владелец входит логином и паролем, заданными при первом запуске.'
    Write-Host 'Доступ клиента выдаётся в его карточке после проверки личности и подписания договора.'
    Write-Host 'Нажмите «Выдать доступ», откройте ссылку активации на localhost:3000 и задайте отдельный пароль клиента.'
    Write-Host 'Логин клиента — его телефон. До выдачи доступа можно смотреть каталог и подавать заявки.'
    Write-Host 'Тестовые машины, клиенты и фиктивные договоры автоматически не создаются.'
    Write-Host 'Для остановки используйте Stop-Islam-Car.cmd. Закрытие этого окна не останавливает приложение.'
} catch {
    Write-Host ''
    Write-Host ('Запуск не завершён: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host 'Выполните docker compose ps и docker compose logs --tail 40 api, чтобы увидеть причину.'
    exit 1
}
