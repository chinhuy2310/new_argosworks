<#
.SYNOPSIS
    Install ARGOS WORKS as a Windows service (auto-start, crash restart).

.DESCRIPTION
    Two supported modes:
      1) NSSM (recommended) — true Windows service, survives logoff/reboot.
      2) Scheduled Task fallback — no extra download required, starts at boot
         under a service account with "restart on failure" semantics.

.PARAMETER Mode
    nssm | task   (default: task)

.PARAMETER InstallDir
    Where the release bundle lives (default: C:\ArgosWorks)

.PARAMETER Port
    Listening port (default: 8080)

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File deploy\install_windows_service.ps1 -Mode task -InstallDir C:\ArgosWorks
#>
param(
    [ValidateSet("nssm", "task")]
    [string]$Mode = "task",
    [string]$InstallDir = "C:\ArgosWorks",
    [int]$Port = 8080,
    [string]$ServiceName = "ArgosWorks"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $InstallDir)) {
    throw "InstallDir not found: $InstallDir"
}

$python = Join-Path $InstallDir ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    $python = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
}
if (-not $python) {
    throw "python.exe not found. Create the virtualenv first: python -m venv .venv"
}

$wsgiArgs = "-m waitress --listen=0.0.0.0:$Port server.wsgi:application"

if ($Mode -eq "nssm") {
    $nssm = (Get-Command nssm.exe -ErrorAction SilentlyContinue).Source
    if (-not $nssm) {
        throw "nssm.exe not found in PATH. Download NSSM, or run with -Mode task."
    }
    & $nssm install $ServiceName $python $wsgiArgs
    & $nssm set $ServiceName AppDirectory $InstallDir
    & $nssm set $ServiceName AppStdout (Join-Path $InstallDir "logs\service.out.log")
    & $nssm set $ServiceName AppStderr (Join-Path $InstallDir "logs\service.err.log")
    & $nssm set $ServiceName Start SERVICE_AUTO_START
    & $nssm set $ServiceName AppExit Default Restart
    & $nssm set $ServiceName AppRestartDelay 5000
    Write-Host "[OK] Installed Windows service '$ServiceName' via NSSM."
    Write-Host "     Start with: Start-Service $ServiceName"
    exit 0
}

# ---- Scheduled task fallback (no extra binaries) ---------------------------
$action = New-ScheduledTaskAction -Execute $python -Argument $wsgiArgs -WorkingDirectory $InstallDir
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest

Register-ScheduledTask -TaskName $ServiceName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Start-ScheduledTask -TaskName $ServiceName

Write-Host "[OK] Registered scheduled task '$ServiceName' (runs at boot as SYSTEM, restarts on failure)."
Write-Host "     Status: Get-ScheduledTask -TaskName $ServiceName | Get-ScheduledTaskInfo"
Write-Host "     Health: Invoke-WebRequest http://localhost:$Port/api/health"
