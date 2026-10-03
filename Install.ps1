[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GamesRoot,
    [switch]$ValidateOnly
)

$ErrorActionPreference = 'Stop'
$taskName = 'Auto Game Folder Icons'
$marker = 'Codex.GameFolderIcons.v1'
$installDir = Join-Path $env:LOCALAPPDATA 'GameFolderIcons'

if (-not (Test-Path -LiteralPath $GamesRoot -PathType Container)) {
    throw "Games directory does not exist: $GamesRoot"
}
$resolvedRoot = (Resolve-Path -LiteralPath $GamesRoot).Path

$launcher = Get-Command py -ErrorAction SilentlyContinue
if (-not $launcher) {
    throw 'Python 3.9 or newer is required. Install Python from python.org and enable the py launcher.'
}
$pythonOutput = & $launcher.Source -3 -c 'import sys; print(sys.executable)' 2>$null
if ($LASTEXITCODE -ne 0 -or -not $pythonOutput) {
    throw 'Could not find a usable Python 3 installation.'
}
$python = ($pythonOutput | Select-Object -First 1).Trim()
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw 'Could not find a usable Python 3 installation.'
}
$pythonw = Join-Path (Split-Path -Parent $python) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw "The background Python executable is missing: $pythonw"
}
& $python -c 'import sys; import PIL; assert sys.version_info >= (3, 9)'
if ($LASTEXITCODE -ne 0) {
    throw 'Python 3.9+ and Pillow are required. Run: py -3 -m pip install -r .\requirements.txt'
}

$sourceScript = Join-Path $PSScriptRoot 'auto_folder_icons.py'
if (-not (Test-Path -LiteralPath $sourceScript -PathType Leaf)) {
    throw "Missing project script: $sourceScript"
}
& $python $sourceScript --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Icon generation self-test failed with exit code $LASTEXITCODE"
}

$existing = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing -and $existing.Description -notlike "$marker*") {
    throw "A different scheduled task named '$taskName' already exists."
}

if ($ValidateOnly) {
    Write-Output "Validation passed for $resolvedRoot using $python"
    exit 0
}

New-Item -ItemType Directory -Path $installDir -Force | Out-Null
foreach ($file in @('auto_folder_icons.py', 'Run-Now.ps1', 'Uninstall.ps1')) {
    $source = Join-Path $PSScriptRoot $file
    if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
        throw "Missing project file: $source"
    }
    Copy-Item -LiteralPath $source -Destination (Join-Path $installDir $file) -Force
}

$installedScript = Join-Path $installDir 'auto_folder_icons.py'
$arguments = ('"{0}" --root "{1}" --scan' -f $installedScript, $resolvedRoot)
$action = New-ScheduledTaskAction -Execute $pythonw -Argument $arguments -WorkingDirectory $installDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$description = "$marker | Root=$resolvedRoot | Adds cover art icons to new game folders"
$task = New-ScheduledTask -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $description
Register-ScheduledTask -TaskPath '\' -TaskName $taskName -InputObject $task -Force | Out-Null
Start-ScheduledTask -TaskPath '\' -TaskName $taskName

Write-Output "Installed '$taskName' for $resolvedRoot. It scans every five minutes while you are signed in."
Write-Output "Log: $(Join-Path $installDir 'automation.log')"
