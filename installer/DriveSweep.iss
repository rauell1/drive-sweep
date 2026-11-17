; Inno Setup script for DriveSweep Windows Installer
#define MyAppName "DriveSweep"
#define MyAppVersion "0.7.3"
#define MyAppPublisher "Roy Otieno"
#define MyAppURL "https://github.com/rauell1/drive-sweep"
#define MyAppExeName "DriveSweep.exe"
#define MyTaskName "DriveSweepLowDiskReminder"

[Setup]
AppId={{7E8F3E52-3F2A-4D28-9E93-B9F5C2C4F612}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
AppCopyright=Copyright (c) 2026 {#MyAppPublisher}. MIT License.
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
; 64-bit app: install into "Program Files", not "Program Files (x86)"
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
InfoBeforeFile=NOTICE.txt
PrivilegesRequired=admin
OutputDir=..\dist\setup
OutputBaseFilename=DriveSweep-Setup-{#MyAppVersion}
SetupIconFile=..\assets\drivesweep.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
; Stable name in Installed apps (no version in it) so winget and upgrades match it reliably
UninstallDisplayName={#MyAppName}
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
Source: "..\THIRD_PARTY_NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
; Start the app as the signed-in user (standard rights), not with Setup's Administrator token.
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent runasoriginaluser
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent runasoriginaluser; Check: IsAutoStartRequested

[UninstallRun]
; Remove the optional low-disk reminder so no scheduled task is left pointing at a deleted program.
Filename: "{sys}\schtasks.exe"; Parameters: "/Delete /TN ""{#MyTaskName}"" /F"; Flags: runhidden; RunOnceId: "DeleteReminderTask"

[UninstallDelete]
; Administrator-only working folder (verified update installers, diskpart scripts)
Type: filesandordirs; Name: "{commonappdata}\DriveSweep"

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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: string;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\DriveSweep');
    if DirExists(DataDir) and (not UninstallSilent()) then
    begin
      if MsgBox('Also delete your DriveSweep settings, Always Keep list, cleanup history and diagnostics logs?' + #13#10 + #13#10 +
                DataDir, mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
