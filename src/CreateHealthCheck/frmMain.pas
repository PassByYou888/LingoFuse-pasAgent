unit frmMain;

{$ifdef FPC}
  {$mode delphi}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}
{$H+}

interface

uses
  LCLIntf, LCLType, LMessages, Messages, SysUtils, Variants, Classes, Graphics,
  Controls, Forms, Dialogs, StdCtrls, ExtCtrls,
  Z.Core, Z.Json, Z.PascalStrings, frmNewRecord, frmNewRecord_tool_provider_unit, lingofuse_import;

type

  { TMainForm }

  TMainForm = class(TForm)
    btnNew: TButton;
    mmoLog: TMemo;
    sysTimer: TTimer;
    procedure btnNewClick(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
    procedure FormCreate(Sender: TObject);
    procedure sysTimerTimer(Sender: TObject);
  private
    procedure AppendLog(const Msg: string);
  public
    procedure ShowJSON(const JSONStr: string);
  end;

var
  MainForm: TMainForm;

implementation

{$R *.lfm}

procedure Do_Th_Conn;
begin
  LF_SetOptionEx('WaitConnect', 'True');
  LF_ResetPrepare;
  LF_PrepareClientEx(IPC_ENDPOINT, RegisterAPIs());
  if LF_PrepareDone() > 0 then
    RegisterTools();
end;

procedure TMainForm.FormCreate(Sender: TObject);
begin
  TCompute.RunC_NP(Do_Th_Conn);
end;

procedure TMainForm.sysTimerTimer(Sender: TObject);
begin
  while LF_GetStatusCount > 0 do
    mmoLog.Lines.Add(LF_GetStatusEx());
  Z.Core.Check_Soft_Thread_Synchronize(0);
  LF_Sync();
end;

procedure TMainForm.btnNewClick(Sender: TObject);
begin
  NewRecordForm := TNewRecordForm.Create(Self);
  NewRecordForm.Show;
end;

procedure TMainForm.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  LF_Shutdown;
end;

procedure TMainForm.AppendLog(const Msg: string);
begin
  mmoLog.Lines.Add(Format('[%s] %s', [FormatDateTime('hh:nn:ss', Now), Msg]));
end;

procedure TMainForm.ShowJSON(const JSONStr: string);
begin
  AppendLog('生成 JSON:');
  mmoLog.Lines.Add(JSONStr);
  mmoLog.Lines.Add('');
end;

end.
