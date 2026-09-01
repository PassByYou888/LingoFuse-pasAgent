program pascal_agent_api;

{$ifdef FPC}
  {$mode delphi}{$H+}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}

{$APPTYPE CONSOLE}

uses
  SysUtils, Classes, lingofuse_import, lingofuse_helper, Z.Core, Z.PascalStrings, Z.Json, Z.Status, Z.UnicodeMixedLib;

// ============================================================================
// Constants – Global Configuration
// ============================================================================
const
  MY_APP_NAME = 'my_calculator';          // This application's name
  MY_APP_DESC = 'Calculator service providing arithmetic tools';
  IPC_ENDPOINT = 'ipc:cross';             // Hub (beacon) endpoint
  REGISTER_API = 'register_agent';        // Registration API on beacon
  BEACON_APP = 'my_tool_provider';        // Beacon application name

// ============================================================================
// 1. Business API Callbacks
// ============================================================================

// ---------- add (Call) – Integer addition ----------
procedure do_add(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, sum: integer;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      jo.Clear;
      jo.S['error'] := 'Missing "a" or "b"';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    sum := a + b;
    jo.Clear;
    jo.I['result'] := sum;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
  finally
    jo.Free;
  end;
end;

// ---------- sub (Call) – Integer subtraction ----------
procedure do_sub(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, diff: integer;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      jo.Clear;
      jo.S['error'] := 'Missing "a" or "b"';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    diff := a - b;
    jo.Clear;
    jo.I['result'] := diff;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
  finally
    jo.Free;
  end;
end;

// ---------- mul (Call) – Integer multiplication ----------
procedure do_mul(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, prod: integer;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      jo.Clear;
      jo.S['error'] := 'Missing "a" or "b"';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    prod := a * b;
    jo.Clear;
    jo.I['result'] := prod;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
  finally
    jo.Free;
  end;
end;

// ---------- div (Call) – Integer division (floating result) ----------
procedure do_div(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b: integer;
  quot: double;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      jo.Clear;
      jo.S['error'] := 'Missing "a" or "b"';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    if b = 0 then
    begin
      jo.Clear;
      jo.S['error'] := 'Division by zero';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    quot := a / b;
    jo.Clear;
    jo.F['result'] := quot;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
  finally
    jo.Free;
  end;
end;

// ============================================================================
// 2. Helper: Register a single tool with the beacon
// ============================================================================
function RegisterTool(const ToolDef: TZ_JsonObject): boolean;
var
  Data, ResultHnd: TDataHnd___;
  RespJson: TZ_JsonObject;
  jsonStr: TZ_JsonString;
begin
  Result := False;
  Data := LF_CreateDataEx(REGISTER_API);
  try
    // Write the tool definition as a JSON string (with null terminator)
    LF_WriteString(Data, ToolDef.ToJSONString(False).Text);
    // Call the beacon's register_agent API
    ResultHnd := LF_CallEx(BEACON_APP, Data, 5000);
    try
      if LF_GetSize(ResultHnd) > 0 then
      begin
        jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(ResultHnd), LF_GetSize(ResultHnd));
        RespJson := TZ_JsonObject.Create;
        try
          RespJson.ParseText(jsonStr);
          if RespJson.Exists('status') and (RespJson.S['status'] = 'ok') then
            Result := True
          else
            DoStatus('[Register] Failed: %s', [RespJson.S['message']]);
        finally
          RespJson.Free;
        end;
      end;
    finally
      LF_FreeData(ResultHnd);
    end;
  finally
    LF_FreeData(Data);
  end;
end;

// ============================================================================
// 3. Main Program
// ============================================================================
var
  App: LF.TAppHandle;
  ToolDef: TZ_JsonObject;
  ParamsObj, PropsObj, PropObj: TZ_JsonObject;
  RequiredArr: TZ_JsonArray;
  Success: boolean;
  Running, IsRunning: boolean;

procedure Wait_Input();
var S: string;
begin
  while Running do
  begin
    readln(S);
    if umlMultipleMatch('exit', S) then
      Break;
  end;
end;

begin
  // Create our own application
  App := LF.TAppHandle.Create(MY_APP_NAME, MY_APP_DESC);

  // Register our business APIs
  App.RegisterCall('add', 'Add two integers', nil, @do_add);
  App.RegisterCall('sub', 'Subtract two integers', nil, @do_sub);
  App.RegisterCall('mul', 'Multiply two integers', nil, @do_mul);
  App.RegisterCall('div', 'Divide two integers (floating result)', nil, @do_div);

  // Connect to the beacon (hub)
  LF.SetOption('WaitConnect', 'True');
  LF.ResetPrepare;
  LF.PrepareClient(IPC_ENDPOINT, App);   // expose our app to the beacon
  if not LF.PrepareDone() then
  begin
    DoStatus('[ERROR] Failed to connect to beacon at %s', [IPC_ENDPOINT]);
    LF.Shutdown;
    exit;
  end;

  DoStatus('[INFO] Connected to beacon; registering tools...');

  // ---- Register each tool ----
  // Tool: add
  ToolDef := TZ_JsonObject.Create;
  try
    ToolDef.S['name'] := 'add';
    ToolDef.S['description'] := 'Add two integers: a + b';
    ToolDef.S['target_app'] := MY_APP_NAME;
    ToolDef.S['target_api'] := 'add';
    ParamsObj := ToolDef.O['parameters'];
    ParamsObj.S['type'] := 'object';
    PropsObj := ParamsObj.O['properties'];
    PropObj := PropsObj.O['a'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'First operand';
    PropObj := PropsObj.O['b'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'Second operand';
    RequiredArr := ParamsObj.a['required'];
    RequiredArr.Add('a');
    RequiredArr.Add('b');
    Success := RegisterTool(ToolDef);
    if Success then
      DoStatus('[OK] Registered tool: add')
    else
      DoStatus('[FAIL] Failed to register add');
  finally
    ToolDef.Free;
  end;

  // Tool: sub
  ToolDef := TZ_JsonObject.Create;
  try
    ToolDef.S['name'] := 'sub';
    ToolDef.S['description'] := 'Subtract two integers: a - b';
    ToolDef.S['target_app'] := MY_APP_NAME;
    ToolDef.S['target_api'] := 'sub';
    ParamsObj := ToolDef.O['parameters'];
    ParamsObj.S['type'] := 'object';
    PropsObj := ParamsObj.O['properties'];
    PropObj := PropsObj.O['a'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'First operand';
    PropObj := PropsObj.O['b'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'Second operand';
    RequiredArr := ParamsObj.a['required'];
    RequiredArr.Add('a');
    RequiredArr.Add('b');
    Success := RegisterTool(ToolDef);
    if Success then
      DoStatus('[OK] Registered tool: sub')
    else
      DoStatus('[FAIL] Failed to register sub');
  finally
    ToolDef.Free;
  end;

  // Tool: mul
  ToolDef := TZ_JsonObject.Create;
  try
    ToolDef.S['name'] := 'mul';
    ToolDef.S['description'] := 'Multiply two integers: a * b';
    ToolDef.S['target_app'] := MY_APP_NAME;
    ToolDef.S['target_api'] := 'mul';
    ParamsObj := ToolDef.O['parameters'];
    ParamsObj.S['type'] := 'object';
    PropsObj := ParamsObj.O['properties'];
    PropObj := PropsObj.O['a'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'First operand';
    PropObj := PropsObj.O['b'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'Second operand';
    RequiredArr := ParamsObj.a['required'];
    RequiredArr.Add('a');
    RequiredArr.Add('b');
    Success := RegisterTool(ToolDef);
    if Success then
      DoStatus('[OK] Registered tool: mul')
    else
      DoStatus('[FAIL] Failed to register mul');
  finally
    ToolDef.Free;
  end;

  // Tool: div
  ToolDef := TZ_JsonObject.Create;
  try
    ToolDef.S['name'] := 'div';
    ToolDef.S['description'] := 'Divide two integers (floating result): a / b';
    ToolDef.S['target_app'] := MY_APP_NAME;
    ToolDef.S['target_api'] := 'div';
    ParamsObj := ToolDef.O['parameters'];
    ParamsObj.S['type'] := 'object';
    PropsObj := ParamsObj.O['properties'];
    PropObj := PropsObj.O['a'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'Dividend';
    PropObj := PropsObj.O['b'];
    PropObj.S['type'] := 'integer';
    PropObj.S['description'] := 'Divisor (must be non-zero)';
    RequiredArr := ParamsObj.a['required'];
    RequiredArr.Add('a');
    RequiredArr.Add('b');
    Success := RegisterTool(ToolDef);
    if Success then
      DoStatus('[OK] Registered tool: div')
    else
      DoStatus('[FAIL] Failed to register div');
  finally
    ToolDef.Free;
  end;

  DoStatus('[INFO] All tools registered. Keeping application running for API availability.');
  DoStatus('input "exit" to quit....');
  Running := True;
  TCompute.RunC_NP(Wait_Input, @IsRunning, nil);
  while IsRunning do
    TCompute.Sleep(100);

  // Cleanup
  LF.ExitMainThread;
  LF.Shutdown;
  App.Free;
end.
