; Instalador de Mapa Sísmico 2.0 (Inno Setup 6)
; Compilar:  ISCC.exe instalador\MapaSismos2.iss   (antes: construir dist\MapaSismos2.exe con PyInstaller)

#define AppName "Mapa Sísmico 2.0 – Gestión de Riesgos"
#define AppVersion "2.0.0"
#define AppExe "MapaSismos2.exe"

[Setup]
AppId={{A4E9C21B-73D4-4F88-9C12-8B4E10A6D542}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Frontino Software Solutions
AppCopyright=© 2026 Lcdo. Denny Lagos · Frontino Software Solutions
AppComments=El poder de las grandes ideas hecho software
VersionInfoCompany=Frontino Software Solutions
VersionInfoCopyright=© 2026 Lcdo. Denny Lagos · Frontino Software Solutions
VersionInfoDescription=Instalador de Mapa Sísmico 2.0 – Gestión de Riesgos
VersionInfoProductName={#AppName}
VersionInfoVersion={#AppVersion}
AppContact=Lcdo. Denny Lagos
DefaultDirName={autopf}\MapaSismos2
DefaultGroupName={#AppName}
OutputDir=..\dist
OutputBaseFilename=MapaSismos2_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
WizardStyle=modern
LicenseFile=licencia.txt
InfoBeforeFile=acerca.txt
SetupIconFile=icono.ico
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Acceso directo en el escritorio"; GroupDescription: "Accesos directos:"
Name: "quiosco"; Description: "Acceso directo en modo quiosco (pantalla completa, para TV)"; GroupDescription: "Accesos directos:"
Name: "inicio"; Description: "Iniciar automáticamente con Windows"; GroupDescription: "Opciones:"; Flags: unchecked
Name: "inicioquiosco"; Description: "…y abrir en modo quiosco al iniciar"; GroupDescription: "Opciones:"; Flags: unchecked

[Files]
Source: "..\dist\{#AppExe}"; DestDir: "{app}"; Flags: ignoreversion
Source: "icono.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\icono.ico"
Name: "{group}\{#AppName} (quiosco)"; Filename: "{app}\{#AppExe}"; Parameters: "--quiosco"; IconFilename: "{app}\icono.ico"
Name: "{group}\Desinstalar"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\icono.ico"; Tasks: escritorio
Name: "{autodesktop}\{#AppName} (quiosco)"; Filename: "{app}\{#AppExe}"; Parameters: "--quiosco"; IconFilename: "{app}\icono.ico"; Tasks: quiosco
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; IconFilename: "{app}\icono.ico"; Tasks: inicio and not inicioquiosco
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExe}"; Parameters: "--quiosco"; IconFilename: "{app}\icono.ico"; Tasks: inicioquiosco

[Run]
Filename: "ie4uinit.exe"; Parameters: "-show"; Flags: runhidden
Filename: "{app}\{#AppExe}"; Description: "Abrir el mapa ahora"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "CerrarMapa2"
