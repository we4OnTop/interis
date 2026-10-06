<#
.SYNOPSIS
  Installs Interis on this Windows PC (run in the project folder, normal PowerShell).

.DESCRIPTION
  1. checks that uv is installed
  2. installs the exact, locked Python environment (uv sync --locked)
  3. sets INTERIS_DATA_DIR permanently for your user (your encrypted data folder)
  4. optionally copies already prepared models from another PC (USB stick) – saves ~8 GB
     download and the conversion time; they are verified by hash before every use
  5. downloads / verifies the models (the only step that uses the internet)
  6. tells you how to block internet access for Interis and runs the self-check

.EXAMPLE
  .\scripts\install.ps1 -DataDir X:\interis-data
  .\scripts\install.ps1 -DataDir X:\interis-data -ModelsFrom E:\interis-models
  .\scripts\install.ps1 -DataDir X:\interis-data -UseSystemCerts -AllowVerifiedMirror
#>
param(
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$ModelsFrom,
    [switch]$UseSystemCerts,
    [switch]$AllowVerifiedMirror
)

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Step($text) { Write-Host "`n== $text" -ForegroundColor Cyan }

# 1. uv
Step 'Checking uv'
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv is not installed. Install it with:' -ForegroundColor Yellow
    Write-Host '    winget install --id=astral-sh.uv -e'
    Write-Host 'then open a NEW PowerShell window and run this script again.'
    exit 1
}
uv --version

# 2. environment
Step 'Installing the locked Python environment (this can take a few minutes)'
uv sync --locked
if ($LASTEXITCODE -ne 0) { throw 'uv sync failed' }

# 3. data directory
Step 'Data directory'
if (-not (Test-Path $DataDir)) {
    $answer = Read-Host "$DataDir does not exist. Create it? (j/n)"
    if ($answer -ne 'j') { exit 1 }
    New-Item -ItemType Directory -Path $DataDir | Out-Null
}
$DataDir = (Resolve-Path $DataDir).Path
foreach ($od in @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial)) {
    if ($od -and $DataDir.StartsWith($od, [StringComparison]::OrdinalIgnoreCase)) {
        throw "The data directory is inside OneDrive ($od). Use your encrypted VeraCrypt volume instead."
    }
}
foreach ($risky in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('MyDocuments'))) {
    if ($risky -and $DataDir.StartsWith($risky, [StringComparison]::OrdinalIgnoreCase)) {
        Write-Host "Warning: $DataDir is under $risky, which Windows may back up to OneDrive." -ForegroundColor Yellow
    }
}
[Environment]::SetEnvironmentVariable('INTERIS_DATA_DIR', $DataDir, 'User')
$env:INTERIS_DATA_DIR = $DataDir
Write-Host "INTERIS_DATA_DIR = $DataDir (saved for your user)"

# 4. optional: copy prepared models
if ($ModelsFrom) {
    Step "Copying prepared models from $ModelsFrom"
    $target = Join-Path $DataDir 'models'
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    robocopy $ModelsFrom $target /E /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
    $global:LASTEXITCODE = 0
}

# 5. models (verifies copied ones, downloads missing ones)
Step 'Models (verifying / downloading)'
$args = @('run', 'interis', 'setup-models')
if ($UseSystemCerts) { $args += '--use-system-certs' }
if ($AllowVerifiedMirror) { $args += '--allow-verified-mirror' }
& uv @args
if ($LASTEXITCODE -ne 0) {
    Write-Host @'
Model setup did not finish. Common causes:
  * "CERTIFICATE_VERIFY_FAILED": an antivirus scans HTTPS -> add -UseSystemCerts
  * pyannote "gated model": set $env:HF_TOKEN (see README) or add -AllowVerifiedMirror
'@ -ForegroundColor Yellow
    exit 1
}

# 6. next steps
Step 'Almost done'
Write-Host @"
Now block internet access for Interis (PowerShell **as administrator**, in this folder):
    .\scripts\firewall.ps1

Then check everything:
    uv run interis doctor

Transcribe:      uv run interis transcribe <audio> --id I01 --guide $DataDir\leitfaden.md
Website:         uv run interis serve
"@
