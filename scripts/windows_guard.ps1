param(
    [switch]$Watch,
    [string]$Distribution,
    [string]$ProjectRoot,
    [string]$LinuxUser
)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

function Read-Dword([string]$Path, [string]$Name) {
    try {
        $key = Get-Item -LiteralPath $Path
        if ($key.GetValueKind($Name) -ne [Microsoft.Win32.RegistryValueKind]::DWord) { return $null }
        return [int]$key.GetValue($Name)
    }
    catch { return $null }
}

function Get-Protection {
    $problems = [System.Collections.Generic.List[string]]::new()
    $power = "HKLM:\SYSTEM\CurrentControlSet\Control\Power"
    $crash = "HKLM:\SYSTEM\CurrentControlSet\Control\CrashControl"
    if ((Read-Dword $power "HibernateEnabled") -cne 0) {
        $problems.Add("Windows hibernation must be disabled.")
    }
    if ((Read-Dword $crash "CrashDumpEnabled") -cne 0) {
        $problems.Add("Windows system crash dumps must be disabled.")
    }
    if ((Read-Dword "$crash\FullLiveKernelReports" "FullLiveReportsMax") -cne 0) {
        $problems.Add("Windows live kernel dumps must be disabled.")
    }
    try {
        $paging = @(Get-CimInstance -ClassName Win32_PageFileUsage -ErrorAction Stop)
        if ($paging.Count -ne 0) {
            $problems.Add("A Windows page file is active. See docs/WSL.md.")
        }
    } catch {
        $problems.Add("Cannot verify Windows page-file state.")
    }
    try {
        $section = ""
        $dumpCount = $null
        foreach ($line in Get-Content -LiteralPath (Join-Path $env:USERPROFILE ".wslconfig")) {
            $trimmed = ($line -split "[#;]", 2)[0].Trim()
            if ($trimmed -match "^\[([^\]]+)\]$") {
                $section = $Matches[1].ToLowerInvariant()
            } elseif ($section -eq "wsl2" -and $trimmed -match "^maxCrashDumpCount\s*=\s*(-?\d+)\s*$") {
                $dumpCount = [int]$Matches[1]
            }
        }
        if ($null -eq $dumpCount -or $dumpCount -ge 0) {
            $problems.Add("Set [wsl2] maxCrashDumpCount=-1, then restart WSL.")
        }
    } catch {
        $problems.Add("Cannot verify WSL crash-dump configuration.")
    }
    return @{
        protected = ($problems.Count -eq 0)
        problems = @($problems.ToArray())
        updated_at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds() / 1000.0
    }
}

if (-not $Watch) {
    Get-Protection | ConvertTo-Json -Compress
    exit
}
if (-not $Distribution -or -not $ProjectRoot -or -not $LinuxUser) {
    throw "Watch mode requires the WSL distribution, project directory, and Linux user."
}
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
public static class HushscriptGuard {
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint flags);
    public static Task<string> WaitForClose() {
        return Task.Run(() => Console.In.ReadLine());
    }
}
"@
$held = $false
try {
    $held = [HushscriptGuard]::SetThreadExecutionState([uint32]2147483649) -ne 0
    if (-not $held) { throw "Could not prevent Windows idle sleep." }
    $closed = [HushscriptGuard]::WaitForClose()
    while (-not $closed.IsCompleted) {
        $state = Get-Protection
        $state | ConvertTo-Json -Compress
        [Console]::Out.Flush()
        if (-not $state.protected) { break }
        Start-Sleep -Seconds 2
    }
} finally {
    # Stop Docker before releasing the independently owned power request,
    # including when the Python launcher's stdin pipe disappears unexpectedly.
    do {
        $stopArgs = @("--distribution", $Distribution, "--user", $LinuxUser,
            "--exec", "docker", "--host", "unix:///var/run/docker.sock", "compose",
            "-f", "$ProjectRoot/compose.yaml", "-f", "$ProjectRoot/compose.tls.yaml", "stop", "-t", "3")
        & wsl.exe @stopArgs
        $stopped = $LASTEXITCODE -eq 0
        if (-not $stopped) {
            [Console]::Error.WriteLine("Docker stop failed; retaining the Windows power request.")
            Start-Sleep -Seconds 2
        }
    } while (-not $stopped)
    if ($held) { [void][HushscriptGuard]::SetThreadExecutionState([uint32]2147483648) }
}
