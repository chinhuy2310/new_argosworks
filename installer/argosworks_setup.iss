; ==============================================================================
; ARGOS WORKS Enterprise - Inno Setup Script
; Đóng gói bộ cài đặt Setup.exe chuyên nghiệp cho Windows
; ==============================================================================

#define MyAppName "ARGOS WORKS Enterprise"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "ARGOS WORKS"
#define MyAppURL "https://github.com/chinhuy2310/new_argosworks"
#define MyAppExeName "ArgosWorks.exe"

[Setup]
; Thông tin nhận diện ứng dụng
AppId={{E6F7A8B9-1C2D-4E5F-8A9B-0C1D2E3F4A5B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\ArgosWorks
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE

; Đầu ra bộ cài đặt
OutputDir=..\dist
OutputBaseFilename=ArgosWorks-Setup-{#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExeName}

; Nén tối ưu hóa LZMA2 siêu nhỏ gọn
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern

; Quyền hạn: Cho phép cài đặt cấp User hoặc Admin
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce
Name: "startupicon"; Description: "Tự động khởi động cùng Windows"; GroupDescription: "Tự động hóa:"; Flags: unchecked

[Files]
; Sao chép toàn bộ tệp từ bản dựng đã giấu code Nuitka
Source: "..\dist\ArgosWorks-1.0.0-win64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; Khởi tạo .env nếu chưa có và không ghi đè khi nâng cấp
Source: "..\dist\ArgosWorks-1.0.0-win64\.env.example"; DestName: ".env"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Dirs]
Name: "{app}\data"; Permissions: users-full
Name: "{app}\logs"; Permissions: users-full

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
