#requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Tokens = $null
$ParseErrors = $null
[void][System.Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $PSScriptRoot 'start-windows.ps1'), [ref]$Tokens, [ref]$ParseErrors)
if ($ParseErrors.Count -gt 0) { throw ($ParseErrors | Out-String) }

$OriginalLocation = Get-Location
$Fixture = Join-Path ([IO.Path]::GetTempPath()) ('islamcar-launch-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $Fixture 'scripts') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'start-windows.ps1') (Join-Path $Fixture 'scripts/start-windows.ps1')
Copy-Item (Join-Path $RepositoryRoot 'docker-compose.yml') $Fixture
$global:IslamCarLauncherTestState = @{
    Opened = (New-Object 'System.Collections.Generic.List[string]')
    ComposeCalls = (New-Object 'System.Collections.Generic.List[string]')
    RemoteDocker = $false
}

# Stub external programs/browser; these checks do not install or start Docker.
function global:docker {
    $global:LASTEXITCODE = 0
    $Arguments = @($args)
    if ($Arguments[0] -eq 'context') {
        if ($global:IslamCarLauncherTestState.RemoteDocker) { '"ssh://example.invalid"' }
        else { '"npipe:////./pipe/dockerDesktopLinuxEngine"' }
    } elseif ($Arguments[0] -eq 'info') { 'linux' }
    elseif ($Arguments[0] -eq 'compose') {
        $global:IslamCarLauncherTestState.ComposeCalls.Add(($Arguments -join ' '))
        if ($Arguments -contains '-c') { '1' } # Owner already exists.
    } else { throw 'Unexpected Docker command' }
}
function global:Invoke-WebRequest {
    param($Uri, [switch]$UseBasicParsing, $TimeoutSec)
    if ($Uri -notmatch '^http://localhost:(8000|3000|3001)/') { throw 'Unexpected readiness URL' }
    [pscustomobject]@{ StatusCode = 200 }
}
function global:Start-Process {
    param([string]$FilePath)
    $global:IslamCarLauncherTestState.Opened.Add($FilePath)
}

try {
    $Launcher = Join-Path $Fixture 'scripts/start-windows.ps1'
    & $Launcher
    if ($LASTEXITCODE -ne 0) { throw 'First launch failed' }
    $EnvPath = Join-Path $Fixture '.env'
    $FirstSettings = [IO.File]::ReadAllText($EnvPath)
    if ($FirstSettings -notmatch '(?m)^POSTGRES_PASSWORD=[a-f0-9]{64}\r?$') { throw 'Missing random DB password' }
    if ($FirstSettings -notmatch '(?m)^PAYMENT_PROVIDER=\r?$') { throw 'External payments must stay off' }
    if ($global:IslamCarLauncherTestState.Opened.Count -ne 2) { throw 'Expected administrator and client browser windows' }
    if (-not $global:IslamCarLauncherTestState.Opened.Contains('http://localhost:3001/login')) { throw 'Missing admin URL' }
    if (-not $global:IslamCarLauncherTestState.Opened.Contains('http://localhost:3000/')) { throw 'Missing client URL' }
    & $Launcher
    if ([IO.File]::ReadAllText($EnvPath) -cne $FirstSettings) { throw 'Repeated launch changed configuration' }
    & $Launcher -Stop
    if (-not ($global:IslamCarLauncherTestState.ComposeCalls | Where-Object { $_ -match '\bstop$' })) { throw 'Stop did not stop services' }
    if ($global:IslamCarLauncherTestState.ComposeCalls | Where-Object { $_ -match '\bdown\b|\bprune\b|\bseed_demo\b' }) {
        throw 'Launcher must not remove data or seed invented business records'
    }
    $global:IslamCarLauncherTestState.RemoteDocker = $true
    $PreviousCalls = $global:IslamCarLauncherTestState.ComposeCalls.Count
    & $Launcher
    if ($LASTEXITCODE -ne 1 -or $global:IslamCarLauncherTestState.ComposeCalls.Count -ne $PreviousCalls) {
        throw 'Remote Docker context was not rejected before mutations'
    }
    Write-Host 'Windows PowerShell 5.1: syntax, first/repeated launch, URLs, safe stop and remote-context rejection passed.'
} finally {
    Set-Location $OriginalLocation
    Remove-Item -Recurse -Force $Fixture
    Remove-Item Function:\docker, Function:\Invoke-WebRequest, Function:\Start-Process
    Remove-Variable -Scope Global -Name IslamCarLauncherTestState
}

exit 0
