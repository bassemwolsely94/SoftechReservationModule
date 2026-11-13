<#
.SYNOPSIS
    Finds what is installed for the eSeal USB token on this PC. Read-only. Never asks for a PIN.

.DESCRIPTION
    Run on the signing workstation, with the token plugged in, from an administrator PowerShell:

        powershell -ExecutionPolicy Bypass -File .\identify_token.ps1

    It writes token_report.txt beside this script. Send that file back. It holds machine, certificate
    and program names, and no PIN, password or private key. Command lines are left out on purpose,
    because programs sometimes carry passwords in them.

    What it does NOT do:
      * It does not log in to the token, load a PKCS#11 module, or touch the private key.
      * It avoids "certutil -scinfo", which can prompt for the PIN and try the card.
      * It changes nothing and starts or stops nothing.

    HONESTY NOTE. The module names below (eps2003csp11.dll, eTPKCS11.dll and the others) come from general
    knowledge of common tokens, not from this PC. Nobody has seen this token yet. What this script finds
    decides what is used, and the names may be wrong or incomplete.
#>
param(
    [string]$OutFile = (Join-Path $PSScriptRoot 'token_report.txt')
)

$ErrorActionPreference = 'Continue'
# This PC is also a database server: the disk search must give way to it.
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch { }
$lines = New-Object System.Collections.ArrayList

function Say([string]$text = '') {
    [void]$lines.Add($text)
    Write-Host $text
}

function Section([string]$title) {
    Say ''
    Say ('=' * 78)
    Say $title
    Say ('=' * 78)
}

function Try-Run([string]$label, [scriptblock]$block) {
    try {
        & $block
    } catch {
        Say "[$label could not run: $($_.Exception.GetType().Name)]"
    }
}

# Reads the PE header only, to tell a 32-bit DLL from a 64-bit one.
function Get-PeBits([string]$path) {
    $stream = $null
    try {
        $stream = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        $reader = New-Object System.IO.BinaryReader($stream)
        [void]$stream.Seek(0x3C, 'Begin')
        $peOffset = $reader.ReadInt32()
        [void]$stream.Seek($peOffset + 4, 'Begin')
        switch ($reader.ReadUInt16()) {
            0x014C { return '32-bit' }
            0x8664 { return '64-bit' }
            default { return 'unknown' }
        }
    } catch {
        return 'unreadable'
    } finally {
        if ($stream) { $stream.Dispose() }
    }
}

# A real PKCS#11 module exports C_GetFunctionList. The text is searched; the DLL is not loaded.
function Test-Pkcs11Export([string]$path) {
    try {
        $item = Get-Item -LiteralPath $path
        if ($item.Length -gt 50MB) { return 'too large to check' }
        $text = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($path))
        if ($text.Contains('C_GetFunctionList')) { return 'yes' }
        return 'no'
    } catch {
        return 'unreadable'
    }
}

Say 'ElRezeiky tax seal: token identification report'
Say "Generated: $((Get-Date).ToString('yyyy-MM-dd HH:mm:ss zzz'))"
Say 'Read-only. No PIN was asked for or used.'
Say 'Module names searched for come from general knowledge; what is found below is what counts.'

Section 'THIS PC'
Try-Run 'system info' {
    $os = Get-CimInstance Win32_OperatingSystem
    Say "Computer:     $env:COMPUTERNAME"
    Say "Windows:      $($os.Caption) build $($os.BuildNumber) ($($os.OSArchitecture))"
    Say "PowerShell:   $($PSVersionTable.PSVersion)"
    Say "Clock now:    $((Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm:ss')) UTC (check it is correct; signatures carry this time)"
}
Try-Run 'network' {
    Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | ForEach-Object {
        Say "Network:      $($_.IPAddress -join ', ')  gateway: $($_.DefaultIPGateway -join ', ')  DNS: $($_.DNSServerSearchOrder -join ', ')"
    }
}
Try-Run 'python' {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) { & py.exe -0p 2>&1 | ForEach-Object { Say "Python:       $_" } }
    Get-Command python.exe -All -ErrorAction SilentlyContinue | ForEach-Object {
        Say "python.exe:   $($_.Source) ($(Get-PeBits $_.Source))"
    }
    if (-not $py -and -not (Get-Command python.exe -ErrorAction SilentlyContinue)) { Say 'Python:       not installed' }
}

Section 'PKCS#11 MODULES ON DISK'
$knownNames = @(
    'eps2003csp11*.dll', 'eTPKCS11.dll', 'eToken.dll', 'dkck201.dll', 'ShuttleCsp11*.dll', 'ngp11v211.dll', 'SafeNet*.dll',
    'aetpkss1.dll', 'gclib.dll', 'opensc-pkcs11.dll', 'acos5*.dll', 'cryptoide_pkcs11.dll', 'WDPKCS.dll', 'bit4ipki.dll',
    '*pkcs11*.dll', '*pkcs#11*.dll', '*p11*.dll', '*csp11*.dll'
)
$searchRoots = @($env:ProgramFiles, ${env:ProgramFiles(x86)}) | Where-Object { $_ } | Select-Object -Unique
$found = @{}
# Windows folders: top level only. Program folders: recursive, and only these name patterns.
foreach ($folder in @((Join-Path $env:WINDIR 'System32'), (Join-Path $env:WINDIR 'SysWOW64'))) {
    foreach ($pattern in $knownNames) {
        Get-ChildItem -Path (Join-Path $folder $pattern) -File -ErrorAction SilentlyContinue | ForEach-Object { $found[$_.FullName] = $_ }
    }
}
foreach ($root in $searchRoots) {
    Get-ChildItem -Path $root -Recurse -File -Include $knownNames -ErrorAction SilentlyContinue | ForEach-Object { $found[$_.FullName] = $_ }
}
$modules = @()
foreach ($item in ($found.Values | Sort-Object FullName)) {
    $export = Test-Pkcs11Export $item.FullName
    $info = $item.VersionInfo
    $bits = Get-PeBits $item.FullName
    if ($export -eq 'yes') { $modules += [pscustomobject]@{ Path = $item.FullName; Bits = $bits } }
    Say $item.FullName
    Say "    bitness: $bits   exports C_GetFunctionList: $export   version: $($info.FileVersion)   company: $($info.CompanyName)   product: $($info.ProductName)"
}
if ($found.Count -eq 0) { Say 'None found under the searched names and folders. Look for the vendor program in the installed list below.' }

Section 'LIKELY CANDIDATES FOR agent.py'
if ($modules.Count -eq 0) { Say 'No DLL here exports C_GetFunctionList.' }
foreach ($m in $modules) { Say "$($m.Bits)  $($m.Path)" }
Say 'Python must have the same bitness as the module chosen.'

Section 'SMART-CARD SERVICE AND READERS'
Try-Run 'smart-card service' {
    Get-Service SCardSvr, ScDeviceEnum, CertPropSvc -ErrorAction SilentlyContinue | ForEach-Object {
        Say "$($_.Name): $($_.Status), start $($_.StartType)"
    }
}
Try-Run 'readers registry' {
    $readers = Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Cryptography\Calais\Readers' -ErrorAction SilentlyContinue
    foreach ($r in $readers) { Say "Reader (registry): $($r.PSChildName)" }
    if (-not $readers) { Say 'No reader registered in the Calais registry key (some USB tokens do not use one).' }
}
Try-Run 'connected devices' {
    $pattern = 'smart ?card|token|epass|safenet|gemalto|thales|feitian|aladdin|watchdata|bit4id|egypt trust|ccid'
    Get-CimInstance Win32_PnPEntity | Where-Object {
        $_.Name -match $pattern -or $_.PNPClass -match '^(SmartCard|SmartCardReader|SmartCardFilter)$'
    } | ForEach-Object { Say "Device: $($_.Name)  [class $($_.PNPClass), status $($_.Status)]" }
}
Try-Run 'card registry' {
    foreach ($key in @('HKLM:\SOFTWARE\Microsoft\Cryptography\Calais\SmartCards', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Cryptography\Calais\SmartCards')) {
        Get-ChildItem $key -ErrorAction SilentlyContinue | ForEach-Object {
            $values = Get-ItemProperty $_.PSPath
            $csp = $values.'Crypto Provider'
            $ksp = $values.'Smart Card Key Storage Provider'
            if ($csp -or $ksp) { Say "Card type: $($_.PSChildName)  CSP: $csp  KSP: $ksp" }
        }
    }
}
Try-Run 'crypto providers' {
    $builtIn = '^Microsoft '
    Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\Cryptography\Defaults\Provider' -ErrorAction SilentlyContinue |
        Where-Object { $_.PSChildName -notmatch $builtIn } |
        ForEach-Object { Say "Non-Microsoft crypto provider: $($_.PSChildName)" }
}

Section 'CERTIFICATES IN THE WINDOWS STORE (no key access)'
Say 'A token''s certificate usually appears here only if its middleware has copied it.'
foreach ($location in 'CurrentUser', 'LocalMachine') {
    Try-Run "$location store" {
        $store = New-Object System.Security.Cryptography.X509Certificates.X509Store('My', $location)
        $store.Open('ReadOnly, OpenExistingOnly')
        Say "--- $location\My: $($store.Certificates.Count) certificate(s)"
        foreach ($c in $store.Certificates) {
            Say "Subject:    $($c.Subject)"
            Say "Issuer:     $($c.Issuer)"
            Say "Serial:     $($c.SerialNumber)"
            Say "Expires:    $($c.NotAfter.ToString('yyyy-MM-dd'))"
            Say "Thumbprint: $($c.Thumbprint)"
            Say ''
        }
        $store.Close()
    }
}

Section 'CERTIFICATE PROVIDERS (certutil, silent)'
Say 'Silent mode: certutil may not show a PIN box. A "cannot find the certificate and private key" or'
Say 'encryption test failure line here is expected when the key is on a token.'
$fields = 'Serial Number|Issuer:|Subject:|NotAfter|Cert Hash\(sha1\)|Provider =|Key Container|Unique container|================'
foreach ($arguments in @(@('-silent', '-store', 'My'), @('-silent', '-user', '-store', 'My'))) {
    Try-Run 'certutil' {
        Say "--- certutil $($arguments -join ' ')"
        & certutil.exe @arguments 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match $fields } | ForEach-Object { Say $_ }
    }
}

Section 'INSTALLED PROGRAMS THAT MAY BE RELATED'
$programPattern = 'token|epass|safenet|gemalto|thales|feitian|aladdin|watchdata|bit4id|egypt ?trust|mcdr|misr|e-?services|e-?invoic|e-?receipt|invoic|tax|eta\b|sign|seal|softech'
Try-Run 'installed programs' {
    $keys = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
            'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    Get-ItemProperty $keys -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -and $_.DisplayName -match $programPattern } |
        Sort-Object DisplayName -Unique |
        ForEach-Object { Say "$($_.DisplayName)  v$($_.DisplayVersion)  [$($_.Publisher)]  installed $($_.InstallDate)  at $($_.InstallLocation)" }
}

Section 'SERVICES THAT MAY HOLD THE TOKEN'
Try-Run 'services' {
    Get-CimInstance Win32_Service | Where-Object {
        $_.Name -match $programPattern -or $_.DisplayName -match $programPattern -or $_.PathName -match $programPattern
    } | ForEach-Object {
        # The executable only: a service's arguments can hold secrets.
        $exe = if ($_.PathName -match '^\s*"([^"]+)"') { $Matches[1] } else { ($_.PathName -split '\s+')[0] }
        Say "$($_.Name) [$($_.DisplayName)]  $($_.State), start $($_.StartMode), runs as $($_.StartName)  exe: $exe"
    }
}

Section 'PROCESSES THAT MAY HOLD THE TOKEN'
Say 'Programs running now that match by name, or that have one of the modules above loaded.'
Say 'Module checks need administrator rights to see other users'' processes.'
Try-Run 'processes' {
    $moduleNames = @($found.Values | ForEach-Object { $_.Name })
    $moduleNames += 'winscard.dll'
    foreach ($p in Get-Process) {
        $hits = @()
        try {
            foreach ($m in $p.Modules) {
                if ($moduleNames -contains $m.ModuleName) { $hits += $m.ModuleName }
            }
        } catch { }
        $path = ''
        try { $path = $p.Path } catch { }
        $vendorHits = @($hits | Where-Object { $_ -ne 'winscard.dll' })
        if ($vendorHits.Count -gt 0 -or $p.ProcessName -match $programPattern -or $path -match $programPattern) {
            Say "$($p.ProcessName) (pid $($p.Id), started $($p.StartTime))  $path"
            if ($hits.Count -gt 0) { Say "    has loaded: $(($hits | Sort-Object -Unique) -join ', ')" }
        }
    }
}

Section 'SCHEDULED TASKS THAT MAY USE THE TOKEN'
Try-Run 'scheduled tasks' {
    Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -match $programPattern -or $_.TaskPath -match $programPattern } | ForEach-Object {
        $exe = @($_.Actions | ForEach-Object { $_.Execute }) -join ', '
        Say "$($_.TaskPath)$($_.TaskName)  state: $($_.State)  runs: $exe"
    }
}

Section 'END'
Say 'Next step: send this file back. Do not attach any PIN or password.'

[System.IO.File]::WriteAllLines($OutFile, [string[]]$lines, (New-Object System.Text.UTF8Encoding($true)))
Write-Host ''
Write-Host "Report written to: $OutFile"
