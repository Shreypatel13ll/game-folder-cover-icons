[CmdletBinding()]
param(
    [string]$GamesRoot,
    [switch]$RestoreIcons
)

$ErrorActionPreference = 'Stop'
$taskName = 'Auto Game Folder Icons'
$marker = 'Codex.GameFolderIcons.v1'
$task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
if ($task -and $task.Description -notlike "$marker*") {
    throw "Refusing to remove an unrelated task named '$taskName'."
}

if (-not $GamesRoot -and $task) {
    $match = [regex]::Match($task.Description, '\| Root=(.*?) \|')
    if ($match.Success) { $GamesRoot = $match.Groups[1].Value }
}

if ($task) {
    Stop-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false
    Write-Output "Removed scheduled task '$taskName'."
} else {
    Write-Output 'Scheduled task is already absent.'
}

if ($RestoreIcons) {
    if (-not $GamesRoot -or -not (Test-Path -LiteralPath $GamesRoot -PathType Container)) {
        throw 'To restore managed icons, provide an existing directory with -GamesRoot.'
    }
    $launcher = Get-Command py -ErrorAction Stop
    $pythonOutput = & $launcher.Source -3 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0 -or -not $pythonOutput) {
        throw 'Could not find a usable Python 3 installation.'
    }
    $python = ($pythonOutput | Select-Object -First 1).Trim()
    $script = Join-Path $PSScriptRoot 'auto_folder_icons.py'
    & $python $script --root (Resolve-Path -LiteralPath $GamesRoot).Path --restore
    if ($LASTEXITCODE -ne 0) {
        throw 'Some managed icons could not be restored. Review the automation log for conflicts.'
    }
    Write-Output 'Restored unchanged icons created by this tool.'
} else {
    Write-Output 'Existing folder icons remain in place.'
}

Write-Output 'Cached artwork and state remain in %LOCALAPPDATA%\GameFolderIcons for inspection.'
