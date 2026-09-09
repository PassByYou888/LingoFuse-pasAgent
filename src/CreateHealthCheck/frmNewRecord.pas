unit frmNewRecord;

{$ifdef FPC}
  {$mode delphi}
  {$MODESWITCH NestedProcVars}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}
{$H+}

interface

uses
  LCLIntf, LCLType, LMessages, Messages, SysUtils, Variants, Classes, Graphics,
  Controls, Forms, Dialogs, StdCtrls, ComCtrls, ExtCtrls,
  Z.Core, Z.Json, Z.PascalStrings, Z.UPascalStrings, Z.UnicodeMixedLib;

type

  { TNewRecordForm }

  TNewRecordForm = class(TForm)
    edtName: TEdit;
    edtAge: TEdit;
    cbGender: TComboBox;
    edtID: TEdit;
    edtPhone: TEdit;
    edtAddress: TEdit;
    dtpBirth: TEdit;
    edtTemp: TEdit;
    edtSBP: TEdit;
    edtDBP: TEdit;
    edtHeartRate: TEdit;
    memSymptoms: TMemo;
    memHistory: TMemo;
    edtAllergy: TEdit;
    edtContact: TEdit;
    memRemark: TMemo;
    btnOK: TButton;
    btnCancel: TButton;
    lblName: TLabel;
    lblAge: TLabel;
    lblGender: TLabel;
    lblBirth: TLabel;
    lblID: TLabel;
    lblPhone: TLabel;
    lblAddress: TLabel;
    lblTemp: TLabel;
    lblSBP: TLabel;
    lblDBP: TLabel;
    lblHeartRate: TLabel;
    lblSymptoms: TLabel;
    lblHistory: TLabel;
    lblAllergy: TLabel;
    lblContact: TLabel;
    lblRemark: TLabel;
    DelayCloseTimer: TTimer;
    procedure btnCancelClick(Sender: TObject);
    procedure btnOKClick(Sender: TObject);
    procedure DelayCloseTimerTimer(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
  private
    function ValidateInputs: boolean;
    function BuildJSON: string;
  public
    { Public declarations }
  end;

var
  NewRecordForm: TNewRecordForm = nil;

  {
    填充新建健康记录表单的所有字段，并返回姓名,如果返回空就是没有执行NewRecord.
    AName:姓名
    AAge:年龄
    AGender:性别（"男" / "女"）
    ABirth:出生日期（字符串形式，如 "1990-01-01"）
    AID:身份证号
    APhone:电话
    AAddress:地址
    ATemp:体温（字符串，如 "36.5"）
    ASBP:收缩压（字符串）
    ADBP:舒张压（字符串）
    AHeartRate:心率（字符串）
    ASymptoms:症状（多行文本）
    AHistory:既往病史（多行文本）
    AAllergy:过敏史
    AContact:紧急联系人
    ARemark:备注（多行文本）
  }
function FillRecord(const AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate,
  ASymptoms, AHistory, AAllergy, AContact, ARemark: string): string;

{
  打开健康记录输入表单，返回1表示成功,返回0表示打开无效.
}
function NewRecord(): integer;

{
  保存健康记录表单为Json，并返回json数据。
}
function SaveRecord(): string;

implementation

uses frmMain;

  {$R *.lfm}

function FillRecord(const AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate,
  ASymptoms, AHistory, AAllergy, AContact, ARemark: string): string;

  procedure do_sync();
  var
    idx: integer;
  begin
    if NewRecordForm = nil then NewRecord();
    with NewRecordForm do
    begin
      edtName.Text := AName;
      edtAge.Text := AAge;

      // 性别：根据传入字符串尝试匹配下拉列表
      idx := cbGender.Items.IndexOf(AGender);
      if idx >= 0 then
        cbGender.ItemIndex := idx
      else
        cbGender.ItemIndex := 0; // 默认男

      dtpBirth.Text := ABirth;
      edtID.Text := AID;
      edtPhone.Text := APhone;
      edtAddress.Text := AAddress;
      edtTemp.Text := ATemp;
      edtSBP.Text := ASBP;
      edtDBP.Text := ADBP;
      edtHeartRate.Text := AHeartRate;
      memSymptoms.Text := ASymptoms;
      memHistory.Text := AHistory;
      edtAllergy.Text := AAllergy;
      edtContact.Text := AContact;
      memRemark.Text := ARemark;

      Result := AName; // 返回姓名
    end;
  end;

begin
  Z.Core.Main_Thread_Sync_Tool.Synchronize(do_sync);
end;

function NewRecord(): integer;

  procedure do_sync();
  begin
    NewRecordForm := TNewRecordForm.Create(MainForm);
    NewRecordForm.Show;
    Result := 1;
  end;

begin
  Z.Core.Main_Thread_Sync_Tool.Synchronize(do_sync);
end;

function SaveRecord(): string;

  procedure do_sync();
  begin
    Result := NewRecordForm.BuildJSON;
    MainForm.ShowJSON(Result);
    NewRecordForm.DelayCloseTimer.Enabled := True;
    NewRecordForm := nil;
  end;

begin
  Z.Core.Main_Thread_Sync_Tool.Synchronize(do_sync);
end;

function TNewRecordForm.ValidateInputs: boolean;
var
  i: integer;
begin
  Result := True;
  if Trim(edtName.Text) = '' then
  begin
    ShowMessage('请输入姓名！');
    edtName.SetFocus;
    Exit(False);
  end;
  if Trim(edtAge.Text) = '' then
  begin
    ShowMessage('请输入年龄！');
    edtAge.SetFocus;
    Exit(False);
  end;
  if not TryStrToInt(edtAge.Text, i) then
  begin
    ShowMessage('年龄必须为整数！');
    edtAge.SetFocus;
    Exit(False);
  end;
  // 其他字段非强制，可扩展
  Result := True;
end;

function TNewRecordForm.BuildJSON: string;
var
  jo: TZ_JsonObject;
begin
  jo := TZ_JsonObject.Create;
  try
    jo.S['name'] := Trim(edtName.Text);
    jo.i['age'] := StrToIntDef(edtAge.Text, 0);
    jo.S['gender'] := cbGender.Text;
    jo.S['birth'] := dtpBirth.Text;
    jo.S['id'] := Trim(edtID.Text);
    jo.S['phone'] := Trim(edtPhone.Text);
    jo.S['address'] := Trim(edtAddress.Text);
    jo.S['temperature'] := Trim(edtTemp.Text);
    jo.S['sbp'] := Trim(edtSBP.Text);
    jo.S['dbp'] := Trim(edtDBP.Text);
    jo.S['heart_rate'] := Trim(edtHeartRate.Text);
    jo.S['symptoms'] := Trim(memSymptoms.Text);
    jo.S['history'] := Trim(memHistory.Text);
    jo.S['allergy'] := Trim(edtAllergy.Text);
    jo.S['emergency_contact'] := Trim(edtContact.Text);
    jo.S['remark'] := Trim(memRemark.Text);
    Result := jo.ToJSONString(True).Text;
  finally
    jo.Free;
  end;
end;

procedure TNewRecordForm.btnOKClick(Sender: TObject);
var
  JSONStr: string;
begin
  if not ValidateInputs then Exit;
  JSONStr := BuildJSON;
  MainForm.ShowJSON(JSONStr);
  NewRecordForm := nil;
  Close;
end;

procedure TNewRecordForm.DelayCloseTimerTimer(Sender: TObject);
begin
  DelayCloseTimer.Tag := DelayCloseTimer.Tag - DelayCloseTimer.Interval;
  Caption := Format('新建健康记录 - 输入窗口将会在 %s 秒以后关闭...', [umlTimeTickToStr(DelayCloseTimer.Tag).Text]);
  if DelayCloseTimer.Tag <= 0 then
    Close;
end;

procedure TNewRecordForm.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  CloseAction := caFree;
end;

procedure TNewRecordForm.btnCancelClick(Sender: TObject);
begin
  Close;
end;

end.
