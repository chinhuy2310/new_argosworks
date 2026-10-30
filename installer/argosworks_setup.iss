; ==============================================================================
; ARGOS WORKS Server - Inno Setup Script
; Đóng gói bộ cài đặt Setup.exe chuyên nghiệp cho Windows x64
; Tích hợp sẵn PostgreSQL 16 Portable + Caddy HTTPS Reverse Proxy
; ==============================================================================

#define MyAppName "ARGOS WORKS Server"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ARGOS WORKS"
#define MyAppExeName "ArgosWorks.exe"

#ifndef BuildType
#define BuildType "standard"
#endif

#if BuildType == "ai"
  #define OutputName "ArgosWorks-Setup-AI-" + MyAppVersion
  #define SourceFolder "..\dist\ArgosWorks-" + MyAppVersion + "-win64-ai\*"
  #define SourceEnv "..\dist\ArgosWorks-" + MyAppVersion + "-win64-ai\.env.example"
#else
  #define OutputName "ArgosWorks-Setup-" + MyAppVersion
  #define SourceFolder "..\dist\ArgosWorks-" + MyAppVersion + "-win64\*"
  #define SourceEnv "..\dist\ArgosWorks-" + MyAppVersion + "-win64\.env.example"
#endif

[Setup]
; Thông tin nhận diện ứng dụng
AppId={{E6F7A8B9-1C2D-4E5F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\ArgosWorks
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE

; Biểu tượng ứng dụng chính thức
SetupIconFile=app.ico
UninstallDisplayIcon={app}\app.ico

; Native x64 Architecture
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible

; Đầu ra bộ cài đặt
OutputDir=..\dist
OutputBaseFilename={#OutputName}

; Nén tối ưu hóa LZMA2 siêu nhỏ gọn
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Quyền hạn: Cho phép cài đặt cấp User hoặc Admin
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=no
RestartApplications=no

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM ArgosWorks.exe /IM postgres.exe /IM caddy.exe /IM ollama.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
  Result := '';
end;

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startupicon"; Description: "Start ARGOS WORKS automatically on Windows startup"; GroupDescription: "Startup options:"; Flags: unchecked

[Dirs]
Name: "{app}"; Permissions: users-full
Name: "{app}\data"; Permissions: users-full
Name: "{app}\data\postgres"; Permissions: users-full
Name: "{app}\data\caddy"; Permissions: users-full
Name: "{app}\logs"; Permissions: users-full

[Files]
; Biểu tượng ứng dụng
Source: "app.ico"; DestDir: "{app}"; Flags: ignoreversion; Permissions: users-full
; Sao chép toàn bộ tệp từ bản dựng đã giấu code Nuitka (bao gồm pgsql và caddy)
Source: "{#SourceFolder}"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Permissions: users-full
; Khởi tạo .env nếu chưa có và không ghi đè khi nâng cấp
Source: "{#SourceEnv}"; DestName: ".env"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\app.ico"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
