# Game Folder Cover Icons

Automatically give Windows game folders icons made from each game's cover art.

Add one or more directories containing a folder per game. The optional automatic scan checks for new games every ten minutes, identifies a game from local metadata, gets artwork when available, makes a multi-size `.ico`, and asks Windows Explorer to display it for that folder.

This project customizes **folders**, not desktop shortcuts or the artwork inside a launcher.

## Install the Windows app

Download `GameFolderIcons-Setup-1.0.0.exe` from [GitHub Releases](https://github.com/Shreypatel13ll/game-folder-cover-icons/releases). Run the installer, then open **Game Folder Icons Manager** from the Start menu. This per-user installation does not require administrator access or a separate Python installation.

In the light-themed manager:

1. Click **Add library…** and select a directory containing your game folders.
2. Click **Scan now** to process it immediately.
3. Click **Turn on** to check watched libraries automatically every ten minutes. You can turn this off at any time.

The manager also lists each game folder. Select a game to choose your own cover image, exclude or include it in future scans, restore an unchanged icon created by this tool, or open its folder. If you replace an existing custom icon, its previous setting is saved for restoration. To replace an icon already managed by this tool, restore it first. **Stop watching** removes a library from the watch list; it does not remove any icons.

If you used an older version of this project, the manager imports its watched directory. Click **Switch to manager** to replace the old scheduled task with the new one; your existing icons and restoration history stay intact.

The GUI closes completely when you exit it. Automatic scans are short-lived scheduled processes, not a resident tray app. They skip folders with working icons, only save state when it changes (or once an hour), and process at most two new candidates per library per automatic run. A manual **Scan now** is not capped.

The installer is currently unsigned, so Windows may show a publisher warning. The source and build recipe are in this repository so you can inspect what the EXE contains.

## Requirements for running from source

- Windows 10 or 11
- Python 3.9 or newer with the Windows `py` launcher
- [Pillow](https://pypi.org/project/Pillow/) (see `requirements.txt`)
- [ttkbootstrap](https://www.ttkbootstrap.org/) for the manager GUI
- An internet connection for Steam or GOG artwork; local artwork works offline

No API key or administrator access is needed. The scheduled task runs under the Windows account that installs it.

## Install the Python scanner without the GUI

Download and extract this repository, then open PowerShell in the extracted directory. Replace `D:\Games` with the directory that contains your game folders:

```powershell
py -3 -m pip install --user -r .\requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -GamesRoot 'D:\Games'
```

This source-only installer checks the Python environment, generates a test icon, copies the tool to `%LOCALAPPDATA%\GameFolderIcons`, and registers the **Auto Game Folder Icons** scheduled task. It starts the task immediately and repeats a low-impact scan every ten minutes while you are signed in. The GUI installer above is recommended for managing multiple libraries.

To check prerequisites without changing the scheduled task:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install.ps1 -GamesRoot 'D:\Games' -ValidateOnly
```

## What happens during a scan

Only immediate child folders of the selected directory are candidates. The tool skips hidden folders, junctions, symbolic links, folders with `.no-folder-icon`, and folders that already have a working custom icon. It waits at least two minutes after a folder is created and requires evidence such as a Steam app ID, Steam manifest, GOG metadata, Unity product name, or plausible game executable.

Artwork is chosen in this order:

1. A GOG cover when the folder has a matching GOG game ID.
2. A Steam library cover when the Steam app ID or game title can be matched confidently.
3. A local cover image or game `.ico` found in the folder.
4. A generated title tile if there is no reliable store match or local artwork.

The square design keeps the full cover visible against a blurred background. The resulting `.ico` contains 16, 20, 24, 32, 40, 48, 64, 128, and 256 pixel images for different Explorer views.

For each managed folder, the tool adds a hidden `.folder-icon-auto-*.ico` file and updates `desktop.ini`. It sets the folder's Windows Read-only *customization flag*, which does not prevent you or games from writing files into the folder. Game executables, saves, and assets are not edited.

## Run or inspect the source-only scanner

Run a scan now:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Now.ps1 -GamesRoot 'D:\Games'
```

Retry a folder immediately after a temporary error:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Run-Now.ps1 -GamesRoot 'D:\Games' -ForceRetry
```

View the task and recent activity:

```powershell
Get-ScheduledTaskInfo -TaskName 'Auto Game Folder Icons'
Get-Content "$env:LOCALAPPDATA\GameFolderIcons\automation.log" -Tail 30
```

The configuration, log, cached artwork, and `state.json` live in `%LOCALAPPDATA%\GameFolderIcons`. None of these personal files belongs in a public Git repository.

## Exclude a folder

Create an empty file named `.no-folder-icon` inside the game folder before its next scan. For example:

```powershell
New-Item -ItemType File -Path 'D:\Games\My Game\.no-folder-icon'
```

If a game is matched incorrectly, you can set its folder icon manually through **Properties → Customize → Change Icon**. Once the folder has a working icon, the scanner leaves it alone.

## Uninstall

For the Windows app, use **Settings → Apps → Installed apps → Game Folder Icons Manager → Uninstall**. This removes the manager's scheduled task and app files but keeps your folder icons, configuration, history, logs, and cache. If you never switched an older scanner to the manager, uninstall leaves that older task alone. Reinstalling can reuse the saved data.

For the source-only scanner, use these commands:

Stop automatic scans and leave existing icons in place:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall.ps1
```

Stop automatic scans and restore only unchanged icons that this automation added:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Uninstall.ps1 -GamesRoot 'D:\Games' -RestoreIcons
```

Restoration verifies the managed icon and `desktop.ini` before changing them. If someone edited either file after the tool applied it, that folder is skipped and the conflict is logged. Icons that existed before the automation was installed are outside its restore history. Uninstall keeps the cache, logs, and history available for inspection.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| A new folder still has the default icon | Wait two minutes for the folder to settle, then run `Run-Now.ps1`. Check that it contains a game executable or supported metadata. |
| The icon was created but Explorer still shows the old one | Press **F5** in Explorer, or close and reopen that Explorer window. |
| No art is downloaded | Check internet access and `%LOCALAPPDATA%\GameFolderIcons\automation.log`. Steam and GOG artwork endpoints may change. |
| `py` is not recognized | Install Python from [python.org](https://www.python.org/downloads/windows/) with the Windows launcher, then reopen PowerShell. |
| `No module named PIL` | Run `py -3 -m pip install --user -r .\requirements.txt`. |
| You want to choose a specific image | Set the folder icon manually; the automatic scan respects a working custom icon. |

## Privacy and limitations

The code runs locally. It sends game title searches and known store IDs to Steam or GOG over HTTPS to find artwork; it does not upload game files, saves, or the local folder tree. Cover images remain the property of their respective owners and are downloaded for personal icon customization. No third-party artwork is bundled in this repository.

Game detection is heuristic. Stores can omit games or return several similarly named releases. The scanner favors a confident match; otherwise it uses local art or a title tile. Windows Explorer reads `desktop.ini`, but other file managers might ignore it.

## Development

The scanner uses the Python standard library plus Pillow. The GUI adds ttkbootstrap. Run the checks with:

```powershell
py -3 -m unittest discover -s tests -v
py -3 -m py_compile .\auto_folder_icons.py .\manager_core.py .\manager.py
```

To build the standalone installer on Windows, install Python 3.9 and Inno Setup 6 or 7, then run:

```powershell
py -3.9 -m venv .venv-build
.\.venv-build\Scripts\python.exe -m pip install -r .\requirements-build.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\Build-Installer.ps1
```

The build writes `release\GameFolderIcons-Setup-1.0.0.exe`. PyInstaller bundles Python and app dependencies; Inno Setup adds the per-user installer, shortcuts, and uninstaller. The build files are ignored by Git.

Issues and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for the review checklist.

Released under the [MIT License](LICENSE). This project is independent of Valve, GOG, and game publishers.
