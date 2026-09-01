program pascal_agent_api;

(*
  pascal_agent_api – LingoFuse Arithmetic Tool Provider

  DESCRIPTION
    This program is a LingoFuse client that registers arithmetic tools (add, sub, mul, div)
    with a central beacon service (pascal_agent_service). It acts as a tool provider
    for the MCP (Model Context Protocol) gateway: the beacon exposes these tools via
    its agent_main API, and the MCP server (mcp_server.py) can then discover and call them.

    Architecture:
      ┌────────────────┐       register_agent          ┌──────────────────────┐
      │  This program  │ ──────────────────────────>   │  pascal_agent_service│
      │ (my_calculator)│                               │   (my_tool_provider) │
      └────────────────┘                               └──────────────────────┘
             │                                                   │
             │  ┌──────────────────────────────────────────────┐ │
             └─>│ agent_log (async)                            │◀<
                │ agent_main (returns tool list including      │
                │  add/sub/mul/div)                            │
                └──────────────────────────────────────────────┘

    The beacon collects tool definitions from multiple providers and presents them
    as a unified tool list to MCP clients.

  CONFIGURATION (constants below)
    MY_APP_NAME      = 'my_calculator'   (must match target_app in tool definitions)
    MY_APP_DESC      = 'Calculator service providing arithmetic tools'
    IPC_ENDPOINT     = 'ipc:cross'       (must match LINGOFUSE_ENDPOINT default)
    BEACON_APP       = 'my_tool_provider'(must match tool_provider_app in Python)
    REGISTER_API     = 'register_agent'  (API name on beacon)
    AGENT_LOG_API    = 'agent_log'       (API name on beacon for logging)
    DEBUG_LOG        = True              (set False to disable all debug logging)

  USAGE
    Compile and run. It will connect to the beacon, register its tools, and then
    wait for incoming calls. Type 'exit' to quit.

  DEPENDENCIES
    - LingoFuse dynamic library (LingoFuse64.dll / liblingofuse.so)
    - Z.Core, Z.Json, Z.Status etc.

  AUTHOR
    PassByYou888 / LingoFuse Team
*)

{$ifdef FPC}
  {$mode delphi}{$H+}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}

{$APPTYPE CONSOLE}

uses
  SysUtils, Classes, lingofuse_import, lingofuse_helper, Z.Core, Z.PascalStrings, Z.UPascalStrings, Z.Json, Z.Status, Z.UnicodeMixedLib;

  // ============================================================================
  // Constants – Global Configuration
  // ============================================================================
const
  MY_APP_NAME = 'my_calculator';
  MY_APP_DESC = 'Calculator service providing arithmetic tools';
  IPC_ENDPOINT = 'ipc:cross';
  BEACON_APP = 'my_tool_provider';    // The beacon application name
  REGISTER_API = 'register_agent';      // Beacon's registration API
  AGENT_LOG_API = 'agent_log';           // Beacon's logging API

  DEBUG_LOG = True;                  // Set to False to silence all logs

  // ============================================================================
  // 1. Business API Callbacks
  // ============================================================================

  // ---- Helper: Send a log message to the beacon asynchronously ----

procedure Do_Th_Send(th: TCompute);
var
  p: Pointer;
  msg: TZ_JsonString;
  Data, ResultHnd: TDataHnd___;
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
begin
  p := th.UserData;
  msg.ReadUTF8AnsiChar(p);
  TZ_JsonString.FreeUTF8AnsiChar(p);

  Data := LF_CreateDataEx(AGENT_LOG_API);
  try
    jo := TZ_JsonObject.Create;
    try
      jo.S['message'] := msg.Text;
      LF_WriteString(Data, jo.ToJSONString(False).Text);
    finally
      jo.Free;
    end;
    ResultHnd := LF_CallEx(BEACON_APP, Data, 3000);
    if ResultHnd <> nil then
      LF_FreeData(ResultHnd);
  finally
    LF_FreeData(Data);
  end;
end;

procedure SendLogAsync(const msg: TZ_JsonString);
begin
  TCompute.RunC(msg.BuildUTF8AnsiChar, nil, Do_Th_Send);
end;

// ---- add ----
procedure do_add(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, sum: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      if DEBUG_LOG then
      begin
        DoStatus('[add] Error: %s', [errMsg]);
        SendLogAsync('[add] Error: ' + errMsg);
      end;
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    sum := a + b;
    jo.Clear;
    jo.I['result'] := sum;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    if DEBUG_LOG then
    begin
      DoStatus('[add] %d + %d = %d', [a, b, sum]);
      SendLogAsync(Format('[add] %d + %d = %d', [a, b, sum]));
    end;
  finally
    jo.Free;
  end;
end;

// ---- sub ----
procedure do_sub(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, diff: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      if DEBUG_LOG then
      begin
        DoStatus('[sub] Error: %s', [errMsg]);
        SendLogAsync('[sub] Error: ' + errMsg);
      end;
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    diff := a - b;
    jo.Clear;
    jo.I['result'] := diff;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    if DEBUG_LOG then
    begin
      DoStatus('[sub] %d - %d = %d', [a, b, diff]);
      SendLogAsync(Format('[sub] %d - %d = %d', [a, b, diff]));
    end;
  finally
    jo.Free;
  end;
end;

// ---- mul ----
procedure do_mul(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b, prod: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      if DEBUG_LOG then
      begin
        DoStatus('[mul] Error: %s', [errMsg]);
        SendLogAsync('[mul] Error: ' + errMsg);
      end;
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    prod := a * b;
    jo.Clear;
    jo.I['result'] := prod;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    if DEBUG_LOG then
    begin
      DoStatus('[mul] %d * %d = %d', [a, b, prod]);
      SendLogAsync(Format('[mul] %d * %d = %d', [a, b, prod]));
    end;
  finally
    jo.Free;
  end;
end;

// ---- div ----
procedure do_div(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  a, b: integer;
  quot: double;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      if DEBUG_LOG then
      begin
        DoStatus('[div] Error: %s', [errMsg]);
        SendLogAsync('[div] Error: ' + errMsg);
      end;
      Exit;
    end;
    a := jo.I['a'];
    b := jo.I['b'];
    if b = 0 then
    begin
      errMsg := 'Division by zero';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      if DEBUG_LOG then
      begin
        DoStatus('[div] Error: %s', [errMsg]);
        SendLogAsync('[div] Error: ' + errMsg);
      end;
      Exit;
    end;
    quot := a / b;
    jo.Clear;
    jo.F['result'] := quot;
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    if DEBUG_LOG then
    begin
      DoStatus('[div] %d / %d = %.2f', [a, b, quot]);
      SendLogAsync(Format('[div] %d / %d = %.2f', [a, b, quot]));
    end;
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
          begin
            if DEBUG_LOG then
              DoStatus('[Register] Failed: %s', [RespJson.S['message']]);
          end;
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
    ReadLn(S);
    if umlMultipleMatch('exit', S) then
      Break;
  end;
end;

begin
  // Create our own application
  App := LF.TAppHandle.Create(MY_APP_NAME, MY_APP_DESC);
  if DEBUG_LOG then
    DoStatus('[MAIN] Application "%s" created.', [MY_APP_NAME]);

  // Register our business APIs
  App.RegisterCall('add', 'Add two integers', nil, @do_add);
  App.RegisterCall('sub', 'Subtract two integers', nil, @do_sub);
  App.RegisterCall('mul', 'Multiply two integers', nil, @do_mul);
  App.RegisterCall('div', 'Divide two integers (floating result)', nil, @do_div);
  if DEBUG_LOG then
    DoStatus('[MAIN] Registered APIs: add, sub, mul, div');

  // Connect to the beacon
  LF.SetOption('WaitConnect', 'True');
  LF.ResetPrepare;
  LF.PrepareClient(IPC_ENDPOINT, App);
  if not LF.PrepareDone() then
  begin
    DoStatus('[ERROR] Failed to connect to beacon at %s', [IPC_ENDPOINT]);
    LF.Shutdown;
    Exit;
  end;

  if DEBUG_LOG then
    DoStatus('[MAIN] Connected to beacon; registering tools...');

  // ---- Register each tool with full JSON schema ----
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
    if DEBUG_LOG then
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
    if DEBUG_LOG then
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
    if DEBUG_LOG then
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
    if DEBUG_LOG then
      if Success then
        DoStatus('[OK] Registered tool: div')
      else
        DoStatus('[FAIL] Failed to register div');
  finally
    ToolDef.Free;
  end;

  if DEBUG_LOG then
  begin
    DoStatus('[MAIN] All tools registered. Keeping application running for API availability.');
    DoStatus('input "exit" to quit....');
  end;

  Running := True;
  TCompute.RunC_NP(Wait_Input, @IsRunning, nil);
  while IsRunning do
    TCompute.Sleep(100);

  // Cleanup
  if DEBUG_LOG then
    DoStatus('[MAIN] Shutting down...');
  LF.ExitMainThread;
  LF.Shutdown;
  App.Free;
  if DEBUG_LOG then
    DoStatus('[MAIN] Cleanup complete.');
end.
