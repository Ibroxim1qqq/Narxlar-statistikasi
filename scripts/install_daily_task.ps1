$ErrorActionPreference = "Stop"

$TaskName = "Narxlar Statistikasi Daily Update"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot "run_daily_update.ps1"
$PowerShell = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path $Runner)) {
    throw "Runner script not found: $Runner"
}

$Action = New-ScheduledTaskAction `
    -Execute $PowerShell `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Runner`"" `
    -WorkingDirectory $ProjectRoot
$Trigger = New-ScheduledTaskTrigger -Daily -At 10:00
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Scrapes Uzbekistan new housing prices into data\housing_prices.sqlite every day at 10:00." `
    -Force | Out-Null

Write-Output "Installed task: $TaskName"
Write-Output "Schedule: daily at 10:00"
Write-Output "Runner: $Runner"
