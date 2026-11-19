# Shared UAT backend on 127.0.0.1:8200 (config.settings_uat: reader copy, writers off) with a
# watchdog: if runserver exits for any reason it is started again after 5 s. Stop it by deleting
# the stop file printed below, or by killing this PowerShell process.
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts/uat/serve.ps1
$ErrorActionPreference = 'Continue'
. "$PSScriptRoot\uat-env.ps1"
$repo = (Resolve-Path "$PSScriptRoot\..\..").Path
$run = Join-Path $env:TEMP 'elrezeiky-uat-serve.run'
Set-Content -Path $run -Value $PID -Encoding ascii
$log = Join-Path $env:TEMP 'uat-server-8200.log'
Write-Output "[serve] watchdog pid $PID; delete $run to stop after the current server exits"
while (Test-Path $run) {
    $busy = Get-NetTCPConnection -LocalPort 8200 -State Listen -ErrorAction SilentlyContinue
    if ($busy) { Start-Sleep -Seconds 15; continue }      # someone else's server answers: leave it
    Add-Content -Path $log -Value "[serve] $(Get-Date -Format s) starting runserver"
    $p = Start-Process -FilePath $env:UAT_PYTHON -WorkingDirectory $repo -PassThru -NoNewWindow `
        -ArgumentList 'manage.py', 'runserver', '127.0.0.1:8200', '--noreload', '--settings=config.settings_uat' `
        -RedirectStandardError $log -RedirectStandardOutput (Join-Path $env:TEMP 'uat-server-8200.out.log')
    $p.WaitForExit()
    Add-Content -Path (Join-Path $env:TEMP 'uat-serve-exits.log') -Value "$(Get-Date -Format s) runserver exited code $($p.ExitCode)"
    Start-Sleep -Seconds 5
}
