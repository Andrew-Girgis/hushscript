# Parser and contract checks; these do not exercise Windows kernel APIs.
$ErrorActionPreference = "Stop"
$tokens = $null
$parseErrors = $null
$path = Join-Path $PSScriptRoot "windows_guard.ps1"
$ast = [System.Management.Automation.Language.Parser]::ParseFile($path, [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
$function = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and
        $node.Name -eq "Get-Protection"
}, $true)
. ([scriptblock]::Create($function.Extent.Text))

$script:Flags = @{ HibernateEnabled = 0; CrashDumpEnabled = 0; FullLiveReportsMax = 0 }
$script:Config = @("[wsl2]", "maxCrashDumpCount=-1")
$script:PageFiles = @()
$script:CimFails = $false
$env:USERPROFILE = "/synthetic"
function Read-Dword([string]$Path, [string]$Name) { return $script:Flags[$Name] }
function Get-Content { return $script:Config }
function Get-CimInstance {
    if ($script:CimFails) { throw "Simulated unavailable WMI" }
    return $script:PageFiles
}
if (-not (Get-Protection).protected) { throw "Known disabled settings were rejected." }
foreach ($name in @("HibernateEnabled", "CrashDumpEnabled", "FullLiveReportsMax")) {
    $script:Flags[$name] = 1
    if ((Get-Protection).protected) { throw "Enabled protection hazard was accepted: $name" }
    $script:Flags.Remove($name)
    if ((Get-Protection).protected) { throw "Unknown setting was accepted: $name" }
    $script:Flags[$name] = 0
}
foreach ($value in @(0, 10)) {
    $script:Config = @("[wsl2]", "maxCrashDumpCount=$value")
    if ((Get-Protection).protected) { throw "WSL dump collection was accepted: $value" }
}
$script:Config = @("[wsl2]", "maxCrashDumpCount=-1")
$script:PageFiles = @([pscustomobject]@{ Name = "synthetic"; CurrentUsage = 0 })
if ((Get-Protection).protected) { throw "An active but unused page file was accepted." }
$script:PageFiles = @()
$script:CimFails = $true
if ((Get-Protection).protected) { throw "Unavailable WMI was accepted." }
$csharp = $ast.Find({
    param($node)
    $node -is [System.Management.Automation.Language.StringConstantExpressionAst] -and
        $node.Value.Contains("class HushscriptGuard")
}, $true)
Add-Type -TypeDefinition $csharp.Value
Write-Output "PowerShell parser, fail-closed probes, and power-helper compilation passed."
