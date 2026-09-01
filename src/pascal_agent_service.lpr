program pascal_agent_service;

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
  APP_NAME = 'my_tool_provider';          // Application name (also used as target_app for all tools)
  APP_DESC = 'My tool provider';          // Application description
  IPC_ENDPOINT = 'ipc:cross';             // IPC service endpoint
  TCP_LISTEN_ADDR = '0.0.0.0:9897';       // TCP listening address
  TCP_PUBLIC_ADDR = '127.0.0.1:9897';     // TCP public address (for client connections)

type
  TRegisteredAgent = class(TBigList<TZ_JsonObject>)
  public
    procedure DoFree(var Data: TZ_JsonObject); override;
  end;

procedure TRegisteredAgent.DoFree(var Data: TZ_JsonObject);
begin
  DisposeObjectAndNil(Data);
  inherited DoFree(Data);
end;

var
  RegisteredAgent: TRegisteredAgent;

  // ============================================================================
  // 1. Business API Callbacks
  // ============================================================================

// ---------- agent_log (Call) – Receive log message and return status ----------
procedure do_agent_log(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  msg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
    jo.ParseText(jsonStr);
    if jo.Exists('message') then
      msg := jo.S['message']
    else
      msg := jsonStr.Text;

    if msg <> '' then
      DoStatus('[agent_log] %s', [msg]);

    jo.Clear;
    jo.S['status'] := 'ok';
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
  except
    jo.Clear;
    jo.S['status'] := 'error';
    jo.S['message'] := 'Internal error processing log';
    LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    jo.Free;
  end;
end;

// ---------- agent_main (Call) – Tool list entry point ----------
procedure do_agent_main(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  JsonObj: TZ_JsonObject;
  JsonArr: TZ_JsonArray;
  toolObj: TZ_JsonObject;
begin
  JsonObj := TZ_JsonObject.Create;
  try
    JsonArr := JsonObj.a['tools'];

    // ----- agent_log tool -----
    toolObj := JsonArr.AddObject;
    toolObj.S['name'] := 'agent_log';
    toolObj.S['description'] := 'Send log messages to the pascal-language backend';
    toolObj.S['target_app'] := APP_NAME;   // use constant
    toolObj.S['target_api'] := 'agent_log';
    with toolObj.O['parameters'] do
    begin
      S['type'] := 'object';
      with O['properties'] do
      begin
        with O['message'] do
        begin
          S['type'] := 'string';
          S['description'] := 'Log message content';
        end;
      end;
      with a['required'] do
        Add('message');
    end;

    // Append dynamically registered tools from RegisteredAgent
    if RegisteredAgent.Num > 0 then
      with RegisteredAgent.Repeat_ do
        repeat
          // Validate required fields
          if queue^.Data.Exists('name') and queue^.Data.Exists('description') and queue^.Data.Exists('target_app') and queue^.Data.Exists('target_api') and queue^.Data.Exists('parameters') then
          begin
            // Check if the target API is actually available via LingoFuse
            if LF_CheckApiEx(queue^.Data.S['target_app'], queue^.Data.S['target_api']) then
            begin
              toolObj := JsonArr.AddObject;
              toolObj.Assign(queue^.Data);
            end
            else
              DoStatus('[agent_main] Skipping tool "%s": API %s.%s not available', [queue^.Data.S['name'], queue^.Data.S['target_app'], queue^.Data.S['target_api']]);
          end
          else
            DoStatus('[agent_main] Skipping invalid tool registration (missing required fields) for entry: %s', [queue^.Data.ToJSONString(False).Text]);
        until not Next;

    LF_WriteString(TDataHnd(Output), JsonObj.ToJSONString(False).Text);
  finally
    JsonObj.Free;
  end;
end;

// ---------- agent_register (Call) – Dynamic tool registration ----------
procedure do_register_agent(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TZ_JsonString;
  jo: TZ_JsonObject;
  toolObj: TZ_JsonObject;
  Name: string;
  found: boolean;
begin
  jo := TZ_JsonObject.Create;
  try
    try
      jsonStr.ReadUTF8AnsiChar(LF_GetBuffer(TDataHnd(Input)), LF_GetSize(TDataHnd(Input)));
      jo.ParseText(jsonStr);

      // ---- Validate required fields ----
      if not jo.Exists('name') then
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Missing "name" field';
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;
      if not jo.Exists('description') then
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Missing "description" field';
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;
      if not jo.Exists('target_app') then
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Missing "target_app" field';
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;
      if not jo.Exists('target_api') then
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Missing "target_api" field';
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;
      if not jo.Exists('parameters') then
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Missing "parameters" field';
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;

      // ---- Search for existing tool with the same name ----
      Name := jo.S['name'];
      found := False;
      if RegisteredAgent.Num > 0 then
        with RegisteredAgent.Repeat_ do
          repeat
            if umlMultipleMatch(Name, queue^.Data.S['name']) then
            begin
              // Overwrite existing definition
              queue^.Data.Assign(jo);
              found := True;
              Break;
            end;
          until not Next;

      // ---- Add new tool if not found ----
      if not found then
      begin
        toolObj := TZ_JsonObject.Create;
        toolObj.Assign(jo);
        RegisteredAgent.Add(toolObj);
      end;

      // ---- Return success ----
      jo.Clear;
      jo.S['status'] := 'ok';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);

    except
      on E: Exception do
      begin
        jo.Clear;
        jo.S['status'] := 'error';
        jo.S['message'] := 'Internal error: ' + E.Message;
        LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
        Exit;
      end;
    end;
  finally
    jo.Free;
  end;
end;

// ============================================================================
// 2. Main Program
// ============================================================================
var
  App: LF.TAppHandle;
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
  RegisteredAgent := TRegisteredAgent.Create;
  App := LF.TAppHandle.Create(APP_NAME, APP_DESC);   // use constants

  // Register agent_log (Call)
  App.RegisterCall('agent_log', 'Logging tool (notify)', nil, @do_agent_log);
  // Register agent_main (tool list entry)
  App.RegisterCall('agent_main', 'Return tool list as JSON with schemas', nil, @do_agent_main);
  // Register agent_register (future dynamic registration)
  App.RegisterCall('register_agent', 'Register a new tool dynamically', nil, @do_register_agent);

  LF.SetOption('WaitConnect', 'False');
  LF.ResetPrepare;
  LF.PrepareService(IPC_ENDPOINT, IPC_ENDPOINT);                     // IPC service
  LF.PrepareService(TCP_LISTEN_ADDR, TCP_PUBLIC_ADDR);               // TCP service
  LF.PrepareClient(IPC_ENDPOINT, App);                               // local IPC client
  LF.PrepareClient(TCP_PUBLIC_ADDR, App);                            // local TCP client
  LF.PrepareDone;

  Running := True;
  TCompute.RunC_NP(Wait_Input, @IsRunning, nil);
  while IsRunning do
    TCompute.Sleep(100);

  LF.ExitMainThread;
  LF.Shutdown;
  App.Free;
  DisposeObjectAndNil(RegisteredAgent);
end.
