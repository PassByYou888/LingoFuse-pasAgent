unit llm_client;

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\zNetV2\source\Z.Define.inc}
interface

uses
  Classes, SysUtils, SyncObjs,
  lingofuse_helper, lingofuse_import,
  Z.Core, Z.Json, Z.PascalStrings, Z.UPascalStrings, Z.Status;

type
  TLLMChunkEvent = procedure(const Chunk: string) of object;
  TLLMFinishEvent = procedure of object;
  TLLMErrorEvent = procedure(const ErrorMsg: string) of object;

  TLLMClient = class
  private
    FApp: LF.TAppHandle;
    FServerApp: string;
    FEndpoint: string;
    FTimeout: integer;
    FConnected: boolean;
    FCurrentSessionId: string;
    FClientName: string;             // Dynamically generated unique name

    FOnChunk: TLLMChunkEvent;
    FOnFinish: TLLMFinishEvent;
    FOnError: TLLMErrorEvent;

    procedure OnLLMStream(Input_: TDataHnd___);
    procedure DoChunk(const Chunk: string);
    procedure DoFinish;
    procedure DoError(const ErrorMsg: string);
  public
    constructor Create(const AServerApp, AEndpoint: string; ATimeout: integer = 10000);
    destructor Destroy; override;

    // Connect to the LingoFuse service, returns True on success.
    // On failure, ErrorMsg contains the reason and FConnected remains False.
    function Connect(out ErrorMsg: string): boolean;
    procedure Disconnect;

    // Generate API – returns session_id on success, ErrorMsg on failure.
    function Generate(const AContent, APrompt: string; out ASessionId, AError: string): boolean;
    function SetSystemMessage(const AMessage: string; out AError: string): boolean;

    // Events (all callbacks are executed on the main thread)
    property OnChunk: TLLMChunkEvent read FOnChunk write FOnChunk;
    property OnFinish: TLLMFinishEvent read FOnFinish write FOnFinish;
    property OnError: TLLMErrorEvent read FOnError write FOnError;
  end;

implementation

{ TLLMClient }

constructor TLLMClient.Create(const AServerApp, AEndpoint: string; ATimeout: integer);
begin
  FServerApp := AServerApp;
  FEndpoint := AEndpoint;
  FTimeout := ATimeout;
  FConnected := False;
  FApp := nil;
  FClientName := '';
  FCurrentSessionId := '';
end;

destructor TLLMClient.Destroy;
begin
  Disconnect;
  inherited;
end;

function TLLMClient.Connect(out ErrorMsg: string): boolean;
begin
  Result := False;
  ErrorMsg := '';
  if FConnected then
  begin
    Result := True;
    Exit;
  end;

  try
    // Step 1: Prepare network connection WITHOUT binding an App
    LF.ResetPrepare;

    // Explicitly set Wait_Connection_ReadyOk to True to block PrepareDone
    // until the client is fully ready.
    LF.SetOption('Wait_Connection_ReadyOk', 'True');
    LF.SetOption('Overlap_Connection', 'True');

    // Prepare client with no App attached
    if LF.PrepareClient(FEndpoint, nil) = -1 then
    begin
      ErrorMsg := 'LF.PrepareClient failed (address may be invalid or already in use)';
      Exit;
    end;

    if not LF.PrepareDone then
    begin
      ErrorMsg := 'LF.PrepareDone failed (network initialization error)';
      Exit;
    end;

    // Step 2: Generate a unique client name NOW (after connection is up)
    FClientName := LF.Generate_AppName;
    if FClientName = '' then
    begin
      ErrorMsg := 'LF.Generate_AppName returned an empty string';
      Exit;
    end;

    // Step 3: Create App with that name and register notify callback
    FApp := LF.TAppHandle.Create(FClientName, 'Dynamic LLM Client');
    if not FApp.RegisterNotifySync('llm_stream', 'llm同步事件', OnLLMStream) then
    begin
      ErrorMsg := 'Failed to register notify callback for llm_stream';
      Exit;
    end;

    // Step 4: Bind the App to the existing client
    if FApp.Bind = 0 then
    begin
      ErrorMsg := 'LF_BindApp failed – no free client available (all clients already occupied)';
      Exit;
    end;

    FConnected := True;
    Result := True;
  except
    on E: Exception do
    begin
      ErrorMsg := 'Unexpected exception in Connect: ' + E.Message;
      FConnected := False;
      Result := False;
    end;
  end;
end;

procedure TLLMClient.Disconnect;
begin
  if not FConnected then Exit;
  LF.ExitMainThread;
  if FApp <> nil then
  begin
    FApp.Free;
    FApp := nil;
  end;
  FConnected := False;
  FClientName := '';
  FCurrentSessionId := '';
end;

procedure TLLMClient.OnLLMStream(Input_: TDataHnd___);
var
  jstr: TZ_JsonString;
  jo: TZ_JsonObject;
  session_id, Chunk: TZ_JsonString;
begin
  jstr.ReadUTF8AnsiChar(LF___.LF_GetBuffer(Input_), LF___.LF_GetSize(Input_));
  jo := TZ_JsonObject.Create;
  try
    if not jo.ParseText(jstr.Text) then Exit;
    session_id := jo.S['session_id'];
    if session_id <> FCurrentSessionId then Exit;
    Chunk := jo.S['chunk'];
  finally
    jo.Free;
  end;

  if Chunk = '__FINISH__' then
    DoFinish()
  else if Chunk.GetPos('__ERROR__') > 0 then
    DoError(Chunk)
  else
    DoChunk(Chunk);
end;

procedure TLLMClient.DoChunk(const Chunk: string);
begin
  if Assigned(FOnChunk) then FOnChunk(Chunk);
end;

procedure TLLMClient.DoFinish;
begin
  if Assigned(FOnFinish) then FOnFinish;
end;

procedure TLLMClient.DoError(const ErrorMsg: string);
begin
  if Assigned(FOnError) then FOnError(ErrorMsg);
end;

function TLLMClient.Generate(const AContent, APrompt: string; out ASessionId, AError: string): boolean;
var
  ReqJSON, RespJSON: TUPascalString;
  jo: TZ_JsonObject;
  hnd, res: TDataHnd;
  code: integer;
begin
  Result := False;
  ASessionId := '';
  AError := '';
  if not FConnected then
  begin
    AError := 'Not connected to LingoFuse service';
    Exit;
  end;

  // Build request JSON including client_name
  jo := TZ_JsonObject.Create;
  try
    jo.S['content'] := AContent;
    jo.S['prompt'] := APrompt;
    jo.S['client_name'] := FClientName;
    ReqJSON := jo.ToJSONString(False);
  finally
    jo.Free;
  end;

  hnd := LF_CreateDataEx('generate');
  try
    LF_WriteString(hnd, ReqJSON);
    res := LF_CallEx(FServerApp, hnd, FTimeout);
    if res = nil then
    begin
      AError := 'Call returned nil (timeout or network error)';
      Exit;
    end;
    try
      LF_SetPos(res, 0);
      RespJSON.UTF8 := LF_ReadStringBytes(res);
      if RespJSON = '' then
      begin
        AError := 'Empty response';
        Exit;
      end;
      jo := TZ_JsonObject.Create;
      try
        if not jo.ParseText(RespJSON) then
        begin
          AError := 'Invalid JSON response';
          Exit;
        end;
        // Check error code
        if jo.Exists('code') then
        begin
          code := jo.I['code'];
          if code <> 0 then
          begin
            if jo.Exists('error') then
              AError := jo.S['error']
            else
              AError := 'Unknown error (code ' + IntToStr(code) + ')';
            Exit;
          end;
        end;
        // Extract session_id
        ASessionId := jo.S['session_id'];
        if ASessionId = '' then
        begin
          AError := 'Missing session_id in response';
          Exit;
        end;
        FCurrentSessionId := ASessionId;
        Result := True;
      finally
        jo.Free;
      end;
    finally
      LF_FreeData(res);
    end;
  finally
    LF_FreeData(hnd);
  end;
end;

function TLLMClient.SetSystemMessage(const AMessage: string; out AError: string): boolean;
var
  ReqJSON, RespJSON: TUPascalString;
  jo: TZ_JsonObject;
  hnd, res: TDataHnd;
  code: integer;
begin
  Result := False;
  AError := '';
  if not FConnected then
  begin
    AError := 'Not connected to LingoFuse service';
    Exit;
  end;

  jo := TZ_JsonObject.Create;
  try
    jo.S['content'] := AMessage;
    ReqJSON := jo.ToJSONString(False);
  finally
    jo.Free;
  end;

  hnd := LF_CreateDataEx('set_system_message');
  try
    LF_WriteString(hnd, ReqJSON);
    res := LF_CallEx(FServerApp, hnd, FTimeout);
    if res = nil then
    begin
      AError := 'Call returned nil (timeout or network error)';
      Exit;
    end;
    try
      LF_SetPos(res, 0);
      RespJSON := LF_ReadString(res);
      if RespJSON = '' then
      begin
        AError := 'Empty response';
        Exit;
      end;
      jo := TZ_JsonObject.Create;
      try
        if not jo.ParseText(RespJSON) then
        begin
          AError := 'Invalid JSON response';
          Exit;
        end;
        if jo.Exists('code') then
        begin
          code := jo.I['code'];
          if code = 0 then
            Result := True
          else
          begin
            if jo.Exists('error') then
              AError := jo.S['error']
            else
              AError := 'Unknown error (code ' + IntToStr(code) + ')';
          end;
        end
        else
        begin
          // No code field – treat as success (legacy compatibility)
          Result := True;
        end;
      finally
        jo.Free;
      end;
    finally
      LF_FreeData(res);
    end;
  finally
    LF_FreeData(hnd);
  end;
end;

end.
