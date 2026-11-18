# Restore a fresh UAT copy of the office database:
#   . scripts/uat/uat-env.ps1; scripts/uat/heavy.ps1 -Name "UAT refresh" -Command { scripts/uat/refresh_uat_db.ps1 }
# Reads elrezeiky_db with pg_dump (read only), restores into <Target>_next and migrates it with this
# branch's code under config.settings_uat; only when both succeed is the old copy dropped and
# <Target>_next renamed to <Target>. A failure leaves the working copy untouched. Stops on the first error.
# Local Postgres only (the office PC); -AllowRemoteHost to override.
param(
    [string] $Target = 'elrezeiky_uat',
    [string] $Source = 'elrezeiky_db',
    [switch] $KeepDump,
    [switch] $AllowRemoteHost
)
$ErrorActionPreference = 'Stop'
if ($Target -notmatch '^elrezeiky_uat') { throw "refusing: target $Target is not a UAT database" }
if ($Target -eq $Source) { throw 'refusing: target equals source' }
if (-not $env:UAT_PG_USER) { throw 'run . scripts/uat/uat-env.ps1 first' }
$pgHost = ($env:UAT_PG_HOST, 'localhost' | Where-Object { $_ } | Select-Object -First 1)
if (-not $AllowRemoteHost -and $pgHost -notin @('localhost', '127.0.0.1', '::1')) {
    throw "refusing: PG host $pgHost is not this PC (a UAT copy is never made on a server)"
}
$Next = "${Target}_next"

$freeGB = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
$os = Get-CimInstance Win32_OperatingSystem
$ramGB = [math]::Round($os.FreePhysicalMemory / 1MB, 1)
if ($freeGB -lt 40) { Write-Host "[refresh] only $freeGB GB free on C: (need 40)"; exit 2 }
if ($ramGB -lt 6) { Write-Host "[refresh] only $ramGB GB RAM free (need 6)"; exit 2 }

$env:PGPASSWORD = $env:UAT_PG_PASSWORD
$conn = @('-U', $env:UAT_PG_USER, '-h', ($env:UAT_PG_HOST, 'localhost' | Where-Object { $_ } | Select-Object -First 1),
          '-p', ($env:UAT_PG_PORT, '5432' | Where-Object { $_ } | Select-Object -First 1))
$dump = Join-Path $env:TEMP "$Target.dump"

function Run($exe, [string[]]$argv) {
    # Postgres tools print NOTICEs on stderr; judge them by exit code, not by stderr.
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & (Join-Path $env:PGBIN $exe) @argv 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE) { throw "$exe exited $LASTEXITCODE" }
}

try {
    $t0 = Get-Date
    Write-Host "[refresh] dumping $Source (read only) ..."
    Run 'pg_dump.exe' ($conn + @('-Fc', '-d', $Source, '-f', $dump))
    Write-Host "[refresh] restoring into $Next (the working copy stays up) ..."
    Run 'dropdb.exe' ($conn + @('--if-exists', $Next))
    Run 'createdb.exe' ($conn + @($Next))
    Run 'pg_restore.exe' ($conn + @('-j', '2', '--no-owner', '-d', $Next, $dump))
    Write-Host "[refresh] migrating $Next with this branch's code ..."
    $env:UAT_PG_NAME = $Next
    $prev = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    try { & $env:UAT_PYTHON manage.py migrate --noinput --settings=config.settings_uat 2>&1 | ForEach-Object { "$_" } }
    finally { $ErrorActionPreference = $prev }
    if ($LASTEXITCODE) { throw "migrate exited $LASTEXITCODE - $Target untouched, $Next left for inspection" }
    Write-Host "[refresh] swapping $Next in for $Target ..."
    $swap = "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname IN ('$Target', '$Next') AND pid <> pg_backend_pid();"
    Run 'psql.exe' ($conn + @('-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', $swap))
    Run 'dropdb.exe' ($conn + @('--if-exists', $Target))
    Run 'psql.exe' ($conn + @('-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-c', "ALTER DATABASE `"$Next`" RENAME TO `"$Target`";"))
    $env:UAT_PG_NAME = $Target
    $mins = [math]::Round(((Get-Date) - $t0).TotalMinutes, 1)
    Write-Host "[OK] $Target restored and migrated in $mins min"
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    if (-not $KeepDump -and (Test-Path $dump)) { Remove-Item $dump -Force }
}
