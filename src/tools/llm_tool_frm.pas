unit llm_tool_frm;

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\zNetV2\source\Z.Define.inc}

interface

uses
  Classes, SysUtils, Forms, Controls, Graphics, Dialogs, StdCtrls, ExtCtrls, ComCtrls,
  SynEdit, SynEditMiscClasses, SynHighlighterAny,
  llm_client, lingofuse_import, lingofuse_helper,
  Z.Core, Z.PascalStrings, Z.UPascalStrings, Z.Json, Z.UnicodeMixedLib, Z.Status;

type

  { Tllm_tool_form }

  Tllm_tool_form = class(TForm)
    Button1: TButton;
    conn_llm_Button: TButton;
    Label1: TLabel;
    Label2: TLabel;
    Label3: TLabel;
    Label4: TLabel;
    llm_APP_Edit: TLabeledEdit;
    LLM_Service_Edit: TLabeledEdit;
    PageControl: TPageControl;
    LLM_Opt_TabSheet: TTabSheet;
    Input_TabSheet: TTabSheet;
    Output_TabSheet: TTabSheet;
    Panel1: TPanel;
    Panel2: TPanel;
    Panel3: TPanel;
    Splitter1: TSplitter;
    SynAnySyn1: TSynAnySyn;
    sys_prompt_Memo: TMemo;
    code_Edit: TSynEdit;
    test_generate_Button: TButton;
    prompt_edit: TMemo;
    sse_Edit: TSynEdit;
    procedure Button1Click(Sender: TObject);
    procedure conn_llm_ButtonClick(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
    procedure test_generate_ButtonClick(Sender: TObject);
  private
    procedure Do_LLM_Chunk(const Chunk: string);
    procedure Do_LLM_Error(const ErrorMsg: string);
    procedure Do_LLM_Finish();
    procedure Do_Thread_Connect_Done;
    procedure Do_Thread_Connect;
  public
    constructor Create(AOwner: TComponent); override;
    destructor Destroy; override;
    procedure Enabled_All;
    procedure Disable_All;
  end;

var
  llm_tool_form: Tllm_tool_form;
  LLM: TLLMClient;
  session_id: string;

implementation

{$R *.lfm}

procedure Tllm_tool_form.Button1Click(Sender: TObject);
var
  err: string;
  n: TP_String;
begin
  if LLM = nil then exit;
  n := sys_prompt_Memo.Lines.Text;
  n := n.TrimChar(#13#10#32#9);
  if not LLM.SetSystemMessage(n, err) then
    DoStatus(err);
  DoStatus('更新系统消息');
end;

procedure Tllm_tool_form.conn_llm_ButtonClick(Sender: TObject);
begin
  if LLM <> nil then exit;
  Disable_All;
  TCompute.RunM_NP(Do_Thread_Connect);
end;

procedure Tllm_tool_form.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  CloseAction := caHide;
end;

procedure Tllm_tool_form.test_generate_ButtonClick(Sender: TObject);
var
  session_id, err: string;
begin
  if LLM = nil then exit;
  if LLM.Generate(code_Edit.Text, prompt_edit.Lines.Text, session_id, err) then
  begin
    PageControl.ActivePage := Output_TabSheet;
    sse_Edit.ReadOnly := True;
    sse_Edit.Clear;
  end
  else
    DoStatus(err);
end;

procedure Tllm_tool_form.Do_LLM_Chunk(const Chunk: string);
var
  s: TZ_JsonString;
begin
  if sse_Edit.Lines.Count <= 0 then
    sse_Edit.Lines.Add('');

  s.Text := Chunk;
  s := s.DeleteChar(#13);
  if s.l <= 0 then exit;
  if s.Exists([#10]) then
  begin
    sse_Edit.Lines[sse_Edit.Lines.Count - 1] :=
      sse_Edit.Lines[sse_Edit.Lines.Count - 1] + umlGetFirstStr___(Chunk, #10);
    sse_Edit.Lines.Add('');
    Do_LLM_Chunk(umlDeleteFirstStr___(Chunk, #10).Text);
  end
  else
  begin
    sse_Edit.Lines[sse_Edit.Lines.Count - 1] :=
      sse_Edit.Lines[sse_Edit.Lines.Count - 1] + s;
  end;
end;

procedure Tllm_tool_form.Do_LLM_Error(const ErrorMsg: string);
begin
  sse_Edit.ReadOnly := False;
end;

procedure Tllm_tool_form.Do_LLM_Finish();
begin
  sse_Edit.Lines.Add('会话结束');
  sse_Edit.ReadOnly := False;
end;

procedure Tllm_tool_form.Do_Thread_Connect_Done;
begin
  Enabled_All();
  PageControl.ActivePage := Input_TabSheet;
end;

procedure Tllm_tool_form.Do_Thread_Connect;
var
  err: string;
  n: TP_String;
begin
  if LLM = nil then
  begin
    LLM := TLLMClient.Create(llm_APP_Edit.Text, LLM_Service_Edit.Text, 5000);
    LLM.OnError := Do_LLM_Error;
    LLM.OnChunk := Do_LLM_Chunk;
    LLM.OnFinish := Do_LLM_Finish;
    if not LLM.Connect(err) then
    begin
      DoStatus(err);
      disposeObjectAndNil(LLM);
      exit;
    end;

    if not LF.CheckApp(llm_APP_Edit.Text) then
    begin
      disposeObjectAndNil(LLM);
      exit;
    end;
    DoStatus('app "%s" 确认握手', [llm_APP_Edit.Text]);
  end;
  n := sys_prompt_Memo.Lines.Text;
  n := n.TrimChar(#13#10#32#9);
  if not LLM.SetSystemMessage(n, err) then
    DoStatus(err);
  DoStatus('更新系统消息');
  TCompute.SyncM(Do_Thread_Connect_Done);
end;

constructor Tllm_tool_form.Create(AOwner: TComponent);
begin
  inherited Create(AOwner);
  LLM := nil;
  Disable_All();
  conn_llm_Button.Enabled := True;
  LLM_Service_Edit.Enabled := True;
  llm_APP_Edit.Enabled := True;
  sys_prompt_Memo.Enabled := True;
  sse_Edit.Enabled := True;
end;

destructor Tllm_tool_form.Destroy;
begin
  inherited Destroy;
end;

procedure Tllm_tool_form.Enabled_All;
var
  i: integer;
begin
  conn_llm_Button.Enabled := True;
  test_generate_Button.Enabled := True;
  for i := 0 to ComponentCount - 1 do
    if (Components[i] is TControl) then
    begin
      if (Components[i] is TCustomEdit) or (Components[i] is TCustomMemo) or (Components[i] is TSynEditBase) or
        (Components[i] is TCustomLabel) or (Components[i] is TCustomButton) then
      begin
        TControl(Components[i]).Enabled := True;
      end;
    end;
end;

procedure Tllm_tool_form.Disable_All;
var
  i: integer;
begin
  conn_llm_Button.Enabled := False;
  test_generate_Button.Enabled := False;
  for i := 0 to ComponentCount - 1 do
    if (Components[i] is TControl) then
    begin
      if (Components[i] is TCustomEdit) or (Components[i] is TCustomMemo) or (Components[i] is TSynEditBase) or
        (Components[i] is TCustomLabel) or (Components[i] is TCustomButton) then
      begin
        TControl(Components[i]).Enabled := False;
      end;
    end;
end;


end.
