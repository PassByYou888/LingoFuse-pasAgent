program HealthCheck;

{$MODE Delphi}

uses
  Forms, Interfaces,
  frmMain in 'frmMain.pas' {MainForm},
  frmNewRecord in 'frmNewRecord.pas', lingofuse_import, lingofuse_helper, frmNewRecord_tool_provider_unit {NewRecordForm};

{$R *.res}

begin
  Application.Initialize;
  Application.MainFormOnTaskbar := True;
  Application.CreateForm(TMainForm, MainForm);
  Application.Run;
end.