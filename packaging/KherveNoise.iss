; Inno Setup script for KherveNoise — per-user install, no admin rights.
;
; Not run by hand: packaging/build_installer.py freezes the app and then calls
;
;   ISCC.exe /DAPP_VERSION=0.1.N /DSRC_DIR=...\dist\KherveNoise /DOUT_DIR=...\dist
;            /DICON_FILE=...\build\KherveNoise.ico KherveNoise.iss
;
; Installs to %LOCALAPPDATA%\Programs\KherveNoise, so there is no elevation
; prompt; associates .knoise projects, and lists KherveNoise under "Open
; with" for the spectrum file types it reads.
;
; Copyright (C) 2026 Gwilherm Kerherve. GPL-3.0.

#ifndef APP_VERSION
  #define APP_VERSION "0.1.0"
#endif
#ifndef SRC_DIR
  #define SRC_DIR "..\dist\KherveNoise"
#endif
#ifndef OUT_DIR
  #define OUT_DIR "..\dist"
#endif
#ifndef ICON_FILE
  #define ICON_FILE "..\build\KherveNoise.ico"
#endif

#define AppName "KherveNoise"
#define AppPublisher "Gwilherm Kerherve"
#define AppURL "https://khervetools.com/tools/khervenoise"
#define AppExe "KherveNoise.exe"

[Setup]
AppId={{21469395-177B-468F-8D91-085902F84F30}
AppName={#AppName}
AppVersion={#APP_VERSION}
AppVerName={#AppName} {#APP_VERSION}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
VersionInfoVersion={#APP_VERSION}
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
LicenseFile=..\LICENSE
SetupIconFile={#ICON_FILE}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir={#OUT_DIR}
OutputBaseFilename={#AppName}-Setup-{#APP_VERSION}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
MinVersion=10.0

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[InstallDelete]
; Inno never removes a file a newer build dropped, and the Python packages
; (numpy, PySide6, matplotlib) are ABI-bound to each other: an upgrade must
; not leave the old _internal tree beside the new one. It is all build
; output; nothing the user made lives under {app}.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "{#SRC_DIR}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Per-user (HKCU) to match the per-user install.
Root: HKCU; Subkey: "Software\Classes\.knoise"; ValueType: string; ValueName: ""; ValueData: "KherveNoise.Project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\KherveNoise.Project"; ValueType: string; ValueName: ""; ValueData: "KherveNoise project"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\KherveNoise.Project\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"
Root: HKCU; Subkey: "Software\Classes\KherveNoise.Project\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
; "Open with" for the instrument and plain-data files KherveNoise imports.
; Offered, not owned: those files belong to the instruments and to KherveFitting.
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "{#AppName}"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".knoise"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".vms"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".xy"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".asc"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".spe"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".avg"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".kal"; ValueData: ""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
