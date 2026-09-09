unit frmNewRecord_tool_provider_unit;

{$ifdef FPC}
  {$mode delphi}
  {$modeswitch advancedrecords}
  {$CODEPAGE UTF8}
{$endif}
{$H+}

interface

uses
  SysUtils, Classes,
  lingofuse_import, frmNewRecord;

// ---- Exported global var ----
var
  MY_APP_NAME : string = 'frmNewRecord';
  MY_APP_DESC : string = 'Tool provider for unit frmNewRecord';
  IPC_ENDPOINT : string = 'ipc:agent';
  BEACON_APP : string = 'agent_main_app';
  REGISTER_API : string = 'register_agent';
  AGENT_LOG_API : string = 'agent_log';
  DEBUG_LOG : boolean = True;

// ---- Exported functions ----
{*
 * RegisterAPIs – Creates the LingoFuse application and registers all
 * generated Call APIs. Returns the application handle, or nil on failure.
 * The caller is responsible for freeing the handle with LF_FreeApp.
 *}
function RegisterAPIs: TAppHnd___;

{*
 * RegisterTools – Connects to the beacon, registers all APIs as tools
 * with JSON schemas, and returns True if all registrations succeeded.
 *}
function RegisterTools: Boolean;

implementation

uses
  Z.Core, Z.Json, Z.PascalStrings, Z.UPascalStrings, Z.Status, Z.UnicodeMixedLib, Z.ListEngine;


function RegisterTool(const ToolDef: TZ_JsonObject): boolean; forward;
procedure Callback_FillRecord_FillRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl; forward;
procedure Callback_NewRecord_NewRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl; forward;
procedure Callback_SaveRecord_SaveRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl; forward;

// ---- Internal wrapper for FillRecord ----
function internal_call_FillRecord_FillRecord(AName: string; AAge: string; AGender: string; ABirth: string; AID: string; APhone: string; AAddress: string; ATemp: string; ASBP: string; ADBP: string; AHeartRate: string; ASymptoms: string; AHistory: string; AAllergy: string; AContact: string; ARemark: string): string;
begin
  Result := frmNewRecord.FillRecord(AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate, ASymptoms, AHistory, AAllergy, AContact, ARemark);
end;

// ---- Internal wrapper for NewRecord ----
function internal_call_NewRecord_NewRecord(): int64;
begin
  Result := frmNewRecord.NewRecord();
  // call type: Result := internal_call_NewRecord_NewRecord();
end;

// ---- Internal wrapper for SaveRecord ----
function internal_call_SaveRecord_SaveRecord(): string;
begin
  Result := frmNewRecord.SaveRecord();
  // call type: Result := internal_call_SaveRecord_SaveRecord();
end;

{$Region 'internal_'}
function ret2str(v: Int64): string; overload;
begin
  Result := IntToStr(v);
end;

function ret2str(v: Double): string; overload;
begin
  Result := FloatToStr(v);
end;

function ret2str(const v: string): string; overload;
begin
  Result := v;
end;

// ---- Asynchronous logging to beacon ----
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
      LF_WriteStringBytes(Data, jo.ToBytes);
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

{$EndRegion 'internal_'}
{$Region 'callback_'}
// ---- FillRecord (API: FillRecord) ----
procedure Callback_FillRecord_FillRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl;
var
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  AName: string;
  AAge: string;
  AGender: string;
  ABirth: string;
  AID: string;
  APhone: string;
  AAddress: string;
  ATemp: string;
  ASBP: string;
  ADBP: string;
  AHeartRate: string;
  ASymptoms: string;
  AHistory: string;
  AAllergy: string;
  AContact: string;
  ARemark: string;
  ret: string;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(_In___));
    if DEBUG_LOG then
      DoStatus('[FillRecord] Input JSON: %s', [TEncoding.UTF8.GetString(jsonBytes)]);

    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[FillRecord] Error: %s', [errMsg]);
        SendLogAsync('[FillRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[FillRecord] Error: %s', [errMsg]);
        SendLogAsync('[FillRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    AName := jo.S['AName'];
    AAge := jo.S['AAge'];
    AGender := jo.S['AGender'];
    ABirth := jo.S['ABirth'];
    AID := jo.S['AID'];
    APhone := jo.S['APhone'];
    AAddress := jo.S['AAddress'];
    ATemp := jo.S['ATemp'];
    ASBP := jo.S['ASBP'];
    ADBP := jo.S['ADBP'];
    AHeartRate := jo.S['AHeartRate'];
    ASymptoms := jo.S['ASymptoms'];
    AHistory := jo.S['AHistory'];
    AAllergy := jo.S['AAllergy'];
    AContact := jo.S['AContact'];
    ARemark := jo.S['ARemark'];

    ret := internal_call_FillRecord_FillRecord(AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate, ASymptoms, AHistory, AAllergy, AContact, ARemark);
    jo.Clear;
    jo.S['result'] := ret;
    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
    if DEBUG_LOG then
    begin
      DoStatus('[FillRecord] called with %s -> result: %s', [AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate, ASymptoms, AHistory, AAllergy, AContact, ARemark, ret2str(ret)]);
      SendLogAsync(PFormat('[FillRecord] called with %s', [AName, AAge, AGender, ABirth, AID, APhone, AAddress, ATemp, ASBP, ADBP, AHeartRate, ASymptoms, AHistory, AAllergy, AContact, ARemark]) + ' -> result: ' + ret2str(ret));
    end;
  except
    on E: Exception do
    begin
      jo.Clear;
      jo.S['error'] := E.Message;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[FillRecord] Exception: %s', [E.Message]);
        SendLogAsync('[FillRecord] Exception: ' + E.Message);
      end;
    end;
  end;
  jo.Free;
end;

// ---- NewRecord (API: NewRecord) ----
procedure Callback_NewRecord_NewRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl;
var
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  ret: int64;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(_In___));
    if DEBUG_LOG then
      DoStatus('[NewRecord] Input JSON: %s', [TEncoding.UTF8.GetString(jsonBytes)]);

    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[NewRecord] Error: %s', [errMsg]);
        SendLogAsync('[NewRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[NewRecord] Error: %s', [errMsg]);
        SendLogAsync('[NewRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    // No parameters
    ret := internal_call_NewRecord_NewRecord();
    jo.Clear;
    jo.I64['result'] := ret;
    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
    if DEBUG_LOG then
    begin
      DoStatus('[NewRecord] called (no params) -> result: %s', [ret2str(ret)]);
      SendLogAsync('[NewRecord] called (no params) -> result: ' + ret2str(ret));
    end;
  except
    on E: Exception do
    begin
      jo.Clear;
      jo.S['error'] := E.Message;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[NewRecord] Exception: %s', [E.Message]);
        SendLogAsync('[NewRecord] Exception: ' + E.Message);
      end;
    end;
  end;
  jo.Free;
end;

// ---- SaveRecord (API: SaveRecord) ----
procedure Callback_SaveRecord_SaveRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl;
var
  jsonBytes: TBytes;
  jo: TZ_JsonObject;
  ret: string;
  errMsg: string;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(_In___));
    if DEBUG_LOG then
      DoStatus('[SaveRecord] Input JSON: %s', [TEncoding.UTF8.GetString(jsonBytes)]);

    if Length(jsonBytes) = 0 then
    begin
      errMsg := 'Empty input';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[SaveRecord] Error: %s', [errMsg]);
        SendLogAsync('[SaveRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    if not jo.Parae(jsonBytes) then
    begin
      errMsg := 'Invalid JSON';
      jo.Clear;
      jo.S['error'] := errMsg;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[SaveRecord] Error: %s', [errMsg]);
        SendLogAsync('[SaveRecord] Error: ' + errMsg);
      end;
      Exit;
    end;
    // No parameters
    ret := internal_call_SaveRecord_SaveRecord();
    jo.Clear;
    jo.S['result'] := ret;
    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
    if DEBUG_LOG then
    begin
      DoStatus('[SaveRecord] called (no params) -> result: %s', [ret2str(ret)]);
      SendLogAsync('[SaveRecord] called (no params) -> result: ' + ret2str(ret));
    end;
  except
    on E: Exception do
    begin
      jo.Clear;
      jo.S['error'] := E.Message;
      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
      if DEBUG_LOG then
      begin
        DoStatus('[SaveRecord] Exception: %s', [E.Message]);
        SendLogAsync('[SaveRecord] Exception: ' + E.Message);
      end;
    end;
  end;
  jo.Free;
end;

{$EndRegion 'callback_'}
// -----------------------------------------------------------------------------
// Register a single tool with the beacon using LF_WriteStringBytes / LF_ReadStringBytes
// The tool definition is sent as a JSON object to the "register_agent" API.
// Returns True on success, False on failure.
// -----------------------------------------------------------------------------
function RegisterTool(const ToolDef: TZ_JsonObject): boolean;
var
  Data, ResultHnd: TDataHnd___;
  jsonBytes: TBytes;
  RespJson: TZ_JsonObject;
  toolName, toolDesc, targetApp, targetApi: string;
begin
  Result := False;
  // Extract key fields for logging
  toolName := ToolDef.S['name'];
  toolDesc := ToolDef.S['description'];
  targetApp := ToolDef.S['target_app'];
  targetApi := ToolDef.S['target_api'];
  if DEBUG_LOG then
    DoStatus('[RegisterTool] Registering tool: %s -> %s.%s', [toolName, targetApp, targetApi]);

  Data := LF_CreateDataEx(REGISTER_API);
  try
    LF_WriteStringBytes(Data, ToolDef.ToBytes);
    ResultHnd := LF_CallEx(BEACON_APP, Data, 5000);
    try
      jsonBytes := LF_ReadStringBytes(ResultHnd);
      if Length(jsonBytes) > 0 then
      begin
        RespJson := TZ_JsonObject.Create;
        try
          RespJson.Parae(jsonBytes);
          if RespJson.Exists('status') and (RespJson.S['status'] = 'ok') then
          begin
            Result := True;
            if DEBUG_LOG then
              DoStatus('[RegisterTool] Tool "%s" registered successfully.', [toolName]);
          end
          else
          begin
            if DEBUG_LOG then
              DoStatus('[RegisterTool] Server returned error: %s', [RespJson.S['message']]);
          end;
        finally
          RespJson.Free;
        end;
      end
      else
        if DEBUG_LOG then
          DoStatus('[RegisterTool] Empty response from beacon (timeout or network error)');
    finally
      LF_FreeData(ResultHnd);
    end;
  finally
    LF_FreeData(Data);
  end;
end;

// ---- RegisterTools implementation ----
function RegisterTools: Boolean;
var
  ToolDef: TZ_JsonObject;
  ParamsObj, PropsObj, PropObj: TZ_JsonObject;
  RequiredArr: TZ_JsonArray;
  Success: boolean;
  regCount: integer;
begin
  Result := False;
  regCount := 0;
  // Check if the beacon is reachable
  if DEBUG_LOG then
    DoStatus('[RegisterTools] Checking beacon availability: app=%s api=%s', [BEACON_APP, REGISTER_API]);
  if not LF_CheckApiEx(BEACON_APP, REGISTER_API) then
  begin
    DoStatus('[RegisterTools] Beacon not available. Please ensure pascal_agent_service is running.');
    exit;
  end;
  if DEBUG_LOG then
    DoStatus('[RegisterTools] Beacon is available. Starting tool registration...');
  try
    // Tool: FillRecord -> FillRecord
    ToolDef := TZ_JsonObject.Create;
    try
      ToolDef.S['name'] := 'FillRecord';
      ToolDef.S['description'] := '{ 填充新建健康记录表单的所有字段，并返回姓名,如果返回空就是没有执行NewRecord. AName:姓名 AAge:年龄 AGender:性别（"男" / "女"） ABirth:出生日期（字符串形式，如 "1990-01-01"） AID:身份证号 APhone:电话 AAddress:地址 ATemp:体温（字符串，如 "36.5"） ASBP:收缩压（字符串） ADBP:舒张压（字符串） AHeartRate:心率（字符串） ASymptoms:症状（多行文本） AHistory:既往病史（多行文本） AAllergy:过敏史 AContact:紧急联系人 ARemark:备注（多行文本） }';
      ToolDef.S['target_app'] := MY_APP_NAME;
      ToolDef.S['target_api'] := 'FillRecord';

      ParamsObj := ToolDef.O['parameters'];
      ParamsObj.S['type'] := 'object';
      PropsObj := ParamsObj.O['properties'];
      PropObj := PropsObj.O['AName'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '姓名'#13;
      PropObj := PropsObj.O['AAge'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '年龄'#13;
      PropObj := PropsObj.O['AGender'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '性别（"男" / "女"）'#13;
      PropObj := PropsObj.O['ABirth'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '出生日期（字符串形式，如 "1990-01-01"）'#13;
      PropObj := PropsObj.O['AID'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '身份证号'#13;
      PropObj := PropsObj.O['APhone'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '电话'#13;
      PropObj := PropsObj.O['AAddress'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '地址'#13;
      PropObj := PropsObj.O['ATemp'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '体温（字符串，如 "36.5"）'#13;
      PropObj := PropsObj.O['ASBP'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '收缩压（字符串）'#13;
      PropObj := PropsObj.O['ADBP'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '舒张压（字符串）'#13;
      PropObj := PropsObj.O['AHeartRate'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '心率（字符串）'#13;
      PropObj := PropsObj.O['ASymptoms'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '症状（多行文本）'#13;
      PropObj := PropsObj.O['AHistory'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '既往病史（多行文本）'#13;
      PropObj := PropsObj.O['AAllergy'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '过敏史'#13;
      PropObj := PropsObj.O['AContact'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '紧急联系人'#13;
      PropObj := PropsObj.O['ARemark'];
      PropObj.S['type'] := 'string';
      PropObj.S['description'] := '备注（多行文本）';
      RequiredArr := ParamsObj.a['required'];
      RequiredArr.Add('AName');
      RequiredArr.Add('AAge');
      RequiredArr.Add('AGender');
      RequiredArr.Add('ABirth');
      RequiredArr.Add('AID');
      RequiredArr.Add('APhone');
      RequiredArr.Add('AAddress');
      RequiredArr.Add('ATemp');
      RequiredArr.Add('ASBP');
      RequiredArr.Add('ADBP');
      RequiredArr.Add('AHeartRate');
      RequiredArr.Add('ASymptoms');
      RequiredArr.Add('AHistory');
      RequiredArr.Add('AAllergy');
      RequiredArr.Add('AContact');
      RequiredArr.Add('ARemark');
      Success := RegisterTool(ToolDef);
      if Success then Inc(regCount);
      if DEBUG_LOG then
        if Success then
          DoStatus('[RegisterTools] OK: FillRecord')
        else
          DoStatus('[RegisterTools] FAIL: FillRecord');
    finally
      ToolDef.Free;
    end;

    // Tool: NewRecord -> NewRecord
    ToolDef := TZ_JsonObject.Create;
    try
      ToolDef.S['name'] := 'NewRecord';
      ToolDef.S['description'] := '{ 打开健康记录输入表单，返回1表示成功,返回0表示打开无效. }';
      ToolDef.S['target_app'] := MY_APP_NAME;
      ToolDef.S['target_api'] := 'NewRecord';

      ParamsObj := ToolDef.O['parameters'];
      ParamsObj.S['type'] := 'object';
      PropsObj := ParamsObj.O['properties'];
      Success := RegisterTool(ToolDef);
      if Success then Inc(regCount);
      if DEBUG_LOG then
        if Success then
          DoStatus('[RegisterTools] OK: NewRecord')
        else
          DoStatus('[RegisterTools] FAIL: NewRecord');
    finally
      ToolDef.Free;
    end;

    // Tool: SaveRecord -> SaveRecord
    ToolDef := TZ_JsonObject.Create;
    try
      ToolDef.S['name'] := 'SaveRecord';
      ToolDef.S['description'] := '{ 保存健康记录表单为Json，并返回json数据。 }';
      ToolDef.S['target_app'] := MY_APP_NAME;
      ToolDef.S['target_api'] := 'SaveRecord';

      ParamsObj := ToolDef.O['parameters'];
      ParamsObj.S['type'] := 'object';
      PropsObj := ParamsObj.O['properties'];
      Success := RegisterTool(ToolDef);
      if Success then Inc(regCount);
      if DEBUG_LOG then
        if Success then
          DoStatus('[RegisterTools] OK: SaveRecord')
        else
          DoStatus('[RegisterTools] FAIL: SaveRecord');
    finally
      ToolDef.Free;
    end;

    Result := (regCount = 3);
    if DEBUG_LOG then
      DoStatus('[RegisterTools] Registered %d out of %d tools.', [regCount, 3]);
  finally
  end;
end;

// ---- RegisterAPIs implementation ----
function RegisterAPIs: TAppHnd___;
var
  App: TAppHnd___;
begin
  Result := nil;
  App := LF_CreateAppEx(MY_APP_NAME, MY_APP_DESC);
  if DEBUG_LOG then
    DoStatus('[RegisterAPIs] Application "%s" created.', [MY_APP_NAME]);

  LF_RegisterCallEx(App, 'FillRecord', '{ 填充新建健康记录表单的所有字段，并返回姓名,如果返回空就是没有执行NewRecord. AName:姓名 AAge:年龄 AGender:性别（"男" / "女"） ABirth:出生日期（字符串形式，如 "1990-01-01"） AID:身份证号 APhone:电话 AAddress:地址 ATemp:体温（字符串，如 "36.5"） ASBP:收缩压（字符串） ADBP:舒张压（字符串） AHeartRate:心率（字符串） ASymptoms:症状（多行文本） AHistory:既往病史（多行文本） AAllergy:过敏史 AContact:紧急联系人 ARemark:备注（多行文本） }', nil, @Callback_FillRecord_FillRecord);  // Register API: FillRecord -> FillRecord
  LF_RegisterCallEx(App, 'NewRecord', '{ 打开健康记录输入表单，返回1表示成功,返回0表示打开无效. }', nil, @Callback_NewRecord_NewRecord);  // Register API: NewRecord -> NewRecord
  LF_RegisterCallEx(App, 'SaveRecord', '{ 保存健康记录表单为Json，并返回json数据。 }', nil, @Callback_SaveRecord_SaveRecord);  // Register API: SaveRecord -> SaveRecord
  if DEBUG_LOG then
    DoStatus('[RegisterAPIs] Registered APIs: 3 functions');
  Result := App;
end;

end.
