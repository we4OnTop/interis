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

# The desktop app runs under pythonw.exe from the same folder: it needs the same rule.
$baseGui = Join-Path (Split-Path $base) 'pythonw.exe'
$guiRule = "$RuleName (GUI)"

function Set-BlockRule([string]$name, [string]$program) {
    $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if ($rule) {
        $rule | Set-NetFirewallRule -Program $program -Direction Outbound -Action Block -Profile Any
        $rule | Enable-NetFirewallRule
        Write-Host "Updated and enabled '$name' for $program"
    } else {
        New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Block `
            -Program $program -Profile Any -Description 'Interis: interview data must never leave this machine.' | Out-Null
        Write-Host "Created '$name' for $program"
    }
}

if ($Remove) {
    foreach ($name in @($RuleName, $guiRule)) {
        $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
        if ($rule) { $rule | Remove-NetFirewallRule; Write-Host "Removed rule '$name'." }
    }
    if (-not (Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue) -and
        -not (Get-NetFirewallRule -DisplayName $guiRule -ErrorAction SilentlyContinue)) {
        Write-Host 'No rule to remove.'
    }
    return
}
if ($Disable) {
    foreach ($name in @($RuleName, $guiRule)) {
        $rule = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
        if ($rule) { $rule | Disable-NetFirewallRule; Write-Host "Disabled '$name'. Re-run without -Disable afterwards!" }
    }
    return
}

Set-BlockRule $RuleName $base
if (Test-Path $baseGui) {
    Set-BlockRule $guiRule $baseGui
} else {
    Write-Warning "No $baseGui next to the base interpreter: the desktop app is not covered by a rule."
}
Write-Host 'Note: this blocks internet access for this Python interpreter in every project that uses it.'
