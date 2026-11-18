# Dot-source before any UAT command:   . scripts/uat/uat-env.ps1
# Sets ONLY the database login (UAT_PG_USER/PASSWORD/HOST/PORT) from the main checkout's .env,
# plus DJANGO_SETTINGS_MODULE=config.settings_uat. Nothing else from that .env (it is the live
# SOFTECH writer) is read. Values are never printed.
$ErrorActionPreference = 'Stop'
$common = (git rev-parse --path-format=absolute --git-common-dir).Trim()
$mainRoot = Split-Path $common -Parent
$envFile = Join-Path $mainRoot '.env'
if (-not (Test-Path $envFile)) { throw "uat-env: no .env at $mainRoot" }
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*PG_(USER|PASSWORD|HOST|PORT)\s*=\s*(.*)$') {
        $val = $Matches[2].Trim().Trim('"').Trim("'")
        Set-Item -Path "Env:UAT_PG_$($Matches[1])" -Value $val
    }
}
if (-not $env:UAT_PG_NAME) { $env:UAT_PG_NAME = 'elrezeiky_uat' }
$env:DJANGO_SETTINGS_MODULE = 'config.settings_uat'
$env:PYTHONIOENCODING = 'utf-8'
$env:UAT_PYTHON = Join-Path $mainRoot 'venv\Scripts\python.exe'
$env:PGBIN = 'C:\Program Files\PostgreSQL\16\bin'
Write-Host "[uat-env] DB login loaded for $($env:UAT_PG_NAME); settings=config.settings_uat"
