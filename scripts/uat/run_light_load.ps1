# W7 light load on the UAT copy (plan Task 11, docs/uat/light-load.md). Read-only Locust mix
# (login POST + GETs) from deploy/loadtest/locustfile.py in UAT mode (role mix from .uat-users.json):
# stage 1 = 5 users for 5 min, stage 2 = 10 users for 10 min, headless, CSV stats to
# frontend/test-results-uat/load/. Runs as ONE heavy run through heavy.ps1.
#
#   . scripts/uat/uat-env.ps1
#   scripts/uat/run_light_load.ps1                  # needs the shared UAT server on 127.0.0.1:8200
#   scripts/uat/run_light_load.ps1 -StartServer     # start it here if nothing listens (stopped at the end)
#
# Memory guard: refuses to start below -MinFreeGB free RAM; while running it samples free RAM,
# Postgres and the runserver process every 10 s into memory.csv and stops Locust early (exit 4)
# if free RAM drops below -FloorGB. Locust lives in its own venv (.venv-locust, created on demand).
param(
    [string] $TargetHost = 'http://127.0.0.1:8200',
    [int] $Stage1Users = 5, [int] $Stage1Minutes = 5,
    [int] $Stage2Users = 10, [int] $Stage2Minutes = 10,
    [double] $MinFreeGB = 6, [double] $FloorGB = 3,
    [string] $UsersJson = '',
    [switch] $StartServer
)
$ErrorActionPreference = 'Stop'
$root = (git rev-parse --show-toplevel).Trim()
if ($env:DJANGO_SETTINGS_MODULE -ne 'config.settings_uat') { throw 'run . scripts/uat/uat-env.ps1 first' }
if ($TargetHost -notmatch '^http://127\.0\.0\.1:8200/?$' -and $TargetHost -notmatch '^http://127\.0\.0\.1:82\d\d/?$') {
    throw "run_light_load is for the local UAT copy only (127.0.0.1:82xx), not $TargetHost"
}

function Get-FreeGB { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory / 1MB, 2) }

$free = Get-FreeGB
if ($free -lt $MinFreeGB) { Write-Host "[load] refused: free RAM $free GB < $MinFreeGB GB"; exit 2 }

# users file: this worktree's git-ignored copy, else the main UAT worktree's (copied, never printed)
if (-not $UsersJson) {
    $UsersJson = Join-Path $root 'frontend/uat/.uat-users.json'
    if (-not (Test-Path $UsersJson)) {
        $common = (git rev-parse --path-format=absolute --git-common-dir).Trim()
        $src = Join-Path (Split-Path $common -Parent) '.claude/worktrees/role-uat/frontend/uat/.uat-users.json'
        if (-not (Test-Path $src)) { throw 'no .uat-users.json (run seed_uat_users in the role-uat worktree)' }
        New-Item -ItemType Directory -Force (Split-Path $UsersJson) | Out-Null
        Copy-Item $src $UsersJson
    }
}

# locust venv
$venv = Join-Path $root '.venv-locust'
$locust = Join-Path $venv 'Scripts/locust.exe'
if (-not (Test-Path $locust)) {
    & $env:UAT_PYTHON -m venv $venv
    & (Join-Path $venv 'Scripts/python.exe') -m pip install -q locust
}

$rel = 'frontend/test-results-uat/load'
$out = Join-Path $root $rel
New-Item -ItemType Directory -Force $out | Out-Null
$port = ([uri]$TargetHost).Port

function Test-Server {
    try { Invoke-WebRequest "$TargetHost/api/auth/me/" -UseBasicParsing -TimeoutSec 15 | Out-Null; return $true }
    catch { return [bool]$_.Exception.Response }       # 401 = the server answered
}

$body = {
    $server = $null
    if (-not (Test-Server)) {
        if (-not $StartServer) { Write-Host "[load] nothing answers on $TargetHost (use -StartServer)"; $global:LASTEXITCODE = 5; return }
        Write-Host "[load] starting the shared UAT server on $port (runserver --noreload, settings_uat)"
        $server = Start-Process $env:UAT_PYTHON -ArgumentList 'manage.py', 'runserver', "127.0.0.1:$port", '--noreload', '--settings=config.settings_uat' `
            -WorkingDirectory $root -PassThru -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $out 'server.out.log') -RedirectStandardError (Join-Path $out 'server.err.log')
        $deadline = (Get-Date).AddMinutes(5)
        while (-not (Test-Server)) {
            if ((Get-Date) -gt $deadline -or $server.HasExited) { throw 'UAT server did not come up' }
            Start-Sleep 5
        }
    }
    $serverPid = (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1).OwningProcess
    $mem = Join-Path $out 'memory.csv'
    'time,stage,free_gb,pg_ws_gb,pg_private_gb,pg_procs,server_ws_gb,locust_running' | Set-Content $mem -Encoding utf8
    $floorHit = $false
    $env:UAT_USERS_JSON = $UsersJson
    try {
        foreach ($stage in @(@{u = $Stage1Users; m = $Stage1Minutes }, @{u = $Stage2Users; m = $Stage2Minutes })) {
            $tag = "load_$($stage.u)u"
            Write-Host "[load] stage $tag : $($stage.u) users for $($stage.m) min (free RAM $(Get-FreeGB) GB)"
            # relative --csv/--logfile paths: Start-Process does not quote arguments with spaces
            $p = Start-Process $locust -ArgumentList '-f', 'deploy/loadtest/locustfile.py', '--host', $TargetHost, '--headless',
                '--users', $stage.u, '--spawn-rate', '1', '--run-time', "$($stage.m)m", '--stop-timeout', '30',
                '--csv', "$rel/$tag", '--only-summary', '--logfile', "$rel/$tag.log" `
                -WorkingDirectory $root -PassThru -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $out "$tag.out.txt") -RedirectStandardError (Join-Path $out "$tag.err.txt")
            $null = $p.Handle      # cache the handle, else ExitCode reads blank after exit
            while (-not $p.HasExited) {
                $f = Get-FreeGB
                $pg = @(Get-Process postgres -ErrorAction SilentlyContinue)
                $pgWs = [math]::Round(($pg | Measure-Object WorkingSet64 -Sum).Sum / 1GB, 2)
                $pgPriv = [math]::Round(($pg | Measure-Object PrivateMemorySize64 -Sum).Sum / 1GB, 2)
                $srv = if ($serverPid) { Get-Process -Id $serverPid -ErrorAction SilentlyContinue }
                $srvWs = if ($srv) { [math]::Round($srv.WorkingSet64 / 1GB, 2) } else { '' }
                "$((Get-Date).ToString('s')),$tag,$f,$pgWs,$pgPriv,$($pg.Count),$srvWs,1" | Add-Content $mem -Encoding utf8
                if ($f -lt $FloorGB) {
                    Write-Host "[load] FLOOR HIT: free RAM $f GB < $FloorGB GB - stopping Locust"
                    Stop-Process -Id $p.Id -Force; $floorHit = $true; break
                }
                Start-Sleep 10
            }
            if ($floorHit) { break }
            Write-Host "[load] stage $tag done (locust exit $($p.ExitCode); non-zero = some requests failed)"
        }
    } finally {
        Remove-Item Env:UAT_USERS_JSON -ErrorAction SilentlyContinue
        if ($server -and -not $server.HasExited) { Write-Host '[load] stopping the UAT server started here'; Stop-Process -Id $server.Id -Force }
    }
    $global:LASTEXITCODE = if ($floorHit) { 4 } else { 0 }
}   # no GetNewClosure: heavy.ps1 runs as a child scope, so this script's functions stay visible

& (Join-Path $root 'scripts/uat/heavy.ps1') -Name 'W7 light load' -Command $body
exit $LASTEXITCODE
