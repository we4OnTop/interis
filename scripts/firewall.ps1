<#
.SYNOPSIS
  Blocks all outbound network traffic of the Python interpreter used by Interis.

.DESCRIPTION
  A Windows venv's python.exe is only a launcher; the process that actually runs (and
  would open network connections) is the base interpreter. This script therefore resolves
  the base interpreter of .venv (a dedicated uv-managed Python) and adds an outbound
  BLOCK rule for it. This also covers native code (CTranslate2, ONNX Runtime) that
  Interis' in-process network guard cannot see.

  Run `interis setup-models` BEFORE enabling the rule (it needs the network once).
  Requires an elevated (administrator) PowerShell.

.EXAMPLE
  .\scripts\firewall.ps1            # add / enable the rule
  .\scripts\firewall.ps1 -Disable   # temporarily disable (e.g. to download a new model)
  .\scripts\firewall.ps1 -Remove    # delete the rule
#>
param(
    [switch]$Disable,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$RuleName = 'Interis - block outbound (python)'

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Please run this script in an administrator PowerShell.'
}

$repo = Split-Path -Parent $PSScriptRoot
$venvPython = Join-Path $repo '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) { throw "Virtualenv not found: $venvPython (run: uv sync)" }

$base = & $venvPython -c "import sys, pathlib; print(pathlib.Path(sys._base_executable).resolve())"
if (-not (Test-Path $base)) { throw "Could not resolve base interpreter: $base" }
if ($base -like '*WindowsApps*') { throw "Refusing: $base is the Microsoft Store Python." }

$existing = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue

if ($Remove) {
    if ($existing) { $existing | Remove-NetFirewallRule; Write-Host "Removed rule '$RuleName'." }
    else { Write-Host 'No rule to remove.' }
    return
}
if ($Disable) {
    if ($existing) { $existing | Disable-NetFirewallRule; Write-Host "Disabled '$RuleName'. Re-run without -Disable afterwards!" }
    return
}

if ($existing) {
    $existing | Set-NetFirewallRule -Program $base -Direction Outbound -Action Block -Profile Any
    $existing | Enable-NetFirewallRule
    Write-Host "Updated and enabled '$RuleName' for $base"
} else {
    New-NetFirewallRule -DisplayName $RuleName -Direction Outbound -Action Block `
        -Program $base -Profile Any -Description 'Interis: interview data must never leave this machine.' | Out-Null
    Write-Host "Created '$RuleName' for $base"
}
Write-Host 'Note: this blocks internet access for this Python interpreter in every project that uses it.'
