; Inno Setup script for DriveSweep Windows Installer
#define MyAppName "DriveSweep"
#define MyAppVersion "0.6.0"
#define MyAppPublisher "DriveSweep"
#define MyAppExeName "DriveSweep.exe"

[Setup]
AppId={{7E8F3E52-3F2A-4D28-9E93-B9F5C2C4F612}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
PrivilegesRequired=admin
OutputDir=..\dist
OutputBaseFilename=DriveSweep-Setup-{#MyAppVersion}
SetupIconFile=..\assets\drivesweep.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\DriveSweep-win64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runascurrentuser
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent; Check: IsAutoStartRequested

[Code]
function ClearSetupEnvVar(lpName: string; lpValue: LongWord): BOOL;
  external 'SetEnvironmentVariableW@kernel32.dll stdcall';

function InitializeSetup(): Boolean;
begin
  ClearSetupEnvVar('_PYI_PARENT_PROCESS_LEVEL', 0);
  ClearSetupEnvVar('_PYI_ARCHIVE_FILE', 0);
  ClearSetupEnvVar('_PYI_APPLICATION_HOME_DIR', 0);
  ClearSetupEnvVar('_PYI_SPLASH_IPC', 0);
  ClearSetupEnvVar('_MEIPASS2', 0);
  Result := True;
end;

function IsAutoStartRequested(): Boolean;
begin
  Result := ExpandConstant('{param:autostart|0}') = '1';
end;
