unit py_mcp_generator_tool;

{*******************************************************************************
 * py_mcp_generator_tool – LingoFuse Python Tool Provider Code Generator
 *
 * This unit consumes a TPascal_Func_Model (extracted from Pascal source) and
 * produces a complete Python module that can be run as a LingoFuse tool
 * provider. It is the Python analogue of pas_mcp_generator_tool.pas.
 *
 * The generated module exposes three public entry points:
 *
 *   - RegisterAPIs()          -> create the LingoFuse application and
 *                                register all supported routines as Call APIs.
 *
 *   - RegisterTools()         -> connect to the beacon and register each API
 *                                as a tool with a JSON schema.
 *
 *   - Execute_And_Reg_all()   -> one-click startup sequence that combines
 *                                the above two steps and connects to the
 *                                backend endpoint via IPC.
 *
 * The generated Python code uses the `lingofuse._lf_native` ctypes bindings
 * (LF_CreateData, LF_FreeData, LF_CreateApp, LF_RegisterCall, LF_Call, ...)
 * and the same LF_ReadStringBytes / LF_WriteStringBytes semantics as the
 * Pascal provider (null-terminated UTF-8 byte strings). It mirrors the
 * layout of the Pascal generator output so that both generated files can
 * live side by side in the same project.
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
 *     Code := GeneratePythonCode(Model);
 *     if Code <> nil then
 *     begin
 *       Code.SaveToFile('my_provider_tool_provider.py');
 *       Code.Free;
 *     end;
 *     Model.Free;
 *   end;
 *
 * =============================================================================
 * NOTES
 * =============================================================================
 *   - The generated Python module uses a fixed beacon application name
 *     ('agent_main_app') and the IPC endpoint 'ipc:agent', matching the
 *     Pascal generator's defaults.
 *   - Nested routines (NestLevel <> 0) are skipped by the model itself;
 *     this generator only iterates over Model.Funcs.
 *   - Unsupported parameter / return types are dropped with a log entry.
 *   - Callback signatures follow the @LFCallFunc convention used by the
 *     LingoFuse Python bindings: (Trigger, Input, Output).
 *
 * =============================================================================
 * OUTPUT STRUCTURE (Python module layout)
 * =============================================================================
 *   - Header docstring + imports
 *   - Application metadata constants (MY_APP_NAME, ...)
 *   - Low-level string helpers (_write_string, _read_string_bytes, _ret2str)
 *   - Internal call stubs (one per supported routine; body is a placeholder)
 *   - Async logging helper (_send_log_async)
 *   - API callbacks (one @LFCallFunc per supported routine)
 *   - Tool registration helper (_register_tool)
 *   - RegisterTools()         – advertise all tools to the beacon
 *   - RegisterAPIs()          – create the app and register all callbacks
 *   - Execute_And_Reg_all()   – full startup sequence
 *   - __main__ entry point (interactive loop)
 *
 * =============================================================================
 * FIX LOG
 * =============================================================================
 *   v1.1 (2026-09-13)
 *     - RegisterTools(): `total_count` was assigned AFTER it was used in
 *       the f-string print at the top of the function body. Python treats
 *       it as a local variable, so the print raised UnboundLocalError.
 *       The assignment has been moved above the print. `reg_count` is
 *       also initialised before the first use, for symmetry.
 *
 *   v1.0 (2026-09-13)
 *     - PyStrLit / MakePythonIdentifier / IsPythonIdentChar now iterate
 *       with TP_Char (UTF-16) instead of SystemChar (AnsiChar). The
 *       previous code silently truncated every non-ASCII code point to a
 *       single byte, so Chinese comments, emoji, and other multi-byte
 *       characters came out as '?' in the generated Python source.
 *     - GetFullDescription has been rewritten to split the comment
 *       directly on the UTF-16 TP_String, avoiding the SystemString
 *       intermediary (TPascalStringList.AsText := Comment) which also
 *       lost non-ASCII characters.
 *     - umlChangeFileExt now receives AppName directly so it goes
 *       through the UTF-8 aware implicit conversion instead of
 *       AppName.Text.
 * ****************************************************************************}

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\..\zNetV2\source\Z.Define.inc}

interface

uses
  SysUtils, Classes,
  Z.Core,
  Z.PascalStrings, Z.UPascalStrings,
  Z.Status, Z.Json, Z.UnicodeMixedLib, Z.ListEngine,
  Z.Pascal_Func_Model,   // TPascal_Func_Model, TFunctionStructure, TParamArray
  Z.Parsing;             // TP_String, TP_Char

{*
 * GeneratePythonCode – Main entry point.
 *
 * @param Model   The TPascal_Func_Model containing the extracted functions.
 * @return        A TPascalStringList containing the generated Python source
 *                lines, or nil on error. The caller is responsible for
 *                freeing the returned list.
 *}
function GeneratePythonCode(Model: TPascal_Func_Model): TPascalStringList;

const
  { Enable/disable verbose logging during code generation. }
  GenerateCode_LogEnabled: boolean = False;

implementation

// -----------------------------------------------------------------------------
// Local logging helper
// -----------------------------------------------------------------------------

procedure Log(const Msg: TP_String);
begin
  if GenerateCode_LogEnabled then
    DoStatus('[py_mcp_generator] %s', [Msg.Text]);
end;

// -----------------------------------------------------------------------------
// Type support check and mapping
// -----------------------------------------------------------------------------

function IsSupportedType(const Typ: TP_String): boolean;
begin
  Result := Typ.Same('int64', 'double', 'string');
end;

function PascalTypeToPythonType(const Typ: TP_String): TP_String;
begin
  if Typ.Same('int64') then
    Result := 'int'
  else if Typ.Same('double') then
    Result := 'float'
  else if Typ.Same('string') then
    Result := 'str'
  else
    Result := 'Any';
end;

function PascalTypeToJsonSchemaType(const Typ: TP_String): TP_String;
begin
  if Typ.Same('int64') then
    Result := 'integer'
  else if Typ.Same('double') then
    Result := 'number'
  else if Typ.Same('string') then
    Result := 'string'
  else
    Result := 'string';
end;

function PascalTypeDefaultValue(const Typ: TP_String): TP_String;
begin
  if Typ.Same('int64') then
    Result := '0'
  else if Typ.Same('double') then
    Result := '0.0'
  else if Typ.Same('string') then
    Result := '""'
  else
    Result := 'None';
end;

// -----------------------------------------------------------------------------
// Python string literal escaping
//
// Iterates with TP_Char (UTF-16) so that non-ASCII code points survive.
// Using SystemChar (AnsiChar) would truncate every multi-byte character.
// -----------------------------------------------------------------------------

function PyStrLit(const S: TP_String): TP_String;
var
  i: integer;
  c: TP_Char;
begin
  Result := '"';
  for i := 1 to S.Len do
  begin
    c := S[i];
    if c = '"' then
      Result := Result + '\"'
    else if c = #92 then
      Result := Result + '\\'
    else if c = #10 then
      Result := Result + '\n'
    else if c = #13 then
      Result := Result + '\r'
    else if c = #9 then
      Result := Result + '\t'
    else
      Result := Result + c;
  end;
  Result := Result + '"';
end;

// -----------------------------------------------------------------------------
// Python identifier maker
// -----------------------------------------------------------------------------

function IsPythonIdentChar(c: TP_Char): boolean;
begin
  Result := ((c >= 'a') and (c <= 'z')) or
            ((c >= 'A') and (c <= 'Z')) or
            ((c >= '0') and (c <= '9')) or
            (c = '_');
end;

function MakePythonIdentifier(const Name: TP_String): TP_String;
var
  i: integer;
  c: TP_Char;
begin
  Result := '';
  for i := 1 to Name.Len do
  begin
    c := Name[i];
    if IsPythonIdentChar(c) then
      Result := Result + c
    else
      Result := Result + '_';
  end;
  if Result.Len = 0 then
    Result := 'unnamed';
  if (Result[1] >= '0') and (Result[1] <= '9') then
    Result := '_' + Result;
end;

// -----------------------------------------------------------------------------
// Comment description extraction (Doxygen-aware)
//
// Operates directly on the UTF-16 TP_String without going through
// TPascalStringList / SystemString. The previous implementation did
//     Lines.AsText := Comment;
// which silently dropped every non-ASCII character.
// -----------------------------------------------------------------------------

function GetFullDescription(const Comment: TP_String): TP_String;
var
  i, j: integer;
  Line: TP_String;
begin
  Result := '';
  if Comment.Len = 0 then
    Exit;

  i := 1;
  while i <= Comment.Len do
  begin
    // Locate the end of the current logical line (CR, LF, or end of string).
    j := i;
    while (j <= Comment.Len) and (Comment[j] <> #10) and (Comment[j] <> #13) do
      Inc(j);

    if j > i then
    begin
      // GetString is half-open: [i, j-1] — excludes the terminator.
      Line := Comment.GetString(i, j);
      Line := Line.TrimChar(#32#9);

      if Line.Len > 0 then
      begin
        // Skip Doxygen-style tag lines (e.g. "@param ...").
        if Line[1] = '@' then
        begin
          // intentionally empty — this line is dropped
        end
        else
        begin
          // Strip leading '*' markers from block comments (possibly two).
          if Line[1] = '*' then
            Line := Line.GetString(2, Line.Len + 1).TrimChar(#32#9);
          if (Line.Len > 0) and (Line[1] = '*') then
            Line := Line.GetString(2, Line.Len + 1).TrimChar(#32#9);

          if Line.Len > 0 then
          begin
            if Result.Len > 0 then
              Result := Result + ' ';
            Result := Result + Line;
          end;
        end;
      end;
    end;

    // Advance past the line terminator(s).
    i := j;
    while (i <= Comment.Len) and ((Comment[i] = #10) or (Comment[i] = #13)) do
      Inc(i);
  end;
end;

// -----------------------------------------------------------------------------
// Main code generator
// -----------------------------------------------------------------------------

function GeneratePythonCode(Model: TPascal_Func_Model): TPascalStringList;
type
  TArryFunctionStructure = array of TFunctionStructure;

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

      for j := 0 to High(f.Params) do
        if not IsSupportedType(f.Params[j].PascalType) then
        begin
          Supported := False;
          Log(PFormat('Skipped "%s": param "%s" has unsupported type "%s"',
            [f.Name.Text, f.Params[j].Name.Text, f.Params[j].PascalType.Text]));
          Break;
        end;

      if Supported and f.IsFunction and not IsSupportedType(f.ReturnType) then
      begin
        Supported := False;
        Log(PFormat('Skipped "%s": return type "%s" unsupported',
          [f.Name.Text, f.ReturnType.Text]));
      end;

      if Supported then
      begin
        SetLength(Result, Length(Result) + 1);
        Result[High(Result)] := f;
      end;
    end;
  end;

  { Ensure the identifier is not already in UsedList; if so, append _1, _2, ... }
  function UniqueApiName(const BaseName: TP_String; UsedList: TPascalStringList): TP_String;
  var
    Counter: integer;
    Candidate: TP_String;
  begin
    Result := BaseName;
    if UsedList.IndexOf(Result) < 0 then
      Exit;
    Counter := 1;
    while True do
    begin
      Candidate := BaseName.Text + '_' + umlIntToStr(Counter).Text;
      if UsedList.IndexOf(Candidate) < 0 then
      begin
        Result := Candidate;
        Exit;
      end;
      Inc(Counter);
    end;
  end;

var
  i, j: integer;
  SupportedFuncs: array of TFunctionStructure;
  UnitName, AppName, BeaconApp, RegisterApi, AgentLogApi, IpcEndpoint: TP_String;
  UsedApiNames: TPascalStringList;
  ApiName, CallbackName, InternalCallName: TP_String;
  Description, ParamName, ParamExtract, CallArgs, ParamDeclPython: TP_String;
  RetTypePy: TP_String;
  PropJson, RequiredList: TP_String;
  TotalFuncCount: integer;

  HeaderLines, HelperLines, InternalCallLines: TPascalStringList;
  LoggingLines, CallbackLines, RegisterToolLines: TPascalStringList;
  RegisterToolsLines, RegisterAPIsLines, ExecuteLines: TPascalStringList;
  ResultLines: TPascalStringList;
begin
  Result := nil;
  if Model = nil then
  begin
    Log('GeneratePythonCode: model is nil.');
    Exit;
  end;

  UnitName := Model.UnitName;
  if UnitName = '' then
  begin
    Log('GeneratePythonCode: UnitName is empty.');
    Exit;
  end;

  // Normalise application name: drop a trailing .pas and replace dots/dashes.
  // Pass AppName (TP_String) directly instead of AppName.Text so the implicit
  // conversion goes through UTF-8 rather than AnsiString.
  AppName := UnitName;
  if umlMultipleMatch('*.pas', AppName) then
    AppName := umlChangeFileExt(AppName, '');
  AppName := AppName.ReplaceChar('.', '_').ReplaceChar('-', '_');

  // Fixed beacon constants (mirrors pas_mcp_generator_tool.pas).
  BeaconApp := 'agent_main_app';
  RegisterApi := 'register_agent';
  AgentLogApi := 'agent_log';
  IpcEndpoint := 'ipc:agent';

  Log(PFormat('Generating Python code for unit "%s"', [UnitName.Text]));

  SupportedFuncs := CollectSupportedFunctions;
  TotalFuncCount := Length(SupportedFuncs);
  if TotalFuncCount = 0 then
    Log('No supported routines; generating an empty skeleton.');

  // ---- Initialise modular line lists ----
  HeaderLines := TPascalStringList.Create;
  HelperLines := TPascalStringList.Create;
  InternalCallLines := TPascalStringList.Create;
  LoggingLines := TPascalStringList.Create;
  CallbackLines := TPascalStringList.Create;
  RegisterToolLines := TPascalStringList.Create;
  RegisterToolsLines := TPascalStringList.Create;
  RegisterAPIsLines := TPascalStringList.Create;
  ExecuteLines := TPascalStringList.Create;
  UsedApiNames := TPascalStringList.Create;
  ResultLines := nil;

  try
    // =========================================================================
    // 1. Header and imports
    // =========================================================================
    HeaderLines.Add('# -*- coding: utf-8 -*-');
    HeaderLines.Add('"""');
    HeaderLines.Add(UnitName + ' - Auto-generated LingoFuse Python tool provider');
    HeaderLines.Add('');
    HeaderLines.Add('This module was auto-generated from a Pascal source model.');
    HeaderLines.Add('It exposes the following public entry points:');
    HeaderLines.Add('    RegisterAPIs()          -> create the LingoFuse application handle');
    HeaderLines.Add('    RegisterTools()         -> advertise all APIs to the beacon');
    HeaderLines.Add('    Execute_And_Reg_all()   -> full startup sequence (recommended)');
    HeaderLines.Add('');
    HeaderLines.Add('Run this file directly to start the provider:');
    HeaderLines.Add('    python ' + UnitName + '_tool_provider.py');
    HeaderLines.Add('"""');
    HeaderLines.Add('');
    HeaderLines.Add('import sys');
    HeaderLines.Add('import json');
    HeaderLines.Add('import ctypes');
    HeaderLines.Add('import threading');
    HeaderLines.Add('from typing import Any, Optional');
    HeaderLines.Add('');
    HeaderLines.Add('try:');
    HeaderLines.Add('    from lingofuse._lf_native import (');
    HeaderLines.Add('        DataHnd, AppHnd,');
    HeaderLines.Add('        LF_CreateData,');
    HeaderLines.Add('        LF_FreeData,');
    HeaderLines.Add('        LF_CreateApp,');
    HeaderLines.Add('        LF_FreeApp,');
    HeaderLines.Add('        LF_RegisterCall,');
    HeaderLines.Add('        LF_WriteBuffer,');
    HeaderLines.Add('        LF_ReadBuffer,');
    HeaderLines.Add('        LF_GetPos,');
    HeaderLines.Add('        LF_SetPos,');
    HeaderLines.Add('        LF_GetSize,');
    HeaderLines.Add('        LF_GetBuffer,');
    HeaderLines.Add('        LF_PrepareClient,');
    HeaderLines.Add('        LF_ResetPrepare,');
    HeaderLines.Add('        LF_PrepareDone,');
    HeaderLines.Add('        LF_ExitMainThread,');
    HeaderLines.Add('        LF_Shutdown,');
    HeaderLines.Add('        LF_Call,');
    HeaderLines.Add('        LF_SetOption,');
    HeaderLines.Add('        LF_CheckMainThread,');
    HeaderLines.Add('        LFCallFunc,');
    HeaderLines.Add('    )');
    HeaderLines.Add('except ImportError as _imp_err:');
    HeaderLines.Add('    print(f"[FATAL] lingofuse package is not available: {_imp_err}", file=sys.stderr)');
    HeaderLines.Add('    sys.exit(1)');
    HeaderLines.Add('');
    HeaderLines.Add('');
    HeaderLines.Add('# ==== Application metadata ====');
    HeaderLines.Add('MY_APP_NAME = ' + PyStrLit(AppName));
    HeaderLines.Add('MY_APP_DESC = ' + PyStrLit('Tool provider for unit ' + UnitName));
    HeaderLines.Add('IPC_ENDPOINT = ' + PyStrLit(IpcEndpoint));
    HeaderLines.Add('BEACON_APP = ' + PyStrLit(BeaconApp));
    HeaderLines.Add('REGISTER_API = ' + PyStrLit(RegisterApi));
    HeaderLines.Add('AGENT_LOG_API = ' + PyStrLit(AgentLogApi));
    HeaderLines.Add('DEBUG_LOG = True');
    HeaderLines.Add('');
    HeaderLines.Add('');

    // =========================================================================
    // 2. Low-level string helpers
    // =========================================================================
    HelperLines.Add('# ==== Low-level string helpers ====');
    HelperLines.Add('');
    HelperLines.Add('def _write_string(hnd, s):');
    HelperLines.Add('    """Write a UTF-8 string with a null terminator to a DataHandle."""');
    HelperLines.Add('    if isinstance(s, str):');
    HelperLines.Add('        s = s.encode("utf-8")');
    HelperLines.Add('    if len(s) > 0:');
    HelperLines.Add('        LF_WriteBuffer(hnd, s, len(s))');
    HelperLines.Add('    LF_WriteBuffer(hnd, b"\x00", 1)');
    HelperLines.Add('');
    HelperLines.Add('');
    HelperLines.Add('def _read_string_bytes(hnd) -> bytes:');
    HelperLines.Add('    """Read a null-terminated UTF-8 string from a DataHandle.');
    HelperLines.Add('');
    HelperLines.Add('    If no null terminator is found, return the entire remaining buffer.');
    HelperLines.Add('    This mirrors LF_ReadString behavior in lingofuse_import.pas.');
    HelperLines.Add('    """');
    HelperLines.Add('    pos = LF_GetPos(hnd)');
    HelperLines.Add('    size = LF_GetSize(hnd)');
    HelperLines.Add('    if pos >= size:');
    HelperLines.Add('        return b""');
    HelperLines.Add('    ptr = LF_GetBuffer(hnd)');
    HelperLines.Add('    if not ptr:');
    HelperLines.Add('        return b""');
    HelperLines.Add('    cptr = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_byte))');
    HelperLines.Add('    end = pos');
    HelperLines.Add('    while end < size and cptr[end] != 0:');
    HelperLines.Add('        end += 1');
    HelperLines.Add('    if end < size:');
    HelperLines.Add('        data_len = end - pos');
    HelperLines.Add('        if data_len == 0:');
    HelperLines.Add('            LF_SetPos(hnd, end + 1)');
    HelperLines.Add('            return b""');
    HelperLines.Add('        raw = (ctypes.c_byte * data_len)()');
    HelperLines.Add('        LF_ReadBuffer(hnd, raw, data_len)');
    HelperLines.Add('        LF_SetPos(hnd, end + 1)');
    HelperLines.Add('        return bytes(raw)');
    HelperLines.Add('    else:');
    HelperLines.Add('        data_len = size - pos');
    HelperLines.Add('        if data_len == 0:');
    HelperLines.Add('            return b""');
    HelperLines.Add('        raw = (ctypes.c_byte * data_len)()');
    HelperLines.Add('        LF_ReadBuffer(hnd, raw, data_len)');
    HelperLines.Add('        LF_SetPos(hnd, size)');
    HelperLines.Add('        return bytes(raw)');
    HelperLines.Add('');
    HelperLines.Add('');
    HelperLines.Add('def _ret2str(v) -> str:');
    HelperLines.Add('    """Convert a return value to a printable string for logging."""');
    HelperLines.Add('    if v is None:');
    HelperLines.Add('        return "None"');
    HelperLines.Add('    return str(v)');
    HelperLines.Add('');
    HelperLines.Add('');

    // =========================================================================
    // 3. Internal call stubs (one per supported routine)
    // =========================================================================
    InternalCallLines.Add('# ==== Internal call stubs ====');
    InternalCallLines.Add('#');
    InternalCallLines.Add('# Each stub corresponds to an original Pascal routine and has the');
    InternalCallLines.Add('# correct signature with Python type annotations.');
    InternalCallLines.Add('# Replace the placeholder body with the actual implementation.');
    InternalCallLines.Add('');

    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakePythonIdentifier(Name);
        ApiName := UniqueApiName(ApiName, UsedApiNames);
        UsedApiNames.Add(ApiName);

        InternalCallName := 'internal_call_' + ApiName;

        // Build the Python parameter list.
        ParamDeclPython := '';
        CallArgs := '';
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := MakePythonIdentifier(Params[j].Name);
          if ParamDeclPython <> '' then
            ParamDeclPython := ParamDeclPython + ', ';
          ParamDeclPython := ParamDeclPython + ParamName + ': ' +
            PascalTypeToPythonType(Params[j].PascalType);
          if CallArgs <> '' then
            CallArgs := CallArgs + ', ';
          CallArgs := CallArgs + ParamName;
        end;

        // Function signature with optional return annotation.
        if IsFunction then
        begin
          RetTypePy := PascalTypeToPythonType(ReturnType);
          InternalCallLines.Add('def ' + InternalCallName + '(' + ParamDeclPython + ') -> ' + RetTypePy + ':');
        end
        else
        begin
          RetTypePy := 'None';
          InternalCallLines.Add('def ' + InternalCallName + '(' + ParamDeclPython + '):');
        end;

        InternalCallLines.Add('    """Wrapper for the original routine ' + PyStrLit(Name) + '.');
        InternalCallLines.Add('    TODO: replace this placeholder with the actual implementation.');
        InternalCallLines.Add('    """');
        InternalCallLines.Add('    if DEBUG_LOG:');
        InternalCallLines.Add('        print(f"[internal_call_' + ApiName + '] called")');
        if IsFunction then
        begin
          InternalCallLines.Add('    # Default return value; replace with actual logic.');
          InternalCallLines.Add('    return ' + PascalTypeDefaultValue(ReturnType));
        end
        else
          InternalCallLines.Add('    pass  # TODO: implement the routine body');
        InternalCallLines.Add('');
      end;
    end;
    InternalCallLines.Add('');

    // =========================================================================
    // 4. Asynchronous logging helper
    // =========================================================================
    LoggingLines.Add('# ==== Asynchronous logging to the beacon ====');
    LoggingLines.Add('');
    LoggingLines.Add('def _send_log_async(msg: str):');
    LoggingLines.Add('    """Fire-and-forget log to the beacon''s agent_log API."""');
    LoggingLines.Add('    def _worker():');
    LoggingLines.Add('        try:');
    LoggingLines.Add('            data = LF_CreateData(AGENT_LOG_API.encode("utf-8"))');
    LoggingLines.Add('            if not data:');
    LoggingLines.Add('                return');
    LoggingLines.Add('            try:');
    LoggingLines.Add('                payload = json.dumps({"message": msg}, ensure_ascii=False).encode("utf-8")');
    LoggingLines.Add('                _write_string(data, payload)');
    LoggingLines.Add('                result = LF_Call(BEACON_APP.encode("utf-8"), data, 3000)');
    LoggingLines.Add('                if result:');
    LoggingLines.Add('                    LF_FreeData(result)');
    LoggingLines.Add('            finally:');
    LoggingLines.Add('                LF_FreeData(data)');
    LoggingLines.Add('        except Exception:');
    LoggingLines.Add('            pass');
    LoggingLines.Add('    threading.Thread(target=_worker, daemon=True).start()');
    LoggingLines.Add('');
    LoggingLines.Add('');

    // =========================================================================
    // 5. API callbacks (@LFCallFunc decorated)
    // =========================================================================
    CallbackLines.Add('# ==== API callbacks ====');
    CallbackLines.Add('');

    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakePythonIdentifier(Name);
        ApiName := UniqueApiName(ApiName, UsedApiNames);
        UsedApiNames.Add(ApiName);

        CallbackName := 'callback_' + ApiName;
        InternalCallName := 'internal_call_' + ApiName;

        // Build parameter extraction code (from the parsed JSON dict) and
        // the comma-separated call argument list.
        ParamExtract := '';
        CallArgs := '';
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := MakePythonIdentifier(Params[j].Name);
          if CallArgs <> '' then
            CallArgs := CallArgs + ', ';
          CallArgs := CallArgs + ParamName;

          // data.get('a') or <default>
          ParamExtract := ParamExtract +
            '        ' + ParamName + ' = data.get(' + PyStrLit(Params[j].Name) + ')';
          if Params[j].PascalType.Same('int64') then
            ParamExtract := ParamExtract + ' or 0'
          else if Params[j].PascalType.Same('double') then
            ParamExtract := ParamExtract + ' or 0.0'
          else if Params[j].PascalType.Same('string') then
            ParamExtract := ParamExtract + ' or ""';
          ParamExtract := ParamExtract + sLineBreak;
        end;

        CallbackLines.Add('@LFCallFunc');
        CallbackLines.Add('def ' + CallbackName + '(_Trigger, _In, _Out):');
        CallbackLines.Add('    """Auto-generated callback for API ' + PyStrLit(Name) + '."""');
        CallbackLines.Add('    try:');
        CallbackLines.Add('        json_bytes = _read_string_bytes(_In)');
        CallbackLines.Add('        if DEBUG_LOG:');
        CallbackLines.Add('            print(f"[' + Name + '] Input JSON: {json_bytes!r}")');
        CallbackLines.Add('');
        CallbackLines.Add('        if not json_bytes:');
        CallbackLines.Add('            _write_string(_Out, json.dumps({"error": "Empty input"}).encode("utf-8"))');
        CallbackLines.Add('            if DEBUG_LOG:');
        CallbackLines.Add('                print(f"[' + Name + '] Error: Empty input")');
        CallbackLines.Add('                _send_log_async(f"[' + Name + '] Error: Empty input")');
        CallbackLines.Add('            return');
        CallbackLines.Add('');
        CallbackLines.Add('        try:');
        CallbackLines.Add('            data = json.loads(json_bytes.decode("utf-8"))');
        CallbackLines.Add('        except Exception as _parse_err:');
        CallbackLines.Add('            _write_string(_Out, json.dumps({"error": f"Invalid JSON: {_parse_err}"}).encode("utf-8"))');
        CallbackLines.Add('            if DEBUG_LOG:');
        CallbackLines.Add('                print(f"[' + Name + '] Invalid JSON: {_parse_err}")');
        CallbackLines.Add('                _send_log_async(f"[' + Name + '] Invalid JSON: {_parse_err}")');
        CallbackLines.Add('            return');
        CallbackLines.Add('');

        if ParamExtract <> '' then
          CallbackLines.Add(ParamExtract);

        if IsFunction then
        begin
          CallbackLines.Add('        ret = ' + InternalCallName + '(' + CallArgs + ')');
          CallbackLines.Add('        _write_string(_Out, json.dumps({"result": ret}, ensure_ascii=False).encode("utf-8"))');
          CallbackLines.Add('        if DEBUG_LOG:');
          CallbackLines.Add('            print(f"[' + Name + '] Called -> {_ret2str(ret)}")');
          CallbackLines.Add('            _send_log_async(f"[' + Name + '] Called -> {_ret2str(ret)}")');
        end
        else
        begin
          CallbackLines.Add('        ' + InternalCallName + '(' + CallArgs + ')');
          CallbackLines.Add('        _write_string(_Out, json.dumps({"status": "ok"}).encode("utf-8"))');
          CallbackLines.Add('        if DEBUG_LOG:');
          CallbackLines.Add('            print(f"[' + Name + '] OK")');
          CallbackLines.Add('            _send_log_async(f"[' + Name + '] OK")');
        end;

        CallbackLines.Add('    except Exception as _err:');
        CallbackLines.Add('        try:');
        CallbackLines.Add('            _write_string(_Out, json.dumps({"error": str(_err)}).encode("utf-8"))');
        CallbackLines.Add('        except Exception:');
        CallbackLines.Add('            pass');
        CallbackLines.Add('        if DEBUG_LOG:');
        CallbackLines.Add('            print(f"[' + Name + '] Exception: {_err}")');
        CallbackLines.Add('            _send_log_async(f"[' + Name + '] Exception: {_err}")');
        CallbackLines.Add('');
        CallbackLines.Add('');
      end;
    end;

    // =========================================================================
    // 6. Tool registration helper
    // =========================================================================
    RegisterToolLines.Add('# ==== Tool registration with the beacon ====');
    RegisterToolLines.Add('');
    RegisterToolLines.Add('def _register_tool(tool_def: dict) -> bool:');
    RegisterToolLines.Add('    """Register a single tool with the beacon via the register_agent API."""');
    RegisterToolLines.Add('    tool_name = tool_def.get("name", "?")');
    RegisterToolLines.Add('    target_app = tool_def.get("target_app", "?")');
    RegisterToolLines.Add('    target_api = tool_def.get("target_api", "?")');
    RegisterToolLines.Add('    if DEBUG_LOG:');
    RegisterToolLines.Add('        print(f"[_register_tool] Registering {tool_name} -> {target_app}.{target_api}")');
    RegisterToolLines.Add('');
    RegisterToolLines.Add('    data = LF_CreateData(REGISTER_API.encode("utf-8"))');
    RegisterToolLines.Add('    if not data:');
    RegisterToolLines.Add('        if DEBUG_LOG:');
    RegisterToolLines.Add('            print(f"[_register_tool] Failed to create data handle")');
    RegisterToolLines.Add('        return False');
    RegisterToolLines.Add('    try:');
    RegisterToolLines.Add('        payload = json.dumps(tool_def, ensure_ascii=False).encode("utf-8")');
    RegisterToolLines.Add('        _write_string(data, payload)');
    RegisterToolLines.Add('        result = LF_Call(BEACON_APP.encode("utf-8"), data, 5000)');
    RegisterToolLines.Add('        if not result:');
    RegisterToolLines.Add('            if DEBUG_LOG:');
    RegisterToolLines.Add('                print(f"[_register_tool] No response from beacon")');
    RegisterToolLines.Add('            return False');
    RegisterToolLines.Add('        try:');
    RegisterToolLines.Add('            resp_bytes = _read_string_bytes(result)');
    RegisterToolLines.Add('            if not resp_bytes:');
    RegisterToolLines.Add('                if DEBUG_LOG:');
    RegisterToolLines.Add('                    print(f"[_register_tool] Empty response")');
    RegisterToolLines.Add('                return False');
    RegisterToolLines.Add('            resp = json.loads(resp_bytes.decode("utf-8"))');
    RegisterToolLines.Add('            if resp.get("status") == "ok":');
    RegisterToolLines.Add('                if DEBUG_LOG:');
    RegisterToolLines.Add('                    print(f"[_register_tool] OK: {tool_name}")');
    RegisterToolLines.Add('                return True');
    RegisterToolLines.Add('            if DEBUG_LOG:');
    RegisterToolLines.Add('                print(f"[_register_tool] Error: {resp.get(''message'', ''?'')}")');
    RegisterToolLines.Add('            return False');
    RegisterToolLines.Add('        finally:');
    RegisterToolLines.Add('            LF_FreeData(result)');
    RegisterToolLines.Add('    finally:');
    RegisterToolLines.Add('        LF_FreeData(data)');
    RegisterToolLines.Add('');
    RegisterToolLines.Add('');

    // =========================================================================
    // 7. RegisterTools() – advertise every API with a JSON schema
    //
    // FIX: total_count must be assigned BEFORE the f-string print that
    // references it. Python treats any name assigned in the function body
    // as a local variable, so referring to it earlier raised
    // UnboundLocalError.
    // =========================================================================
    RegisterToolsLines.Add('# ==== RegisterTools ====');
    RegisterToolsLines.Add('');
    RegisterToolsLines.Add('def RegisterTools() -> bool:');
    RegisterToolsLines.Add('    """Register all supported routines as tools with the beacon."""');
    RegisterToolsLines.Add('    total_count = ' + umlIntToStr(TotalFuncCount));
    RegisterToolsLines.Add('    reg_count = 0');
    RegisterToolsLines.Add('    if DEBUG_LOG:');
    RegisterToolsLines.Add('        print(f"[RegisterTools] Starting registration of {total_count} tools...")');
    RegisterToolsLines.Add('');

    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakePythonIdentifier(Name);
        ApiName := UniqueApiName(ApiName, UsedApiNames);
        UsedApiNames.Add(ApiName);

        Description := GetFullDescription(Comment);
        if Description = '' then
          Description := 'Auto-generated tool for ' + Name;

        RegisterToolsLines.Add('    tool_def = {');
        RegisterToolsLines.Add('        "name": ' + PyStrLit(ApiName) + ',');
        RegisterToolsLines.Add('        "description": ' + PyStrLit(Description) + ',');
        RegisterToolsLines.Add('        "target_app": MY_APP_NAME,');
        RegisterToolsLines.Add('        "target_api": ' + PyStrLit(ApiName) + ',');
        RegisterToolsLines.Add('        "parameters": {');
        RegisterToolsLines.Add('            "type": "object",');
        RegisterToolsLines.Add('            "properties": {');

        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;

          PropJson := '                ' + PyStrLit(ParamName) + ': {"type": ' +
            PyStrLit(PascalTypeToJsonSchemaType(Params[j].PascalType));
          if Params[j].Description <> '' then
            PropJson := PropJson + ', "description": ' + PyStrLit(Params[j].Description)
          else
            PropJson := PropJson + ', "description": ' + PyStrLit(ParamName + ' parameter');
          PropJson := PropJson + '},';
          RegisterToolsLines.Add(PropJson);
        end;

        RegisterToolsLines.Add('            },');

        // Build the required list.
        RequiredList := '';
        for j := 0 to High(Params) do
        begin
          if Params[j].Name = '' then
            ParamName := 'p' + umlIntToStr(j)
          else
            ParamName := Params[j].Name;
          if RequiredList <> '' then
            RequiredList := RequiredList + ', ';
          RequiredList := RequiredList + PyStrLit(ParamName);
        end;
        if RequiredList <> '' then
          RegisterToolsLines.Add('            "required": [' + RequiredList + '],')
        else
          RegisterToolsLines.Add('            "required": [],');

        RegisterToolsLines.Add('        },');
        RegisterToolsLines.Add('    }');
        RegisterToolsLines.Add('    if _register_tool(tool_def):');
        RegisterToolsLines.Add('        reg_count += 1');
        RegisterToolsLines.Add('');
      end;
    end;

    RegisterToolsLines.Add('    if DEBUG_LOG:');
    RegisterToolsLines.Add('        print(f"[RegisterTools] Registered {reg_count} / {total_count}")');
    RegisterToolsLines.Add('    return reg_count == total_count');
    RegisterToolsLines.Add('');
    RegisterToolsLines.Add('');

    // =========================================================================
    // 8. RegisterAPIs() – create the app and register every callback
    // =========================================================================
    RegisterAPIsLines.Add('# ==== RegisterAPIs ====');
    RegisterAPIsLines.Add('');
    RegisterAPIsLines.Add('def RegisterAPIs() -> Optional[Any]:');
    RegisterAPIsLines.Add('    """Create the LingoFuse app and register all API callbacks."""');
    RegisterAPIsLines.Add('    app = LF_CreateApp(MY_APP_NAME.encode("utf-8"), MY_APP_DESC.encode("utf-8"))');
    RegisterAPIsLines.Add('    if not app:');
    RegisterAPIsLines.Add('        if DEBUG_LOG:');
    RegisterAPIsLines.Add('            print(f"[RegisterAPIs] Failed to create app")');
    RegisterAPIsLines.Add('        return None');
    RegisterAPIsLines.Add('');
    RegisterAPIsLines.Add('    if DEBUG_LOG:');
    RegisterAPIsLines.Add('        print(f"[RegisterAPIs] Application \''{MY_APP_NAME}\'' created")');
    RegisterAPIsLines.Add('');

    UsedApiNames.Clear;
    for i := 0 to High(SupportedFuncs) do
    begin
      with SupportedFuncs[i] do
      begin
        ApiName := MakePythonIdentifier(Name);
        ApiName := UniqueApiName(ApiName, UsedApiNames);
        UsedApiNames.Add(ApiName);
        CallbackName := 'callback_' + ApiName;
        Description := GetFullDescription(Comment);
        if Description = '' then
          Description := 'Auto-generated API for ' + Name;

        RegisterAPIsLines.Add('    LF_RegisterCall(');
        RegisterAPIsLines.Add('        app,');
        RegisterAPIsLines.Add('        ' + PyStrLit(ApiName) + '.encode("utf-8"),');
        RegisterAPIsLines.Add('        ' + PyStrLit(Description) + '.encode("utf-8"),');
        RegisterAPIsLines.Add('        None,');
        RegisterAPIsLines.Add('        ' + CallbackName + ',');
        RegisterAPIsLines.Add('    )');
      end;
    end;

    RegisterAPIsLines.Add('');
    RegisterAPIsLines.Add('    if DEBUG_LOG:');
    RegisterAPIsLines.Add('        print(f"[RegisterAPIs] Registered ' + umlIntToStr(TotalFuncCount) + ' APIs")');
    RegisterAPIsLines.Add('');
    RegisterAPIsLines.Add('    return app');
    RegisterAPIsLines.Add('');
    RegisterAPIsLines.Add('');

    // =========================================================================
    // 9. Execute_And_Reg_all() + __main__ entry point
    // =========================================================================
    ExecuteLines.Add('# ==== One-click startup ====');
    ExecuteLines.Add('');
    ExecuteLines.Add('def Execute_And_Reg_all() -> bool:');
    ExecuteLines.Add('    """');
    ExecuteLines.Add('    Full startup sequence:');
    ExecuteLines.Add('        1. RegisterAPIs         – create app and register callbacks.');
    ExecuteLines.Add('        2. LF_PrepareClient     – connect to the beacon via IPC_ENDPOINT.');
    ExecuteLines.Add('        3. LF_PrepareDone       – wait until the connection is ready.');
    ExecuteLines.Add('        4. RegisterTools        – advertise all APIs as tools.');
    ExecuteLines.Add('    """');
    ExecuteLines.Add('    app = RegisterAPIs()');
    ExecuteLines.Add('    if app is None:');
    ExecuteLines.Add('        if DEBUG_LOG:');
    ExecuteLines.Add('            print(f"[Execute_And_Reg_all] RegisterAPIs failed")');
    ExecuteLines.Add('        return False');
    ExecuteLines.Add('');
    ExecuteLines.Add('    LF_ResetPrepare()');
    ExecuteLines.Add('    LF_PrepareClient(IPC_ENDPOINT.encode("utf-8"), app)');
    ExecuteLines.Add('    if LF_PrepareDone() > 0:');
    ExecuteLines.Add('        return RegisterTools()');
    ExecuteLines.Add('    if DEBUG_LOG:');
    ExecuteLines.Add('        print(f"[Execute_And_Reg_all] LF_PrepareDone failed")');
    ExecuteLines.Add('    return False');
    ExecuteLines.Add('');
    ExecuteLines.Add('');
    ExecuteLines.Add('# ==== Main entry point ====');
    ExecuteLines.Add('');
    ExecuteLines.Add('if __name__ == "__main__":');
    ExecuteLines.Add('    print(f"=== {MY_APP_NAME} tool provider ===")');
    ExecuteLines.Add('    if not Execute_And_Reg_all():');
    ExecuteLines.Add('        print("Startup failed.")');
    ExecuteLines.Add('        sys.exit(1)');
    ExecuteLines.Add('    print("Ready. Type ''exit'' and press Enter to quit.")');
    ExecuteLines.Add('    try:');
    ExecuteLines.Add('        while True:');
    ExecuteLines.Add('            line = input()');
    ExecuteLines.Add('            if line.strip().lower() == "exit":');
    ExecuteLines.Add('                break');
    ExecuteLines.Add('    except (KeyboardInterrupt, EOFError):');
    ExecuteLines.Add('        pass');
    ExecuteLines.Add('    LF_ExitMainThread()');
    ExecuteLines.Add('    LF_Shutdown()');
    ExecuteLines.Add('    print("Shutdown complete.")');
    ExecuteLines.Add('');

    // =========================================================================
    // 10. Assemble the final output
    // =========================================================================
    ResultLines := TPascalStringList.Create;
    ResultLines.AddStrings(HeaderLines);
    ResultLines.Add('');
    ResultLines.Add('');
    ResultLines.AddStrings(HelperLines);
    ResultLines.AddStrings(InternalCallLines);
    ResultLines.AddStrings(LoggingLines);
    ResultLines.AddStrings(CallbackLines);
    ResultLines.AddStrings(RegisterToolLines);
    ResultLines.AddStrings(RegisterToolsLines);
    ResultLines.AddStrings(RegisterAPIsLines);
    ResultLines.AddStrings(ExecuteLines);

    Result := ResultLines;
    Log(PFormat('Generated %d lines of Python code for %d supported routines.',
      [ResultLines.Count, TotalFuncCount]));

  finally
    HeaderLines.Free;
    HelperLines.Free;
    InternalCallLines.Free;
    LoggingLines.Free;
    CallbackLines.Free;
    RegisterToolLines.Free;
    RegisterToolsLines.Free;
    RegisterAPIsLines.Free;
    ExecuteLines.Free;
    UsedApiNames.Free;
    // ResultLines is returned to the caller; do not free here.
  end;
end;

end.
