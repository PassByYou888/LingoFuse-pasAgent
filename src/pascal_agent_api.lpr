program pascal_agent_api;

(*
  pascal_agent_api – LingoFuse Arithmetic Tool Provider
  (Revised: consistently using LF_ReadStringBytes / LF_WriteStringBytes + TZ_JsonObject.ToBytes/Parae)
*)

{$ifdef FPC}
  {$mode delphi}{$H+}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}

{$APPTYPE CONSOLE}

uses
  SysUtils,
  Classes,
  lingofuse_import,
  lingofuse_helper,
  Z.Core,
  Z.PascalStrings,
  Z.UPascalStrings,
  Z.Json,
  Z.Status,
  Z.UnicodeMixedLib;

const
  MY_APP_NAME = 'my_calculator';
  MY_APP_DESC = 'Calculator service providing arithmetic tools';
  IPC_ENDPOINT = 'ipc:agent';
  BEACON_APP = 'agent_main_app';
  REGISTER_API = 'register_agent';
  AGENT_LOG_API = 'agent_log';
  DEBUG_LOG = True;

// ---- Asynchronous logging (unchanged) ----
procedure Do_Th_Send(th: TCompute);
var
  p: Pointer;
  msg: TZ_JsonString;
  Data, ResultHnd: TDataHnd___;
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
      LF_WriteStringBytes(Data, jo.ToBytes);   // Use WriteStringBytes consistently
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
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  a, b, sum: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(Input));
    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[add] Error: %s', [errMsg]);
        SendLogAsync('[add] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[add] Error: %s', [errMsg]);
        SendLogAsync('[add] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  a, b, diff: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(Input));
    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[sub] Error: %s', [errMsg]);
        SendLogAsync('[sub] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[sub] Error: %s', [errMsg]);
        SendLogAsync('[sub] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  a, b, prod: integer;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(Input));
    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[mul] Error: %s', [errMsg]);
        SendLogAsync('[mul] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[mul] Error: %s', [errMsg]);
        SendLogAsync('[mul] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  a, b: integer;
  quot: double;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(Input));
    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[div] Error: %s', [errMsg]);
        SendLogAsync('[div] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[div] Error: %s', [errMsg]);
        SendLogAsync('[div] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Exists('a') or not jo.Exists('b') then
    begin
      errMsg := 'Missing "a" or "b"';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
      LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
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
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
    if DEBUG_LOG then
    begin
      DoStatus('[div] %d / %d = %.2f', [a, b, quot]);
      SendLogAsync(Format('[div] %d / %d = %.2f', [a, b, quot]));
    end;
  finally
    jo.Free;
  end;
end;

// ---- Registration helper function ----
function RegisterTool(const ToolDef: TZ_JsonObject): boolean;
var
  Data, ResultHnd: TDataHnd___;
  jsonBytes: TBytes;
  RespJson: TZ_JsonObject;
begin
  Result := False;
  Data := LF_CreateDataEx(REGISTER_API);
  try
    LF_WriteStringBytes(Data, ToolDef.ToBytes);
    ResultHnd := LF_CallEx(BEACON_APP, Data, 5000);
    try
      if LF_GetSize(ResultHnd) > 0 then
      begin
        jsonBytes := LF_ReadStringBytes(ResultHnd);
        if Length(jsonBytes) > 0 then
        begin
          RespJson := TZ_JsonObject.Create;
          try
            if RespJson.Parae(jsonBytes) and RespJson.Exists('status') and (RespJson.S['status'] = 'ok') then
              Result := True
            else if DEBUG_LOG then
                DoStatus('[Register] Failed: %s', [RespJson.S['message']]);
          finally
            RespJson.Free;
          end;
        end;
      end;
    finally
      LF_FreeData(ResultHnd);
    end;
  finally
    LF_FreeData(Data);
  end;
end;

// ---- Main program ----
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
  App := LF.TAppHandle.Create(MY_APP_NAME, MY_APP_DESC);
  if DEBUG_LOG then
    DoStatus('[MAIN] Application "%s" created.', [MY_APP_NAME]);

  App.RegisterCall('add', 'Add two integers', nil, @do_add);
  App.RegisterCall('sub', 'Subtract two integers', nil, @do_sub);
  App.RegisterCall('mul', 'Multiply two integers', nil, @do_mul);
  App.RegisterCall('div', 'Divide two integers (floating result)', nil, @do_div);
  if DEBUG_LOG then
    DoStatus('[MAIN] Registered APIs: add, sub, mul, div');

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

  // ---- add ----
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

  // ---- sub ----
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

  // ---- mul ----
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

  // ---- div ----
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

  if DEBUG_LOG then
    DoStatus('[MAIN] Shutting down...');
  LF.ExitMainThread;
  LF.Shutdown;
  App.Free;
  if DEBUG_LOG then
    DoStatus('[MAIN] Cleanup complete.');
end.
