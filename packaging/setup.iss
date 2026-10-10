; Inno Setup 脚本 — 由 scripts/build-installer.ps1 调用
; 前置：已生成 packaging\payload\（含 runtime、app、scripts、Start.bat）

#define MyAppName "买入时机"
#define MyAppVersion "0.1.0"
#define MyAppPublisher "StockDecision"
#define MyAppURL "http://127.0.0.1:8765"
#define MyAppExeName "Start.bat"

[Setup]
AppId={{A8F3C2E1-7B4D-4E9A-9C1F-2D6E8B0A5F31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=买入时机-Setup-{#MyAppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\Start.bat
InfoBeforeFile=info-before.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加选项:"; Flags: unchecked

[Files]
Source: "payload\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 {#MyAppName}"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
; 安装目录内残留；用户数据在 %LOCALAPPDATA%\买入时机\ 默认保留，见说明文档
Type: filesandordirs; Name: "{app}\runtime\Lib\site-packages\__pycache__"
