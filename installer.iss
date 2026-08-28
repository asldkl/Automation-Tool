; 三角洲行动自动化工具 安装脚本
; Inno Setup 6 编译
; 更新日期: 2026-08-28

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName=三角洲行动自动化工具
AppVersion=6.08.22
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
UninstallDisplayName=三角洲行动自动化工具
UninstallDisplayIcon={app}\三角洲自动工具.exe
VersionInfoVersion=6.08.22.0
VersionInfoDescription=三角洲行动自动化工具安装程序

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\三角洲自动工具.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "interception.dll"; DestDir: "{app}"; Flags: ignoreversion
Source: "interception.sys"; DestDir: "{app}"; Flags: ignoreversion
Source: "install_interception.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "使用说明书.txt"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "Interception安装使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"
Name: "startupicon"; Description: "开机自动启动"; GroupDescription: "其他选项:"
Name: "install_driver"; Description: "安装 Interception 键盘驱动（WeGame 直接登录需要，需重启）"; GroupDescription: "其他选项:"; Flags: checkedonce

[Icons]
Name: "{group}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"
Name: "{group}\卸载三角洲行动自动化工具"; Filename: "{uninstallexe}"
Name: "{autodesktop}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"; Tasks: desktopicon
Name: "{userstartup}\三角洲行动自动化工具"; Filename: "{app}\三角洲自动工具.exe"; Tasks: startupicon

[Run]
Filename: "{app}\三角洲自动工具.exe"; Description: "启动程序"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "sc.exe"; Parameters: "stop keyboard"; Flags: runhidden
Filename: "sc.exe"; Parameters: "delete keyboard"; Flags: runhidden
Filename: "sc.exe"; Parameters: "stop interception"; Flags: runhidden
Filename: "sc.exe"; Parameters: "delete interception"; Flags: runhidden

[UninstallDelete]
Type: files; Name: "{app}\interception.sys"
Type: files; Name: "{app}\install_interception.bat"
Type: filesandordirs; Name: "{app}"

[Code]
function IsInterceptionInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := False;
  if Exec('sc.exe', 'query keyboard', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if ResultCode = 0 then
      Result := True;
  end;
  if not Result then
  begin
    if Exec('sc.exe', 'query interception', '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
    begin
      if ResultCode = 0 then
        Result := True;
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    if IsTaskSelected('install_driver') and (not IsInterceptionInstalled) then
    begin
      if Exec(ExpandConstant('{app}\install_interception.bat'), '',
              '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then
      begin
        if MsgBox('Interception driver installed.' + #13#10 +
                  'Reboot now to ensure the driver is loaded?', mbConfirmation, MB_YESNO) = IDYES then
        begin
          Exec('shutdown.exe', '/r /t 5', '', SW_HIDE, ewNoWait, ResultCode);
        end;
      end;
    end;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
  begin
    if IsInterceptionInstalled then
    begin
      Exec('sc.exe', 'stop keyboard', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Exec('sc.exe', 'delete keyboard', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      DeleteFile(ExpandConstant('{sys}\drivers\keyboard.sys'));
      Exec('sc.exe', 'stop interception', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      Exec('sc.exe', 'delete interception', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
      DeleteFile(ExpandConstant('{sys}\drivers\interception.sys'));
    end;
  end;
end;
