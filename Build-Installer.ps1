[CmdletBinding()]
param([string]$IsccPath)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$venvPython = Join-Path $PSScriptRoot '.venv-build\Scripts\python.exe'
if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
    $python = $venvPython
} else {
    $pythonOutput = & py -3.9 -c 'import sys; print(sys.executable)'
    if ($LASTEXITCODE -ne 0 -or -not $pythonOutput) {
        throw 'Python 3.9 with the py launcher is required to build.'
    }
    $python = ($pythonOutput | Select-Object -First 1).Trim()
}
& $python -c 'import PIL, PyInstaller, ttkbootstrap'
if ($LASTEXITCODE -ne 0) {
    throw 'Build dependencies are missing. Run: py -3.9 -m pip install -r requirements-build.txt'
}

& $python .\tools\make_app_icon.py .\build\app.ico
if ($LASTEXITCODE -ne 0) { throw 'Could not generate the app icon.' }
& $python -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name GameFolderIconsManager --icon .\build\app.ico .\manager.py
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -LiteralPath .\task.ps1 -Destination .\dist\GameFolderIconsManager\task.ps1 -Force
Copy-Item -LiteralPath .\build\app.ico -Destination .\dist\GameFolderIconsManager\app.ico -Force
Copy-Item -LiteralPath .\third_party_licenses -Destination .\dist\GameFolderIconsManager -Recurse -Force
$smoke = Start-Process -FilePath .\dist\GameFolderIconsManager\GameFolderIconsManager.exe `
    -ArgumentList '--smoke-gui' -Wait -PassThru -WindowStyle Hidden
if ($smoke.ExitCode -ne 0) { throw "Bundled GUI failed its smoke test (exit $($smoke.ExitCode))." }

if (-not $IsccPath) {
    $found = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($found) { $IsccPath = $found.Source }
}
if (-not $IsccPath) {
    foreach ($candidate in @(
        'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 6\ISCC.exe',
        'C:\Program Files\Inno Setup 7\ISCC.exe',
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 7\ISCC.exe')
    )) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { $IsccPath = $candidate; break }
    }
}
if (-not $IsccPath -or -not (Test-Path -LiteralPath $IsccPath -PathType Leaf)) {
    throw 'Inno Setup compiler (ISCC.exe) was not found. Install Inno Setup or pass -IsccPath.'
}
& $IsccPath .\packaging\GameFolderIcons.iss
if ($LASTEXITCODE -ne 0) { throw 'Inno Setup compilation failed.' }
Write-Output "Installer: $(Join-Path $PSScriptRoot 'release\GameFolderIcons-Setup-1.0.0.exe')"
