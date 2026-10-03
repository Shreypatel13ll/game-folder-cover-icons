[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('status', 'install', 'remove', 'remove-current')]
    [string]$Action,
    [string]$ExePath
)

$ErrorActionPreference = 'Stop'
$taskName = 'Auto Game Folder Icons'
$newMarker = 'GameFolderIcons.Manager.v1'
$oldMarker = 'Codex.GameFolderIcons.v1'
$task = Get-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
$state = 'none'
$oldRoot = $null
if ($task) {
    if ($task.Description -like "$newMarker*") {
        $state = 'current'
    } elseif ($task.Description -like "$oldMarker*") {
        $state = 'legacy'
        $match = [regex]::Match($task.Description, '\| Root=(.*?) \|')
        if ($match.Success) { $oldRoot = $match.Groups[1].Value }
    } else {
        $state = 'unrelated'
    }
}

if ($Action -eq 'status') {
    [pscustomobject]@{ state = $state; root = $oldRoot } | ConvertTo-Json -Compress
    exit 0
}

if ($state -eq 'unrelated') {
    throw "An unrelated scheduled task named '$taskName' exists. It will not be changed."
}

if ($Action -eq 'remove-current' -and $state -ne 'current') {
    Write-Output 'No manager-owned automatic scan was installed.'
    exit 0
}

if ($Action -eq 'remove' -or $Action -eq 'remove-current') {
    if ($task) {
        Stop-ScheduledTask -TaskPath '\' -TaskName $taskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskPath '\' -TaskName $taskName -Confirm:$false
    }
    Write-Output 'Automatic scans are off. Existing folder icons were left in place.'
    exit 0
}

if (-not $ExePath -or -not (Test-Path -LiteralPath $ExePath -PathType Leaf)) {
    throw 'Provide the installed manager executable with -ExePath.'
}
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
$actionSpec = New-ScheduledTaskAction -Execute $resolvedExe -Argument '--scheduled' `
    -WorkingDirectory (Split-Path -Parent $resolvedExe)
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 10)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Limited
$description = "$newMarker | Scans configured game libraries every ten minutes"
$newTask = New-ScheduledTask -Action $actionSpec -Trigger $trigger -Settings $settings `
    -Principal $principal -Description $description
Register-ScheduledTask -TaskPath '\' -TaskName $taskName -InputObject $newTask -Force | Out-Null
Start-ScheduledTask -TaskPath '\' -TaskName $taskName
Write-Output 'Automatic scans are on. Watched libraries are checked every ten minutes.'
