<#
  Sperrt den Internetzugang für Interis (Windows-Firewall), zusätzlich zur Sperre im
  Programm selbst. Gilt nur für runtime\python.exe und runtime\pythonw.exe in DIESEM Ordner.

  Rechtsklick → "Mit PowerShell ausführen". Fragt nach Administratorrechten.

  Vorher die Modelle herunterladen (der Download braucht Internet).
  Nach dem Verschieben des Ordners erneut ausführen.

      Internet-sperren.ps1            Sperre anlegen / aktualisieren
      Internet-sperren.ps1 -Remove    Sperre entfernen (z. B. um Modelle nachzuladen)
#>
param([switch]$Remove)

$ErrorActionPreference = 'Stop'
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSCommandPath`"")
    if ($Remove) { $argList += '-Remove' }
    Start-Process powershell -Verb RunAs -ArgumentList $argList
    return
}

$home_ = $PSScriptRoot
foreach ($exe in 'python.exe', 'pythonw.exe') {
    $program = Join-Path $home_ "runtime\$exe"
    $name = "Interis portable - block outbound ($exe)"
    $existing = Get-NetFirewallRule -DisplayName $name -ErrorAction SilentlyContinue
    if ($Remove) {
        if ($existing) { $existing | Remove-NetFirewallRule; Write-Host "Entfernt: $name" }
        continue
    }
    if (-not (Test-Path $program)) { throw "Nicht gefunden: $program" }
    if ($existing) {
        $existing | Set-NetFirewallRule -Program $program -Direction Outbound -Action Block -Profile Any
        $existing | Enable-NetFirewallRule
        Write-Host "Aktualisiert: $name -> $program"
    } else {
        New-NetFirewallRule -DisplayName $name -Direction Outbound -Action Block -Program $program `
            -Profile Any -Description 'Interis: Interviewdaten verlassen diesen Rechner nie.' | Out-Null
        Write-Host "Angelegt: $name -> $program"
    }
}
Write-Host "`nFertig." -ForegroundColor Green
Read-Host 'Enter zum Schließen'
