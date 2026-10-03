#define AppName "Game Folder Icons Manager"
#define AppVersion "1.0.0"
#define AppExe "GameFolderIconsManager.exe"

[Setup]
AppId={{DFA19006-ED01-46A3-B4B2-A8D24B1684B1}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Shrey
AppPublisherURL=https://github.com/Shreypatel13ll/game-folder-cover-icons
DefaultDirName={localappdata}\Programs\GameFolderIconsManager
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=..\release
OutputBaseFilename=GameFolderIcons-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\build\app.ico
UninstallDisplayIcon={app}\{#AppExe}
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\GameFolderIconsManager\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "--uninstall-task"; Flags: runhidden; RunOnceId: "RemoveAutoScanTask"
