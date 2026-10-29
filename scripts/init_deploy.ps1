# ==============================================================================
# ARGOS WORKS - first-run deployment bootstrap (Windows / PowerShell)
#
# Native fallback for machines without Python. Behaves like
# scripts/init_deploy.py:
#   1. Creates .env with generated ARGOS_MASTER_KEY / POSTGRES_PASSWORD,
#      replacing template placeholders.
#   2. Ensures server\config.json exists as a file (never a directory).
#   3. Creates the persistent data directories.
#
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File scripts\init_deploy.ps1
#        powershell -NoProfile -ExecutionPolicy Bypass -File scripts\init_deploy.ps1 -Rotate
# ==============================================================================
param([switch]$Rotate)

$ErrorActionPreference = 'Stop'

$Root         = Split-Path -Parent $PSScriptRoot
$EnvPath      = Join-Path $Root '.env'
$EnvExample   = Join-Path $Root '.env.example'
$ConfigPath   = Join-Path $Root 'server\config.json'
$ConfigSample = Join-Path $Root 'server\config.example.json'

$Placeholders = @(
    'YOUR_STRONG_PASSWORD_HERE',
    '0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'
)

function New-RandomHex([int]$Bytes) {
    $buffer = New-Object 'byte[]' $Bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

function New-RandomPassword([int]$Length) {
    $alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
    $buffer = New-Object 'byte[]' $Length
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buffer)
    $chars = foreach ($b in $buffer) { $alphabet[$b % $alphabet.Length] }
    return (-join $chars)
}

function Test-Weak([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    if ($Value.Length -lt 32) { return $true }
    return ($Placeholders -contains $Value)
}

# Generate when the key is absent, or when it holds a template/weak value and
# rotation was explicitly requested (or .env was just created from the template).
function Test-ShouldGenerate([string]$Value) {
    if ([string]::IsNullOrWhiteSpace($Value)) { return $true }
    if ($Rotate -or $script:EnvCreated) { return (Test-Weak $Value) }
    return $false
}

function Get-EnvMap([string[]]$Lines) {
    $map = @{}
    foreach ($line in $Lines) {
        $trimmed = $line.Trim()
        if ($trimmed -eq '' -or $trimmed.StartsWith('#') -or -not $trimmed.Contains('=')) { continue }
        $idx = $trimmed.IndexOf('=')
        $map[$trimmed.Substring(0, $idx).Trim()] = $trimmed.Substring($idx + 1).Trim()
    }
    return $map
}

function Set-EnvLine([System.Collections.Generic.List[string]]$Lines, [string]$Key, [string]$Value) {
    for ($i = 0; $i -lt $Lines.Count; $i++) {
        if ($Lines[$i] -match "^\s*$([regex]::Escape($Key))=") {
            $Lines[$i] = "$Key=$Value"
            return
        }
    }
    $Lines.Add("$Key=$Value")
}

function Write-TextFile([string]$Path, [string[]]$Lines) {
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, (($Lines -join "`n") + "`n"), $utf8NoBom)
}

Write-Host '[init] Preparing ARGOS WORKS deployment...'

# --- 1. persistent directories -------------------------------------------------
$dirs = @('data', 'data\backups', 'data\attachments', 'data\templates', 'logs')
$created = @()
foreach ($rel in $dirs) {
    $target = Join-Path $Root $rel
    if (-not (Test-Path -LiteralPath $target -PathType Container)) {
        New-Item -ItemType Directory -Path $target -Force | Out-Null
        $created += $rel
    }
}
if ($created.Count -gt 0) { Write-Host "[init] created directories: $($created -join ', ')" }

# --- 2. .env -------------------------------------------------------------------
$envCreated = $false
if (-not (Test-Path -LiteralPath $EnvPath -PathType Leaf)) {
    if (-not (Test-Path -LiteralPath $EnvExample -PathType Leaf)) {
        Write-Host '[init][ERROR] .env is missing and .env.example could not be found.'
        exit 1
    }
    Copy-Item -LiteralPath $EnvExample -Destination $EnvPath
    $envCreated = $true
    Write-Host '[init] .env created from .env.example'
}

$lines = New-Object 'System.Collections.Generic.List[string]'
(Get-Content -LiteralPath $EnvPath -Encoding UTF8) | ForEach-Object { $lines.Add($_) }
$original = $lines -join "`n"
$map = Get-EnvMap $lines
$changes = @()

if (Test-ShouldGenerate ([string]$map['ARGOS_MASTER_KEY'])) {
    Set-EnvLine $lines 'ARGOS_MASTER_KEY' (New-RandomHex 32)
    $changes += 'ARGOS_MASTER_KEY'
}
if (Test-ShouldGenerate ([string]$map['POSTGRES_PASSWORD'])) {
    Set-EnvLine $lines 'POSTGRES_PASSWORD' (New-RandomPassword 32)
    $changes += 'POSTGRES_PASSWORD'
}

$map = Get-EnvMap $lines
$dbUrl = [string]$map['DATABASE_URL']
$dbUrlStale = [string]::IsNullOrWhiteSpace($dbUrl)
foreach ($p in $Placeholders) { if ($dbUrl -and $dbUrl.Contains($p)) { $dbUrlStale = $true } }
if ($dbUrlStale) {
    $user = if ($map['POSTGRES_USER']) { [string]$map['POSTGRES_USER'] } else { 'argos_admin' }
    $name = if ($map['POSTGRES_DB']) { [string]$map['POSTGRES_DB'] } else { 'argos_works' }
    Set-EnvLine $lines 'DATABASE_URL' "postgresql://$user`:$($map['POSTGRES_PASSWORD'])@localhost:5432/$name"
    $changes += 'DATABASE_URL'
}

$defaults = [ordered]@{
    'TRUSTED_PROXIES'       = '127.0.0.1,::1'
    'SESSION_TTL_HOURS'     = '24'
    'ALLOW_PUBLIC_REGISTER' = 'false'
    'TZ'                    = 'Asia/Seoul'
}
foreach ($key in $defaults.Keys) {
    if (-not $map.ContainsKey($key)) {
        Set-EnvLine $lines $key $defaults[$key]
        $changes += $key
    }
}

$map = Get-EnvMap $lines
$stale = @()
foreach ($key in @('ARGOS_MASTER_KEY', 'POSTGRES_PASSWORD')) {
    if ((Test-Weak ([string]$map[$key])) -and ($changes -notcontains $key)) { $stale += $key }
}
if ($stale.Count -gt 0) {
    Write-Host ("[init] WARNING: template/weak secret(s) in .env: " + ($stale -join ', ') +
        ". Generate strong values manually before going live (rotating ARGOS_MASTER_KEY " +
        "invalidates secrets already encrypted with the old key; rotating POSTGRES_PASSWORD " +
        "requires ALTER USER in PostgreSQL).")
}

if (($lines -join "`n") -ne $original) {
    if ($envCreated) {
        $note = ''
    } else {
        $backup = "$EnvPath.bak-$(Get-Date -Format 'yyyyMMddHHmmss')"
        Copy-Item -LiteralPath $EnvPath -Destination $backup
        $note = "; previous copy at $(Split-Path -Leaf $backup)"
    }
    Write-TextFile $EnvPath $lines
    Write-Host "[init] .env updated ($($changes -join ', '))$note"
    Write-Host '[init] Keep .env secret: it holds the master key used to encrypt stored credentials.'
} else {
    Write-Host '[init] .env unchanged (no secrets needed regeneration)'
}

# --- 3. server\config.json -----------------------------------------------------
if (Test-Path -LiteralPath $ConfigPath -PathType Container) {
    Write-Host ('[init][ERROR] server\config.json is a directory - Docker created it because the ' +
        'file was missing during a previous deploy. Remove that directory (it contains no data) ' +
        'and run this script again.')
    exit 1
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    if (Test-Path -LiteralPath $ConfigSample -PathType Leaf) {
        Copy-Item -LiteralPath $ConfigSample -Destination $ConfigPath
    } else {
        Write-TextFile $ConfigPath @('{', '  "server": { "host": "0.0.0.0", "port": 8080 }', '}')
    }
    Write-Host '[init] server\config.json created'
} else {
    Write-Host '[init] server\config.json present - unchanged'
}

Write-Host '[init] Ready. Next: docker compose up -d --build'
exit 0

