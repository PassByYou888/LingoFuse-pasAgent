program pascal_agent_service;

(*
  pascal_agent_service – LingoFuse Backend for MCP Tool Provider

  DESCRIPTION
    This program is a Pascal implementation of a LingoFuse service that acts as
    a tool provider for the MCP (Model Context Protocol) gateway. It exposes
    three main APIs:

      - agent_main   : Returns a JSON list of all available tools with their
                       schemas (used by mcp_server to dynamically register MCP tools).
      - agent_log    : Accepts log messages from the gateway and prints them
                       to the console (with optional forwarding to a log file).
      - register_agent: Allows dynamic registration of new tools at runtime
                       (used by language_middleware's reg_agent, if present).

    The service listens on both IPC (ipc:agent) and TCP (0.0.0.0:9897) to
    support both local and remote clients. It automatically registers itself
    with the LingoFuse C4 service mesh.

  CONFIGURATION (constants below)
    APP_NAME            = 'agent_main_app'   (must match tool_provider_app in Python)
    APP_DESC            = 'My tool provider'
    IPC_ENDPOINT        = 'ipc:agent'          (must match LINGOFUSE_ENDPOINT default)
    TCP_LISTEN_ADDR     = '0.0.0.0:9897'
    TCP_PUBLIC_ADDR     = '127.0.0.1:9897'

  USAGE
    Simply run the compiled executable. It will start the service and wait for
    incoming connections. Type 'exit' and press Enter to shut down gracefully.

  DEPENDENCIES
    - LingoFuse dynamic library (LingoFuse64.dll / liblingofuse.so)
    - Z.Core, Z.Json, Z.Status etc. (included in the project)

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
  SysUtils,
  Classes,
  Z.Core,
  Z.PascalStrings,
  Z.UPascalStrings,
  Z.Json,
  Z.Status,
  Z.UnicodeMixedLib,
  lingofuse_import,
  lingofuse_helper;

const
  APP_NAME = 'agent_main_app';
  APP_DESC = 'agent main application';
  IPC_ENDPOINT = 'ipc:agent';
  TCP_LISTEN_ADDR = '0.0.0.0:9897';
  TCP_PUBLIC_ADDR = '127.0.0.1:9897';

type
  { TRegisteredAgent – stores dynamically registered tool definitions (JSON objects) }
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
  // 1. API Callbacks
  // ============================================================================

(*
  do_agent_log – Callback for agent_log API
  Expects a JSON object with a "message" field.
  Logs the message via DoStatus and returns {"status":"ok"}.
  On error, returns {"status":"error","message":"..."}.
*)
procedure do_agent_log(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TBytes;
  jo: TZ_JsonObject;
  msg: string;
  ori_msg: TZ_JsonString;
begin
  jo := TZ_JsonObject.Create;
  try
    // Read the input string (UTF‑8, null‑terminated)
    jsonStr := LF_ReadStringBytes(TDataHnd(Input));
    jo.Parae(jsonStr);
    ori_msg.UTF8 := jsonStr;

    // Extract the message
    if jo.Exists('message') then
      msg := jo.S['message']
    else
      msg := ori_msg.Text;

    // Print the log message (this will also appear in the console)
    if msg <> '' then
      DoStatus('[agent_log] %s', [msg]);

    // Respond with success
    jo.Clear;
    jo.S['status'] := 'ok';
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
  except
    on E: Exception do
    begin
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Internal error: ' + E.Message;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      DoStatus('[agent_log] Exception: %s', [E.Message]);
    end;
  end;
  jo.Free;
end;

(*
  do_agent_main – Callback for agent_main API
  Returns a JSON object with a "tools" array containing definitions of all
  built‑in tools (agent_log) plus any dynamically registered tools.
  Each tool definition includes name, description, target_app, target_api,
  and a parameters schema (JSON Schema).
  The service checks API availability via LF_CheckApiEx to ensure only
  reachable tools are advertised.
*)
procedure do_agent_main(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  JsonObj: TZ_JsonObject;
  JsonArr: TZ_JsonArray;
  toolObj: TZ_JsonObject;
begin
  JsonObj := TZ_JsonObject.Create;
  try
    JsonArr := JsonObj.a['tools'];

    // ----- Built‑in tool: agent_log -----
    toolObj := JsonArr.AddObject;
    toolObj.S['name'] := 'agent_log';
    toolObj.S['description'] := 'Send log messages to the backend';
    toolObj.S['target_app'] := APP_NAME;
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

    // ----- Dynamically registered tools (from RegisteredAgent) -----
    RegisteredAgent.Lock;
    try
      if RegisteredAgent.Num > 0 then
        with RegisteredAgent.Repeat_ do
          repeat
            // Validate required fields
            if queue^.Data.Exists('name') and queue^.Data.Exists('description') and queue^.Data.Exists('target_app') and queue^.Data.Exists('target_api') and queue^.Data.Exists('parameters') then
            begin
              // Check if the target API is actually available (local or remote)
              if LF_CheckApiEx(queue^.Data.S['target_app'], queue^.Data.S['target_api']) then
              begin
                toolObj := JsonArr.AddObject;
                toolObj.Assign(queue^.Data);
                DoStatus('[agent_main] Included dynamic tool: %s (API %s.%s available)',
                  [queue^.Data.S['name'], queue^.Data.S['target_app'], queue^.Data.S['target_api']]);
              end
              else
                DoStatus('[agent_main] Skipped dynamic tool "%s": API %s.%s not available',
                  [queue^.Data.S['name'], queue^.Data.S['target_app'], queue^.Data.S['target_api']]);
            end
            else
              DoStatus('[agent_main] Skipped invalid tool registration (missing fields) for: %s',
                [queue^.Data.ToJSONString(False).Text]);
          until not Next;
    finally
      RegisteredAgent.UnLock;
    end;

    // Send the complete tool list as a JSON string
    LF_WriteStringBytes(TDataHnd(Output), JsonObj.ToBytes);
    DoStatus('[agent_main] Tool list sent (%d tools)', [JsonArr.Count]);
  finally
    JsonObj.Free;
  end;
end;

(*
  do_register_agent – Callback for register_agent API
  Accepts a JSON tool definition, validates required fields (name, description,
  target_app, target_api, parameters). If a tool with the same name already
  exists, it is overwritten; otherwise a new entry is added.
  Returns {"status":"ok"} on success, or {"status":"error","message":"..."} on failure.
  Errors are logged and do not raise exceptions.
*)
procedure do_register_agent(Trigger: Pointer; Input, Output: TDataHnd___); cdecl;
var
  jsonStr: TBytes;
  jo: TZ_JsonObject;
  toolObj: TZ_JsonObject;
  Name: string;
  found: boolean;
begin
  jo := TZ_JsonObject.Create;
  try
    // ---- Read and parse input ----
    jsonStr := LF_ReadStringBytes(TDataHnd(Input));
    jo.Parae(jsonStr);

    // ---- Validate required fields (if missing, log error and exit without adding) ----
    if not jo.Exists('name') then
    begin
      DoStatus('[register_agent] Error: Missing "name" field');
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Missing "name" field';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    if not jo.Exists('description') then
    begin
      DoStatus('[register_agent] Error: Missing "description" field');
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Missing "description" field';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    if not jo.Exists('target_app') then
    begin
      DoStatus('[register_agent] Error: Missing "target_app" field');
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Missing "target_app" field';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    if not jo.Exists('target_api') then
    begin
      DoStatus('[register_agent] Error: Missing "target_api" field');
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Missing "target_api" field';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;
    if not jo.Exists('parameters') then
    begin
      DoStatus('[register_agent] Error: Missing "parameters" field');
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Missing "parameters" field';
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
      Exit;
    end;

    Name := jo.S['name'];

    // ---- Search for existing tool with the same name ----
    found := False;
    RegisteredAgent.Lock;
    try
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

      if not found then
      begin
        toolObj := TZ_JsonObject.Create;
        toolObj.Assign(jo);
        RegisteredAgent.Add(toolObj);
      end
    finally
      RegisteredAgent.UnLock;
    end;

    // ---- Add new tool if not found ----
    if not found then
      DoStatus('[register_agent] Added new tool: %s "%s"', [Name, jo.S['description']])
    else
      DoStatus('[register_agent] Updated existing tool: %s "%s"', [Name, jo.S['description']]);

    // ---- Return success ----
    jo.Clear;
    jo.S['status'] := 'ok';
    LF_WriteStringBytes(TDataHnd(Output), jo.ToBytes);
  except
    on E: Exception do
    begin
      // Unexpected error – log and return error JSON, but do not re‑raise
      DoStatus('[register_agent] Exception: %s', [E.Message]);
      jo.Clear;
      jo.S['status'] := 'error';
      jo.S['message'] := 'Internal error: ' + E.Message;
      LF_WriteString(TDataHnd(Output), jo.ToJSONString(False).Text);
    end;
  end;
  jo.Free;
end;

// ============================================================================
// 2. Main Program
// ============================================================================
var
  App: LF.TAppHandle;
  Running, IsRunning: boolean;

procedure Wait_Input();
var
  S: string;
begin
  while Running do
  begin
    ReadLn(S);
    if umlMultipleMatch('exit', S) then
      Break;
  end;
end;

begin
  // Create the registered agent storage
  RegisteredAgent := TRegisteredAgent.Create;

  // Create the LingoFuse application
  App := LF.TAppHandle.Create(APP_NAME, APP_DESC);
  DoStatus('[MAIN] Application "%s" created.', [APP_NAME]);

  // Register the three APIs
  App.RegisterCall('agent_log', 'Logging tool', nil, @do_agent_log);
  App.RegisterCall('agent_main', 'Tool list entry', nil, @do_agent_main);
  App.RegisterCall('register_agent', 'Dynamic tool registration', nil, @do_register_agent);
  DoStatus('[MAIN] Registered APIs: agent_log, agent_main, register_agent');

  // Configure LingoFuse options
  LF.SetOption('WaitConnect', 'True');
  DoStatus('[MAIN] Set WaitConnect=True');

  // Reset preparation and start services and clients
  LF.ResetPrepare;
  DoStatus('[MAIN] Preparing IPC service on %s', [IPC_ENDPOINT]);
  LF.PrepareService(IPC_ENDPOINT, IPC_ENDPOINT);
  DoStatus('[MAIN] Preparing TCP service on %s (public %s)', [TCP_LISTEN_ADDR, TCP_PUBLIC_ADDR]);
  LF.PrepareService(TCP_LISTEN_ADDR, TCP_PUBLIC_ADDR);

  // Connect locally to both endpoints to expose the app
  DoStatus('[MAIN] Connecting local IPC client to %s', [IPC_ENDPOINT]);
  LF.PrepareClient(IPC_ENDPOINT, App);
  DoStatus('[MAIN] Connecting local TCP client to %s', [TCP_PUBLIC_ADDR]);
  LF.PrepareClient(TCP_PUBLIC_ADDR, App);

  // Start the LingoFuse framework
  DoStatus('[MAIN] Starting framework...');
  LF.PrepareDone;
  DoStatus('[MAIN] Framework started successfully.');

  // Start input thread to wait for 'exit'
  Running := True;
  TCompute.RunC_NP(Wait_Input, @IsRunning, nil);
  DoStatus('[MAIN] Service is running. Type "exit" to quit.');

  // Main loop – just wait for the input thread to finish
  while IsRunning do
    TCompute.Sleep(100);

  // Cleanup
  DoStatus('[MAIN] Shutting down...');
  LF.ExitMainThread;
  LF.Shutdown;
  App.Free;
  DisposeObjectAndNil(RegisteredAgent);
  DoStatus('[MAIN] Cleanup complete.');
end.
