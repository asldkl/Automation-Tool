[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName=三角洲行动自动化工具
AppVersion=1.1.0
AppPublisher=三角洲自动化工具
AppPublisherURL=
DefaultDirName={autopf}\三角洲行动自动化工具
DefaultGroupName=三角洲行动自动化工具
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=三角洲行动自动化工具_安装程序
SetupIconFile=picture\icon\icon.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\三角洲自动工具.exe
VersionInfoVersion=1.1.0.0
VersionInfoDescription=三角洲行动自动化工具安装程序

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "startupicon"; Description: "开机自动启动"; GroupDescription: "其他选项:"

[Files]
Source: "dist_nuitka_standalone\main.dist\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"
Name: "{group}\卸载三角洲行动自动化工具"; Filename: "{uninstallexe}"
Name: "{autodesktop}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"; Tasks: desktopicon
Name: "{userstartup}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"; Tasks: startupicon

[Run]
Filename: "{app}\三角洲自动工具.exe"; Description: "启动三角洲行动自动化工具"; Flags: nowait postinstall skipifsilent
