unit pas_mcp_generator_tool;

{*******************************************************************************
 * pas_mcp_generator_tool – LingoFuse Tool Provider Code Generator
 *
 * This unit consumes a TPascal_Func_Model (extracted from Pascal source) and
 * produces a complete Pascal unit that can be compiled into a LingoFuse
 * tool provider. The generated unit exposes two functions:
 *
 *   - RegisterAPIs: creates a LingoFuse application, registers all supported
 *     Pascal functions as Call APIs, and returns the application handle.
 *
 *   - RegisterTools: connects to the beacon, registers each API as a tool
 *     with a JSON schema, and returns True on success.
 *
 * The generated code uses LF_ReadStringBytes / LF_WriteStringBytes for
 * zero‑copy, null‑terminated byte string I/O, consistent with LingoFuse
 * service examples. All LingoFuse API calls are made via lingofuse_import
 * (the low‑level C‑ABI bindings) with the "Ex" string‑convenience wrappers.
 *
 * =============================================================================
 * USAGE
 * =============================================================================
 *   var
 *     Model: TPascal_Func_Model;
 *     Code: TPascalStringList;
 *   begin
 *     Model := TPascal_Func_Model.Create;
 *     Model.LoadFromParser(Parser);   // Populate from parsed source
 *     Code := GenerateCode(Model);
 *     if Code <> nil then
 *     begin
 *       Code.SaveToFile('my_provider.pas');
 *       Code.Free;
 *     end;
 *     Model.Free;
 *   end;
 *
 * =============================================================================
 * NOTES
 * =============================================================================
 *   - The generated unit uses a fixed beacon application name
 *     ('agent_main_app') and IPC endpoint ('ipc:agent').
 *   - Nested routines (NestLevel <> 0) are skipped.
 *   - All user‑supplied callbacks are executed on LingoFuse worker threads;
 *     the generated code logs execution and errors asynchronously.
 * ****************************************************************************}
{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\zNetV2\source\Z.Define.inc}

interface

uses
  Z.Core,
  Z.PascalStrings, Z.UPascalStrings,
  Z.Status, Z.Json, Z.UnicodeMixedLib, Z.ListEngine,
  Z.Pascal_Func_Model,   // TPascal_Func_Model, TFunctionStructure, TParamArray
  Z.Parsing;             // For TTextParsing.Translate_Text_To_Pascal_Decl

{*
 * GenerateCode – Main entry point.
 *
 * @param Model   The TPascal_Func_Model containing the extracted functions.
 * @return        A TPascalStringList containing the generated source lines,
 *                or nil on error. The caller is responsible for freeing the list.
 *}
function GenerateCode(Model: TPascal_Func_Model): TPascalStringList;

const
  // Enable/disable logging during generation.
  GenerateCode_LogEnabled: boolean = False;

implementation

// -----------------------------------------------------------------------------
// Local logging helper
// -----------------------------------------------------------------------------

procedure Log(const Msg: TP_String);
begin
  if GenerateCode_LogEnabled then
    DoStatus('[pas_mcp_generator] %s', [Msg.Text]);
end;

// -----------------------------------------------------------------------------
// Type support check
// -----------------------------------------------------------------------------

function IsSupportedType(const Typ: TP_String): boolean;
begin
  Result := Typ.Same('int64', 'double', 'string');
end;

// -----------------------------------------------------------------------------
// Naming helpers for generated symbols
// -----------------------------------------------------------------------------

function MakeApiName(const FuncName: TP_String): TP_String;
begin
  // Replace characters that are not valid in Pascal identifiers
  Result := FuncName.ReplaceChar(#32#9'./\@', '_');
end;

function MakeCallbackName(const FuncName: TP_String): TP_String;
begin
  Result := 'Callback_' + MakeApiName(FuncName);
end;

function MakeInternalCallName(const FuncName: TP_String): TP_String;
begin
  Result := 'internal_call_' + MakeApiName(FuncName);
end;

// -----------------------------------------------------------------------------
// Helper to produce a Pascal string literal using the Z framework
// -----------------------------------------------------------------------------

function PascalStrLit(const S: TP_String): TP_String;
begin
  // Translate_Text_To_Pascal_Decl returns a quoted Pascal string literal,
  // e.g. 'Hello' or 'Hello'#13#10'World'. We use it directly in code generation.
  Result := TTextParsing.Translate_Text_To_Pascal_Decl(S);
end;

// -----------------------------------------------------------------------------
// Comment description extraction
// -----------------------------------------------------------------------------

function GetFullDescription(const Comment: TP_String): TP_String;
var
  Lines: TPascalStringList;
  i: integer;
  Line: TP_String;
begin
  Result := '';
  if Comment = '' then
    Exit;

  Lines := TPascalStringList.Create;
  try
    Lines.AsText := Comment;
    for i := 0 to Lines.Count - 1 do
    begin
      Line := TP_String(Lines[i]);
      Line := Line.TrimChar(#32#9);
      if Line.Len = 0 then
        Continue;
      // Skip Doxygen tags
      if Line[1] = '@' then
        Continue;
      // Remove leading '*' and possibly another '*'
      if Line[1] = '*' then
        Line := Line.GetString(2, Line.Len + 1).TrimChar(#32#9);
      if Line.Len > 0 then
        if Line[1] = '*' then
          Line := Line.GetString(2, Line.Len + 1).TrimChar(#32#9);
      if Line <> '' then
      begin
        if Result <> '' then
          Result := Result + ' ';
        Result := Result + Line;
      end;
    end;
  finally
    Lines.Free;
  end;
end;

// -----------------------------------------------------------------------------
// Main code generator – generates a unit with RegisterAPIs and RegisterTools
// -----------------------------------------------------------------------------

function GenerateCode(Model: TPascal_Func_Model): TPascalStringList;
type
  TArryFunctionStructure = array of TFunctionStructure;

// ----- Helper: collect supported functions -----
  function CollectSupportedFunctions: TArryFunctionStructure;
  var
    i, j: integer;
    f: TFunctionStructure;
    Supported: boolean;
  begin
    SetLength(Result, 0);
    for i := 0 to Model.Funcs.Count - 1 do
    begin
      f := Model.Funcs[i];
      Supported := True;
      // Check all parameters
      for j := 0 to High(f.Params) do
        if not IsSupportedType(f.Params[j].PascalType) then
        begin
          Supported := False;
          Log(PFormat('Skipped "%s": param "%s" has unsupported type "%s"', [f.Name.Text, f.Params[j].Name.Text,
            f.Params[j].PascalType.Text]));
          Break;
        end;
      // Check return type for functions
      if Supported and f.IsFunction and not IsSupportedType(f.ReturnType) then
      begin
        Supported := False;
        Log(PFormat('Skipped "%s": return type "%s" unsupported', [f.Name.Text, f.ReturnType.Text]));
      end;
      if Supported then
      begin
        SetLength(Result, Length(Result) + 1);
        Result[High(Result)] := f;
      end;
    end;
  end;

  // ----- Helpers for building parameter strings -----
  function BuildParamDecl(const Params: TParamArray): TP_String;
  var
    i: integer;
  begin
    Result := '';
    for i := 0 to High(Params) do
    begin
      if i > 0 then Result := Result + '; ';
      Result := Result + Params[i].Name + ': ' + Params[i].PascalType;
    end;
  end;

  function BuildArgList(const Params: TParamArray): TP_String;
  var
    i: integer;
  begin
    Result := '';
    for i := 0 to High(Params) do
    begin
      if i > 0 then Result := Result + ', ';
      Result := Result + Params[i].Name;
    end;
  end;

var
  i, j: integer;
  SupportedFuncs: array of TFunctionStructure;
  UnitName, AppName, BeaconApp, RegisterApi, AgentLogApi, IpcEndpoint: TP_String;
  UsedApiNames: TPascalStringList;
  ApiName, CallbackName, InternalCallName: TP_String;
  ExtractCode, CallArgs: TP_String;
  Description: TP_String;
  ParamName: TP_String;

  // ---- Line builders (TPascalStringList) ----
  HeaderLines: TPascalStringList;
  InterfaceLines: TPascalStringList;
  UsesLines: TPascalStringList;
  ForwardLines: TPascalStringList;
  InternalCallLines: TPascalStringList;   // will hold the internal call wrappers
  Ret2StrLines: TPascalStringList;
  LoggingLines: TPascalStringList;
  CallbackLines: TPascalStringList;
  RegisterToolLines: TPascalStringList;
  RegisterAPIsLines: TPascalStringList;
  ExecuteLines: TPascalStringList;
  ResultLines: TPascalStringList;
begin
  Result := nil;
  if Model = nil then
  begin
    Log('GenerateCode: model is nil.');
    Exit;
  end;

  UnitName := Model.UnitName;
  if UnitName = '' then
  begin
    Log('GenerateCode: UnitName is empty.');
    Exit;
  end;

  // Normalise application name: remove .pas extension and replace dots/dashes with underscores
  AppName := UnitName;
  if umlMultipleMatch('*.pas', AppName) then
    AppName := umlChangeFileExt(AppName.Text, '').Text;
  AppName := AppName.ReplaceChar('.', '_').ReplaceChar('-', '_');

  // Fixed beacon constants
  BeaconApp := 'agent_main_app';
  RegisterApi := 'register_agent';
  AgentLogApi := 'agent_log';
  IpcEndpoint := 'ipc:agent';

  Log(PFormat('Generating code for unit "%s"', [UnitName.Text]));

  SupportedFuncs := CollectSupportedFunctions;
  if Length(SupportedFuncs) = 0 then
    Log('No supported functions; generating an empty skeleton.');

  // ---- Initialise modular line lists ----
  HeaderLines := TPascalStringList.Create;
  InterfaceLines := TPascalStringList.Create;
  UsesLines := TPascalStringList.Create;
  ForwardLines := TPascalStringList.Create;
  InternalCallLines := TPascalStringList.Create;
  Ret2StrLines := TPascalStringList.Create;
  LoggingLines := TPascalStringList.Create;
  CallbackLines := TPascalStringList.Create;
  RegisterToolLines := TPascalStringList.Create;
  RegisterAPIsLines := TPascalStringList.Create;
  UsedApiNames := TPascalStringList.Create;
  ResultLines := nil;

  try
    // ---- 1. Unit header ----
    HeaderLines.Add('unit ' + UnitName + '_tool_provider_unit;');
    HeaderLines.Add('');
    HeaderLines.Add('{$ifdef FPC}');
    HeaderLines.Add('  {$mode delphi}');
    HeaderLines.Add('  {$MODESWITCH NestedProcVars}');
    HeaderLines.Add('  {$modeswitch advancedrecords}');
    HeaderLines.Add('  {$MODESWITCH NESTEDCOMMENTS}');
    HeaderLines.Add('  {$CODEPAGE UTF8}');
    HeaderLines.Add('{$endif}');
    HeaderLines.Add('{$H+}');
    HeaderLines.Add('{$R-}');
    HeaderLines.Add('{$I-}');
    HeaderLines.Add('{$Q-}');
    HeaderLines.Add('{$B-}');
    HeaderLines.Add('');
    HeaderLines.Add('interface');
    HeaderLines.Add('');

    // ---- 2. Interface section ----
    InterfaceLines.Add('uses');
    InterfaceLines.Add('  SysUtils, Classes,');
    InterfaceLines.Add('  lingofuse_import;');
    InterfaceLines.Add('');
    InterfaceLines.Add('// ---- Exported global var ----');
    InterfaceLines.Add('var');
    InterfaceLines.Add('  MY_APP_NAME : string = ' + PascalStrLit(AppName) + ';');
    InterfaceLines.Add('  MY_APP_DESC : string = ' + PascalStrLit('Tool provider for unit ' + UnitName) + ';');
    InterfaceLines.Add('  IPC_ENDPOINT : string = ' + PascalStrLit(IpcEndpoint) + ';');
    InterfaceLines.Add('  BEACON_APP : string = ' + PascalStrLit(BeaconApp) + ';');
    InterfaceLines.Add('  REGISTER_API : string = ' + PascalStrLit(RegisterApi) + ';');
    InterfaceLines.Add('  AGENT_LOG_API : string = ' + PascalStrLit(AgentLogApi) + ';');
    InterfaceLines.Add('  DEBUG_LOG : boolean = True;');
    InterfaceLines.Add('');
    InterfaceLines.Add('// ---- Exported functions ----');
    InterfaceLines.Add('{*');
    InterfaceLines.Add(' * RegisterAPIs – Creates the LingoFuse application and registers all');
    InterfaceLines.Add(' * generated Call APIs. Returns the application handle, or nil on failure.');
    InterfaceLines.Add(' * The caller is responsible for freeing the handle with LF_FreeApp.');
    InterfaceLines.Add(' *}');
    InterfaceLines.Add('function RegisterAPIs: TAppHnd___;');
    InterfaceLines.Add('');
    InterfaceLines.Add('{*');
    InterfaceLines.Add(' * RegisterTools – Connects to the beacon, registers all APIs as tools');
    InterfaceLines.Add(' * with JSON schemas, and returns True if all registrations succeeded.');
    InterfaceLines.Add(' *}');
    InterfaceLines.Add('function RegisterTools: Boolean;');
    InterfaceLines.Add('');
    InterfaceLines.Add('{**');
    InterfaceLines.Add(' * Execute_And_Reg_all – One‑click startup and tool registration.');
    InterfaceLines.Add(' *');
    InterfaceLines.Add(' * This function performs the entire initialization sequence:');
    InterfaceLines.Add(' *   1. Calls RegisterAPIs to create the application handle and register all Call APIs.');
    InterfaceLines.Add(' *   2. Prepares a LingoFuse client with IPC_ENDPOINT and the application handle (LF_PrepareClientEx).');
    InterfaceLines.Add(' *   3. Waits for the client to be ready (LF_PrepareDone).');
    InterfaceLines.Add(' *   4. If the connection succeeds, registers every API as a tool with the beacon (RegisterTools).');
    InterfaceLines.Add(' *');
    InterfaceLines.Add(' * It is thread-safe and can be called from any thread without blocking the main thread.');
    InterfaceLines.Add(' * All network operations are handled asynchronously, and the function returns only after');
    InterfaceLines.Add(' * the entire sequence completes (or fails).');
    InterfaceLines.Add(' *');
    InterfaceLines.Add(' * If any step fails (e.g., RegisterAPIs returns nil, PrepareDone returns 0, or RegisterTools returns False),');
    InterfaceLines.Add(' * the function returns False and, when DEBUG_LOG is True, logs an error message.');
    InterfaceLines.Add(' *');
    InterfaceLines.Add(' * @return True if all steps completed successfully, False otherwise.');
    InterfaceLines.Add(' *}');
    InterfaceLines.Add('function Execute_And_Reg_all: Boolean;');
    InterfaceLines.Add('');

    // ---- 3. Implementation uses clause ----
    UsesLines.Add('uses');
    UsesLines.Add('  Z.Core, Z.Json, Z.PascalStrings, Z.UPascalStrings, Z.Status, Z.UnicodeMixedLib, Z.ListEngine;');
    UsesLines.Add('');

    ForwardLines.Add('');
    ForwardLines.Add('// Forward declarations for all API callbacks (allows easy navigation in the editor)');
    ForwardLines.Add('function RegisterTool(const ToolDef: TZ_JsonObject): boolean; forward;');

    // ---- 4. ret2str overloads ----
    Ret2StrLines.Add('function ret2str(v: Int64): string; overload;');
    Ret2StrLines.Add('begin');
    Ret2StrLines.Add('  Result := IntToStr(v);');
    Ret2StrLines.Add('end;');
    Ret2StrLines.Add('');
    Ret2StrLines.Add('function ret2str(v: Double): string; overload;');
    Ret2StrLines.Add('begin');
    Ret2StrLines.Add('  Result := FloatToStr(v);');
    Ret2StrLines.Add('end;');
    Ret2StrLines.Add('');
    Ret2StrLines.Add('function ret2str(const v: string): string; overload;');
    Ret2StrLines.Add('begin');
    Ret2StrLines.Add('  Result := v;');
    Ret2StrLines.Add('end;');
    Ret2StrLines.Add('');

    // ---- 5. Internal call wrappers ----
    // For each supported function, generate an internal call function that
    // calls the original unit's function.
    UsedApiNames.Clear;
    InternalCallLines.Add('');
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        // Build a unique base name (without suffix)
        ApiName := MakeApiName(Name);
        // Check for duplicate; if so, add numeric suffix
        if UsedApiNames.IndexOf(ApiName) >= 0 then
        begin
          j := 1;
          while UsedApiNames.IndexOf(ApiName + '_' + umlIntToStr(j).Text) >= 0 do
            Inc(j);
          ApiName := ApiName + '_' + umlIntToStr(j).Text;
        end;
        UsedApiNames.Add(ApiName);

        InternalCallName := MakeInternalCallName(Name) + '_' + ApiName; // ensure uniqueness

        CallArgs := '';
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;
          if CallArgs <> '' then
            CallArgs.Append(', ');
          CallArgs := CallArgs + ParamName;
        end;

        // Emit the internal call function
        // Emit the internal call function
        InternalCallLines.Add('// ---- Internal wrapper for ' + Name + ' ----');
        InternalCallLines.Add('// This wrapper runs in a background thread. If main-thread synchronization is needed,');
        InternalCallLines.Add('// uncomment the code inside the (* ... *) block below and adjust accordingly.');
        if IsFunction then
          InternalCallLines.Add('function ' + InternalCallName + '(' + BuildParamDecl(Params) + '): ' + ReturnType + ';')
        else
          InternalCallLines.Add('procedure ' + InternalCallName + '(' + BuildParamDecl(Params) + ');');

        InternalCallLines.Add('(*');
        InternalCallLines.Add('{$IFDEF FPC}');
        InternalCallLines.Add('  procedure Do_Sync___();');
        InternalCallLines.Add('  begin');
        if IsFunction then
          InternalCallLines.Add(PFormat('    // call type: Result := %s(%s);', [InternalCallName.Text, CallArgs.Text]))
        else
          InternalCallLines.Add(PFormat('    // call type: %s(%s);', [InternalCallName.Text, CallArgs.Text]));
        InternalCallLines.Add('  end;');
        if IsFunction then
        begin
          InternalCallLines.Add('{$ELSE FPC}');
          InternalCallLines.Add('var temp_: ' + ReturnType + ';');
        end;
        InternalCallLines.Add('{$ENDIF FPC}');
        InternalCallLines.Add('*)');
        InternalCallLines.Add('begin');
        if IsFunction then
        begin
          if ReturnType.Same('string') then
          begin
            InternalCallLines.Add('  Result := ' + #39#39 + ';');
          end
          else
          begin
            InternalCallLines.Add('  Result := 0;');
          end;
          if IsFunction then
            InternalCallLines.Add(PFormat('  // call type: Result := %s(%s);', [InternalCallName.Text, CallArgs.Text]))
          else
            InternalCallLines.Add(PFormat('  // call type: %s(%s);', [InternalCallName.Text, CallArgs.Text]));

          InternalCallLines.Add('(*');
          InternalCallLines.Add('{$IFDEF FPC}');
          InternalCallLines.Add('  TCompute.Sync(Do_Sync___);');
          InternalCallLines.Add('{$ELSE FPC}');
          InternalCallLines.Add('  TCompute.Sync(procedure()');
          InternalCallLines.Add('  begin');
          if IsFunction then
            InternalCallLines.Add(PFormat('    // call type: temp_ := %s(%s);', [InternalCallName.Text, CallArgs.Text]))
          else
            InternalCallLines.Add(PFormat('    // call type: %s(%s);', [InternalCallName.Text, CallArgs.Text]));
          InternalCallLines.Add('  end);');
          InternalCallLines.Add('  Result := temp_;');
          InternalCallLines.Add('{$ENDIF FPC}');
          InternalCallLines.Add('*)');
        end;
        InternalCallLines.Add('end;');
        InternalCallLines.Add('');
      end;
    end;

    // ---- 6. Asynchronous logging ----
    LoggingLines.Add('// ---- Asynchronous logging to beacon ----');
    LoggingLines.Add('procedure Do_Th_Send(th: TCompute);');
    LoggingLines.Add('var');
    LoggingLines.Add('  p: Pointer;');
    LoggingLines.Add('  msg: TZ_JsonString;');
    LoggingLines.Add('  Data, ResultHnd: TDataHnd___;');
    LoggingLines.Add('  jo: TZ_JsonObject;');
    LoggingLines.Add('begin');
    LoggingLines.Add('  p := th.UserData;');
    LoggingLines.Add('  msg.ReadUTF8AnsiChar(p);');
    LoggingLines.Add('  TZ_JsonString.FreeUTF8AnsiChar(p);');
    LoggingLines.Add('  Data := LF_CreateDataEx(AGENT_LOG_API);');
    LoggingLines.Add('  try');
    LoggingLines.Add('    jo := TZ_JsonObject.Create;');
    LoggingLines.Add('    try');
    LoggingLines.Add('      jo.S[''message''] := msg.Text;');
    LoggingLines.Add('      LF_WriteStringBytes(Data, jo.ToBytes);');
    LoggingLines.Add('    finally');
    LoggingLines.Add('      jo.Free;');
    LoggingLines.Add('    end;');
    LoggingLines.Add('    ResultHnd := LF_CallEx(BEACON_APP, Data, 3000);');
    LoggingLines.Add('    if ResultHnd <> nil then');
    LoggingLines.Add('      LF_FreeData(ResultHnd);');
    LoggingLines.Add('  finally');
    LoggingLines.Add('    LF_FreeData(Data);');
    LoggingLines.Add('  end;');
    LoggingLines.Add('end;');
    LoggingLines.Add('');
    LoggingLines.Add('procedure SendLogAsync(const msg: TZ_JsonString);');
    LoggingLines.Add('begin');
    LoggingLines.Add('  TCompute.RunC(msg.BuildUTF8AnsiChar, nil, Do_Th_Send);');
    LoggingLines.Add('end;');
    LoggingLines.Add('');

    // ---- 7. Generate callback procedures ----
    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakeApiName(Name);
        if UsedApiNames.IndexOf(ApiName) >= 0 then
        begin
          j := 1;
          while UsedApiNames.IndexOf(ApiName + '_' + umlIntToStr(j).Text) >= 0 do
            Inc(j);
          ApiName := ApiName + '_' + umlIntToStr(j).Text;
        end;
        UsedApiNames.Add(ApiName);

        CallbackName := MakeCallbackName(Name) + '_' + ApiName;
        InternalCallName := MakeInternalCallName(Name) + '_' + ApiName;

        Log('  Generating callback: ' + CallbackName + ' (params: ' + umlIntToStr(Length(Params)).Text + ')');

        // Build parameter extraction code
        ExtractCode := '';
        CallArgs := '';
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;
          if j > 0 then
            CallArgs := CallArgs + ', ';
          if Params[j].PascalType.Same('Int64') then
            ExtractCode := ExtractCode + '    ' + ParamName + ' := jo.I64[' + #39 + ParamName + #39 + '];' + sLineBreak
          else if Params[j].PascalType.Same('Double') then
            ExtractCode := ExtractCode + '    ' + ParamName + ' := jo.F[' + #39 + ParamName + #39 + '];' + sLineBreak
          else if Params[j].PascalType.Same('string') then
            ExtractCode := ExtractCode + '    ' + ParamName + ' := jo.S[' + #39 + ParamName + #39 + '];' + sLineBreak;
          CallArgs := CallArgs + ParamName;
        end;

        // Emit forward declaration for callback
        ForwardLines.Add('procedure ' + CallbackName + '(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl; forward;');

        // ---- Emit callback implementation with detailed logging ----
        CallbackLines.Add('// ---- ' + Name + ' (API: ' + ApiName + ') ----');
        CallbackLines.Add('procedure ' + CallbackName + '(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl;');
        CallbackLines.Add('var');
        CallbackLines.Add('  jsonBytes: TBytes;');
        CallbackLines.Add('  jo: TZ_JsonObject;');
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;
          CallbackLines.Add('  ' + ParamName + ': ' + Params[j].PascalType + ';');
        end;
        if IsFunction then
          CallbackLines.Add('  ret: ' + ReturnType + ';');
        CallbackLines.Add('  errMsg: string;');
        CallbackLines.Add('begin');
        CallbackLines.Add('  jo := TZ_JsonObject.Create;');
        CallbackLines.Add('  try');
        CallbackLines.Add('    jsonBytes := LF_ReadStringBytes(TDataHnd(_In___));');
        // ----- Log input JSON (if debugging) -----
        CallbackLines.Add('    if DEBUG_LOG then');
        CallbackLines.Add('      DoStatus(''[' + Name + '] Input JSON: %s'', [TEncoding.UTF8.GetString(jsonBytes)]);');
        CallbackLines.Add('');
        CallbackLines.Add('    if Length(jsonBytes) = 0 then');
        CallbackLines.Add('    begin');
        CallbackLines.Add('      errMsg := ''Empty input'';');
        CallbackLines.Add('      jo.Clear;');
        CallbackLines.Add('      jo.S[''error''] := errMsg;');
        CallbackLines.Add('      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);');
        CallbackLines.Add('      if DEBUG_LOG then');
        CallbackLines.Add('      begin');
        CallbackLines.Add('        DoStatus(''[' + Name + '] Error: %s'', [errMsg]);');
        CallbackLines.Add('        SendLogAsync(''[' + Name + '] Error: '' + errMsg);');
        CallbackLines.Add('      end;');
        CallbackLines.Add('      Exit;');
        CallbackLines.Add('    end;');
        CallbackLines.Add('    if not jo.Parae(jsonBytes) then');
        CallbackLines.Add('    begin');
        CallbackLines.Add('      errMsg := ''Invalid JSON'';');
        CallbackLines.Add('      jo.Clear;');
        CallbackLines.Add('      jo.S[''error''] := errMsg;');
        CallbackLines.Add('      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);');
        CallbackLines.Add('      if DEBUG_LOG then');
        CallbackLines.Add('      begin');
        CallbackLines.Add('        DoStatus(''[' + Name + '] Error: %s'', [errMsg]);');
        CallbackLines.Add('        SendLogAsync(''[' + Name + '] Error: '' + errMsg);');
        CallbackLines.Add('      end;');
        CallbackLines.Add('      Exit;');
        CallbackLines.Add('    end;');
        if ExtractCode <> '' then
          CallbackLines.Add(ExtractCode)
        else
          CallbackLines.Add('    // No parameters');
        // Invoke the internal wrapper function (not directly the original unit)
        if IsFunction then
        begin
          CallbackLines.Add('    ret := ' + InternalCallName + '(' + CallArgs + ');');
          CallbackLines.Add('    jo.Clear;');
          if ReturnType.Same('Int64') then
            CallbackLines.Add('    jo.I64[''result''] := ret;')
          else if ReturnType.Same('Double') then
            CallbackLines.Add('    jo.F[''result''] := ret;')
          else if ReturnType.Same('string') then
            CallbackLines.Add('    jo.S[''result''] := ret;');
          CallbackLines.Add('    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);');
          // ----- Log result (if debugging) -----
          CallbackLines.Add('    if DEBUG_LOG then');
          CallbackLines.Add('    begin');
          if CallArgs = '' then
          begin
            CallbackLines.Add('      DoStatus(''[' + Name + '] called (no params) -> result: %s'', [ret2str(ret)]);');
            CallbackLines.Add('      SendLogAsync(''[' + Name + '] called (no params) -> result: '' + ret2str(ret));');
          end
          else
          begin
            CallbackLines.Add('      DoStatus(''[' + Name + '] called with %s -> result: %s'', [' + CallArgs + ', ret2str(ret)]);');
            CallbackLines.Add('      SendLogAsync(PFormat(''[' + Name + '] called with %s'', [' + CallArgs +
              ']) + '' -> result: '' + ret2str(ret));');
          end;
        end
        else
        begin
          CallbackLines.Add('    ' + InternalCallName + '(' + CallArgs + ');');
          CallbackLines.Add('    jo.Clear;');
          CallbackLines.Add('    jo.S[''status''] := ''ok'';');
          CallbackLines.Add('    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);');
          CallbackLines.Add('    if DEBUG_LOG then');
          CallbackLines.Add('    begin');
          if CallArgs = '' then
          begin
            CallbackLines.Add('      DoStatus(''[' + Name + '] called (no params)'');');
            CallbackLines.Add('      SendLogAsync(''[' + Name + '] called (no params)'');');
          end
          else
          begin
            CallbackLines.Add('      DoStatus(''[' + Name + '] called with %s'', [' + CallArgs + ']);');
            CallbackLines.Add('      SendLogAsync(PFormat(''[' + Name + '] called with %s'', [' + CallArgs + ']));');
          end;
        end;
        CallbackLines.Add('    end;');
        CallbackLines.Add('  except');
        CallbackLines.Add('    on E: Exception do');
        CallbackLines.Add('    begin');
        CallbackLines.Add('      jo.Clear;');
        CallbackLines.Add('      jo.S[''error''] := E.Message;');
        CallbackLines.Add('      LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);');
        CallbackLines.Add('      if DEBUG_LOG then');
        CallbackLines.Add('      begin');
        CallbackLines.Add('        DoStatus(''[' + Name + '] Exception: %s'', [E.Message]);');
        CallbackLines.Add('        SendLogAsync(''[' + Name + '] Exception: '' + E.Message);');
        CallbackLines.Add('      end;');
        CallbackLines.Add('    end;');
        CallbackLines.Add('  end;');
        CallbackLines.Add('  jo.Free;');
        CallbackLines.Add('end;');
        CallbackLines.Add('');
      end;
    end;

    // ---- 8. RegisterTool helper (with detailed logging) ----
    RegisterToolLines.Add('// -----------------------------------------------------------------------------');
    RegisterToolLines.Add('// Register a single tool with the beacon using LF_WriteStringBytes / LF_ReadStringBytes');
    RegisterToolLines.Add('// The tool definition is sent as a JSON object to the "register_agent" API.');
    RegisterToolLines.Add('// Returns True on success, False on failure.');
    RegisterToolLines.Add('// -----------------------------------------------------------------------------');
    RegisterToolLines.Add('function RegisterTool(const ToolDef: TZ_JsonObject): boolean;');
    RegisterToolLines.Add('var');
    RegisterToolLines.Add('  Data, ResultHnd: TDataHnd___;');
    RegisterToolLines.Add('  jsonBytes: TBytes;');
    RegisterToolLines.Add('  RespJson: TZ_JsonObject;');
    RegisterToolLines.Add('  toolName, toolDesc, targetApp, targetApi: string;');
    RegisterToolLines.Add('begin');
    RegisterToolLines.Add('  Result := False;');
    RegisterToolLines.Add('  // Extract key fields for logging');
    RegisterToolLines.Add('  toolName := ToolDef.S[''name''];');
    RegisterToolLines.Add('  toolDesc := ToolDef.S[''description''];');
    RegisterToolLines.Add('  targetApp := ToolDef.S[''target_app''];');
    RegisterToolLines.Add('  targetApi := ToolDef.S[''target_api''];');
    RegisterToolLines.Add('  if DEBUG_LOG then');
    RegisterToolLines.Add('    DoStatus(''[RegisterTool] Registering tool: %s -> %s.%s'', [toolName, targetApp, targetApi]);');
    RegisterToolLines.Add('');
    RegisterToolLines.Add('  Data := LF_CreateDataEx(REGISTER_API);');
    RegisterToolLines.Add('  try');
    RegisterToolLines.Add('    LF_WriteStringBytes(Data, ToolDef.ToBytes);');
    RegisterToolLines.Add('    ResultHnd := LF_CallEx(BEACON_APP, Data, 5000);');
    RegisterToolLines.Add('    try');
    RegisterToolLines.Add('      jsonBytes := LF_ReadStringBytes(ResultHnd);');
    RegisterToolLines.Add('      if Length(jsonBytes) > 0 then');
    RegisterToolLines.Add('      begin');
    RegisterToolLines.Add('        RespJson := TZ_JsonObject.Create;');
    RegisterToolLines.Add('        try');
    RegisterToolLines.Add('          RespJson.Parae(jsonBytes);');
    RegisterToolLines.Add('          if RespJson.Exists(''status'') and (RespJson.S[''status''] = ''ok'') then');
    RegisterToolLines.Add('          begin');
    RegisterToolLines.Add('            Result := True;');
    RegisterToolLines.Add('            if DEBUG_LOG then');
    RegisterToolLines.Add('              DoStatus(''[RegisterTool] Tool "%s" registered successfully.'', [toolName]);');
    RegisterToolLines.Add('          end');
    RegisterToolLines.Add('          else');
    RegisterToolLines.Add('          begin');
    RegisterToolLines.Add('            if DEBUG_LOG then');
    RegisterToolLines.Add('              DoStatus(''[RegisterTool] Server returned error: %s'', [RespJson.S[''message'']]);');
    RegisterToolLines.Add('          end;');
    RegisterToolLines.Add('        finally');
    RegisterToolLines.Add('          RespJson.Free;');
    RegisterToolLines.Add('        end;');
    RegisterToolLines.Add('      end');
    RegisterToolLines.Add('      else');
    RegisterToolLines.Add('        if DEBUG_LOG then');
    RegisterToolLines.Add('          DoStatus(''[RegisterTool] Empty response from beacon (timeout or network error)'');');
    RegisterToolLines.Add('    finally');
    RegisterToolLines.Add('      LF_FreeData(ResultHnd);');
    RegisterToolLines.Add('    end;');
    RegisterToolLines.Add('  finally');
    RegisterToolLines.Add('    LF_FreeData(Data);');
    RegisterToolLines.Add('  end;');
    RegisterToolLines.Add('end;');
    RegisterToolLines.Add('');

    // ---- RegisterTools implementation ----
    RegisterToolLines.Add('// ---- RegisterTools implementation ----');
    RegisterToolLines.Add('function RegisterTools: Boolean;');
    RegisterToolLines.Add('var');
    RegisterToolLines.Add('  ToolDef: TZ_JsonObject;');
    RegisterToolLines.Add('  ParamsObj, PropsObj, PropObj: TZ_JsonObject;');
    RegisterToolLines.Add('  RequiredArr: TZ_JsonArray;');
    RegisterToolLines.Add('  Success: boolean;');
    RegisterToolLines.Add('  regCount: integer;');
    RegisterToolLines.Add('begin');
    RegisterToolLines.Add('  Result := False;');
    RegisterToolLines.Add('  regCount := 0;');
    RegisterToolLines.Add('  // Check if the beacon is reachable');
    RegisterToolLines.Add('  if DEBUG_LOG then');
    RegisterToolLines.Add('    DoStatus(''[RegisterTools] Checking beacon availability: app=%s api=%s'', [BEACON_APP, REGISTER_API]);');
    RegisterToolLines.Add('  if not LF_CheckApiEx(BEACON_APP, REGISTER_API) then');
    RegisterToolLines.Add('  begin');
    RegisterToolLines.Add('    DoStatus(''[RegisterTools] Beacon not available. Please ensure pascal_agent_service is running.'');');
    RegisterToolLines.Add('    exit;');
    RegisterToolLines.Add('  end;');
    RegisterToolLines.Add('  if DEBUG_LOG then');
    RegisterToolLines.Add('    DoStatus(''[RegisterTools] Beacon is available. Starting tool registration...'');');
    RegisterToolLines.Add('  try');
    // Register each tool
    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakeApiName(Name);
        if UsedApiNames.IndexOf(ApiName) >= 0 then
        begin
          j := 1;
          while UsedApiNames.IndexOf(ApiName + '_' + umlIntToStr(j).Text) >= 0 do
            Inc(j);
          ApiName := ApiName + '_' + umlIntToStr(j).Text;
        end;
        UsedApiNames.Add(ApiName);

        Description := GetFullDescription(Comment);
        if Description = '' then
          Description := 'Auto-generated call for ' + Name;

        RegisterToolLines.Add('    // Tool: ' + Name + ' -> ' + ApiName);
        RegisterToolLines.Add('    ToolDef := TZ_JsonObject.Create;');
        RegisterToolLines.Add('    try');
        RegisterToolLines.Add('      ToolDef.S[''name''] := ' + PascalStrLit(ApiName) + ';');
        RegisterToolLines.Add('      ToolDef.S[''description''] := ' + PascalStrLit(Description) + ';');
        RegisterToolLines.Add('      ToolDef.S[''target_app''] := MY_APP_NAME;');
        RegisterToolLines.Add('      ToolDef.S[''target_api''] := ' + PascalStrLit(ApiName) + ';');
        RegisterToolLines.Add('');
        RegisterToolLines.Add('      ParamsObj := ToolDef.O[''parameters''];');
        RegisterToolLines.Add('      ParamsObj.S[''type''] := ''object'';');
        RegisterToolLines.Add('      PropsObj := ParamsObj.O[''properties''];');
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;
          RegisterToolLines.Add('      PropObj := PropsObj.O[' + PascalStrLit(ParamName) + '];');
          if Params[j].PascalType.Same('Int64') then
            RegisterToolLines.Add('      PropObj.S[''type''] := ''integer'';')
          else if Params[j].PascalType.Same('Double') then
            RegisterToolLines.Add('      PropObj.S[''type''] := ''number'';')
          else if Params[j].PascalType.Same('string') then
            RegisterToolLines.Add('      PropObj.S[''type''] := ''string'';');
          if Params[j].Description <> '' then
            RegisterToolLines.Add('      PropObj.S[''description''] := ' + PascalStrLit(Params[j].Description) + ';')
          else
            RegisterToolLines.Add('      PropObj.S[''description''] := ' + PascalStrLit(ParamName + ' parameter') + ';');
        end;
        if Length(Params) > 0 then
        begin
          RegisterToolLines.Add('      RequiredArr := ParamsObj.a[''required''];');
          for j := 0 to High(Params) do
          begin
            if Params[j].Name = '' then
              ParamName := 'p' + umlIntToStr(j)
            else
              ParamName := Params[j].Name;
            RegisterToolLines.Add('      RequiredArr.Add(' + PascalStrLit(ParamName) + ');');
          end;
        end;
        RegisterToolLines.Add('      Success := RegisterTool(ToolDef);');
        RegisterToolLines.Add('      if Success then Inc(regCount);');
        RegisterToolLines.Add('      if DEBUG_LOG then');
        RegisterToolLines.Add('        if Success then');
        RegisterToolLines.Add('          DoStatus(''[RegisterTools] OK: ' + ApiName + ''')');
        RegisterToolLines.Add('        else');
        RegisterToolLines.Add('          DoStatus(''[RegisterTools] FAIL: ' + ApiName + ''');');
        RegisterToolLines.Add('    finally');
        RegisterToolLines.Add('      ToolDef.Free;');
        RegisterToolLines.Add('    end;');
        RegisterToolLines.Add('');
      end;
    end;

    RegisterToolLines.Add('    Result := (regCount = ' + umlIntToStr(Length(SupportedFuncs)).Text + ');');
    RegisterToolLines.Add('    if DEBUG_LOG then');
    RegisterToolLines.Add('      DoStatus(''[RegisterTools] Registered %d out of %d tools.'', [regCount, ' +
      umlIntToStr(Length(SupportedFuncs)).Text + ']);');
    RegisterToolLines.Add('  finally');
    RegisterToolLines.Add('  end;');
    RegisterToolLines.Add('end;');
    RegisterToolLines.Add('');

    // ---- 9. RegisterAPIs implementation ----
    RegisterAPIsLines.Add('// ---- RegisterAPIs implementation ----');
    RegisterAPIsLines.Add('function RegisterAPIs: TAppHnd___;');
    RegisterAPIsLines.Add('var');
    RegisterAPIsLines.Add('  App: TAppHnd___;');
    RegisterAPIsLines.Add('begin');
    RegisterAPIsLines.Add('  Result := nil;');
    RegisterAPIsLines.Add('  App := LF_CreateAppEx(MY_APP_NAME, MY_APP_DESC);');
    RegisterAPIsLines.Add('  if DEBUG_LOG then');
    RegisterAPIsLines.Add('    DoStatus(''[RegisterAPIs] Application "%s" created.'', [MY_APP_NAME]);');
    RegisterAPIsLines.Add('');
    // Register APIs
    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakeApiName(Name);
        if UsedApiNames.IndexOf(ApiName) >= 0 then
        begin
          j := 1;
          while UsedApiNames.IndexOf(ApiName + '_' + umlIntToStr(j).Text) >= 0 do
            Inc(j);
          ApiName := ApiName + '_' + umlIntToStr(j).Text;
        end;
        UsedApiNames.Add(ApiName);
        CallbackName := MakeCallbackName(Name) + '_' + ApiName;
        Description := GetFullDescription(Comment);
        if Description = '' then
          Description := 'Auto-generated call for ' + Name;
        RegisterAPIsLines.Add('  LF_RegisterCallEx(App, ' + PascalStrLit(ApiName) + ', ' + PascalStrLit(Description) +
          ', nil, @' + CallbackName + ');' + '  // Register API: ' + Name + ' -> ' + ApiName);
      end;
    end;
    RegisterAPIsLines.Add('  if DEBUG_LOG then');
    RegisterAPIsLines.Add('    DoStatus(''[RegisterAPIs] Registered APIs: ' + umlIntToStr(Length(SupportedFuncs)) + ' functions'');');
    RegisterAPIsLines.Add('  Result := App;');
    RegisterAPIsLines.Add('end;');
    RegisterAPIsLines.Add('');


    // ---- Execute_And_Reg_all implementation ----
    ExecuteLines := TPascalStringList.Create;
    ExecuteLines.Add('');
    ExecuteLines.Add('// ---- Execute_And_Reg_all implementation ----');
    ExecuteLines.Add('function Execute_And_Reg_all: Boolean;');
    ExecuteLines.Add('var');
    ExecuteLines.Add('  App: TAppHnd___;');
    ExecuteLines.Add('begin');
    ExecuteLines.Add('  Result := False;');
    ExecuteLines.Add('  App := RegisterAPIs();');
    ExecuteLines.Add('  if App = nil then');
    ExecuteLines.Add('  begin');
    ExecuteLines.Add('    if DEBUG_LOG then DoStatus(''[Execute_And_Reg_all] RegisterAPIs failed'');');
    ExecuteLines.Add('    Exit;');
    ExecuteLines.Add('  end;');
    ExecuteLines.Add('  LF_ResetPrepare();');
    ExecuteLines.Add('  LF_PrepareClientEx(IPC_ENDPOINT, App);');
    ExecuteLines.Add('  if LF_PrepareDone() > 0 then');
    ExecuteLines.Add('    Result := RegisterTools()');
    ExecuteLines.Add('  else');
    ExecuteLines.Add('  begin');
    ExecuteLines.Add('    if DEBUG_LOG then DoStatus(''[Execute_And_Reg_all] LF_PrepareDone failed'');');
    ExecuteLines.Add('  end;');
    ExecuteLines.Add('end;');
    ExecuteLines.Add('');

    // ---- Assemble final result ----
    ResultLines := TPascalStringList.Create;
    ResultLines.AddStrings(HeaderLines);
    ResultLines.AddStrings(InterfaceLines);

    ResultLines.Add('implementation');
    ResultLines.Add('');

    ResultLines.AddStrings(UsesLines);
    ResultLines.AddStrings(ForwardLines);
    ResultLines.AddStrings(InternalCallLines);

    ResultLines.Add('{$Region ''internal_''}');
    ResultLines.AddStrings(Ret2StrLines);
    ResultLines.AddStrings(LoggingLines);
    ResultLines.Add('{$EndRegion ''internal_''}');

    ResultLines.Add('{$Region ''callback_''}');
    ResultLines.AddStrings(CallbackLines);
    ResultLines.Add('{$EndRegion ''callback_''}');

    ResultLines.AddStrings(RegisterToolLines);
    ResultLines.AddStrings(RegisterAPIsLines);
    ResultLines.AddStrings(ExecuteLines);
    ResultLines.Add('end.');

    Result := ResultLines;
    Log(PFormat('Generation completed: %d lines, %d supported functions.', [ResultLines.Count, Length(SupportedFuncs)]));

  finally
    HeaderLines.Free;
    InterfaceLines.Free;
    UsesLines.Free;
    ForwardLines.Free;
    InternalCallLines.Free;
    Ret2StrLines.Free;
    LoggingLines.Free;
    CallbackLines.Free;
    RegisterToolLines.Free;
    RegisterAPIsLines.Free;
    UsedApiNames.Free;
    ExecuteLines.Free;
    // ResultLines is returned; do not free it here.
  end;
end;

end.
