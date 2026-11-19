# One heavy UAT run at a time on this PC (DB refresh, a full sweep, a load run) - parallel heavy
# runs crashed Postgres twice (memory: pc_memory_and_ci_timeouts). Usage:
#   scripts/uat/heavy.ps1 -Name "W2 visibility sweep" -Command { npm run test:uat -- visibility }
# Exit 3 = another heavy run holds the lock (its label is printed).
param(
    [Parameter(Mandatory)] [string] $Name,
    [Parameter(Mandatory)] [scriptblock] $Command
)
$lock = Join-Path $env:TEMP 'elrezeiky-uat-heavy.lock'

function Test-Stale($path) {
    try {
        $info = Get-Content $path -Raw | ConvertFrom-Json
        $age = (Get-Date) - [datetime]$info.started
        $alive = Get-Process -Id $info.pid -ErrorAction SilentlyContinue
        return (-not $alive) -and ($age.TotalHours -gt 6 -or -not $alive)
    } catch { return $true }
}

if ((Test-Path $lock) -and (Test-Stale $lock)) { Remove-Item $lock -Force }
try {
    $fs = [IO.File]::Open($lock, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
} catch {
    $holder = Get-Content $lock -Raw -ErrorAction SilentlyContinue
    Write-Host "[heavy] busy - another heavy UAT run holds the lock: $holder"
    exit 3
}
$payload = @{ name = $Name; pid = $PID; started = (Get-Date).ToString('o') } | ConvertTo-Json -Compress
$bytes = [Text.Encoding]::UTF8.GetBytes($payload)
$fs.Write($bytes, 0, $bytes.Length); $fs.Close()
Write-Host "[heavy] lock taken: $Name"
$code = 0
try {
    & $Command
    if ($LASTEXITCODE) { $code = $LASTEXITCODE }
} catch {
    Write-Host "[heavy] failed: $_"
    $code = 1
} finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
    Write-Host "[heavy] lock released: $Name"
}
exit $code
