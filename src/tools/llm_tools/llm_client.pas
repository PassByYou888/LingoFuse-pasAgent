(*
 * ============================================================================
 * llm_client — Pascal client for LingoFuse LLM Service (v3.3)
 * ============================================================================
 *
 * Purpose
 * -------
 * This unit provides a high-level, event-driven Pascal client for a
 * LingoFuse LLM service. It speaks the structured streaming protocol
 * defined by llm_service.py / llm_proxy.py (v3.0 protocol), and it is
 * the reference client used by the Pascal GUI tool (llm_tool_frm.pas).
 *
 * Two backends, one protocol
 * --------------------------
 * The LingoFuse LLM service can be one of two sibling implementations,
 * both exposing the SAME Call API surface on the SAME endpoint
 * (default: ipc:llm_service, app name: LLM_Service):
 *
 *   llm_service.py  (server_kind = "service")
 *       A local inference server (llama.cpp or transformers). It owns
 *       an in-process model, a session registry, and a global default
 *       system message. Because it holds the model's KV cache, it can
 *       support persistent sessions with a fixed system message.
 *
 *   llm_proxy.py    (server_kind = "proxy")
 *       A stateless forwarder to an external OpenAI-compatible HTTP
 *       backend (LM Studio, Ollama, vLLM, DeepSeek, OpenRouter, ...).
 *       It does NOT own the model, and it does NOT maintain any global
 *       default state. Every generate request is translated into an
 *       HTTP POST to the backend, and the SSE stream is relayed back
 *       over LingoFuse notifications.
 *
 * Because only one of the two can bind ipc:llm_service at a time, this
 * client transparently works against either one. All Call API methods
 * behave identically EXCEPT SetSystemMessage, which is discussed below.
 *
 * API capability discovery
 * ------------------------
 * Both server kinds expose a `get_api_capabilities` Call API that
 * returns a capability matrix:
 *
 *     {
 *       "code": 0,
 *       "server_kind": "service" | "proxy",
 *       "capabilities": {
 *           "generate":           1,
 *           "create_session":     1,
 *           "close_session":      1,
 *           "cancel_session":     1,
 *           "list_sessions":      1,
 *           "set_system_message": 1 | 0,
 *           "health":             1,
 *           "llm_stream":         1
 *       }
 *     }
 *
 * A value of 1 means "supported by this server", 0 means "not
 * supported" (the API belongs to the sibling server kind).
 *
 * This client fetches the matrix once, right after Connect succeeds,
 * and caches it in FCapabilities. The public helpers are:
 *
 *   HasCapabilityInfo             -> True if the matrix was fetched.
 *   LLMSupported(api_name)        -> True if api_name maps to 1.
 *   ServerKind                    -> "service" | "proxy" | "".
 *   GetAPICapabilities(..., err)  -> raw JSON, for callers that want
 *                                    to inspect or display the whole
 *                                    matrix themselves.
 *
 * Backward compatibility: servers older than the capability API
 * will fail the fetch, HasCapabilityInfo stays False, and
 * LLMSupported returns False for every name. Callers that gate on
 * HasCapabilityInfo (as SetSystemMessage does) fall back to
 * unconditional invocation in that case.
 *
 * API surface (identical between the two backends, except where noted)
 * -------------------------------------------------------------------
 *   Connect / Disconnect                    connection lifecycle
 *   CreateSession                           create a persistent session
 *   CloseSession / CancelSession            session teardown
 *   ListSessions                            enumerate this client's sessions
 *   Generate / GenerateCurrent              send a prompt, stream the reply
 *   SetSystemMessage                        (see limitations below)
 *   Health                                  query server status
 *   GetAPICapabilities                      fetch the capability matrix
 *   LLMSupported                            capability predicate
 *
 * set_system_message is NOT supported by llm_proxy.py
 * ---------------------------------------------------
 * llm_service.py supports set_system_message: it updates an in-process
 * global default that applies to sessions created AFTER the call.
 *
 * llm_proxy.py explicitly rejects this API. The proxy is stateless: the
 * system message of a session is captured at session-creation time and
 * cannot be changed afterwards, because the backend would have to
 * re-process the entire message history from a different context. This
 * is impossible without invalidating the model's KV cache.
 *
 * When SetSystemMessage is called against llm_proxy.py, the response is:
 *
 *     {"code": -1, "status": "unsupported", "error": "..."}
 *
 * This Pascal method returns False and fills AError with a friendly
 * message. If the capability matrix has already been fetched, the
 * method short-circuits locally without an RPC round-trip. Callers MUST
 * be prepared for this failure and MUST NOT treat it as a network error.
 *
 * Recommended workflow
 * --------------------
 * To use a custom system message, ALWAYS pass it through CreateSession:
 *
 *     LLM.CreateSession(sys_msg, sid, err);
 *     LLM.Generate(content, prompt, sid, err);   // continue that session
 *
 * If you want a different system message later, create a NEW session:
 *
 *     LLM.CloseSession(old_sid, True, err);
 *     LLM.CreateSession(new_sys_msg, new_sid, err);
 *
 * This workflow works identically against llm_service.py and
 * llm_proxy.py, and it is what llm_tool_frm.pas uses.
 *
 * Default system message when CreateSession omits it
 * --------------------------------------------------
 * The two backends behave differently when the client calls
 * CreateSession without a system_message argument:
 *
 *   llm_service.py  -> uses its process-wide default system message
 *                      (set via --system-message on the command line,
 *                      or via set_system_message at runtime)
 *   llm_proxy.py    -> uses an empty system message; the backend's
 *                      own chat template decides the default behaviour
 *
 * Clients that need deterministic behaviour should always pass an
 * explicit system_message to CreateSession, even if it is empty.
 *
 * Thread model
 * ------------
 * The streaming notify callback (OnLLMStream) is registered with
 * RegisterNotifySync, which means it executes on the LingoFuse main
 * thread (the thread that called LF.PrepareDone). The five user-facing
 * events (OnChunk / OnThink / OnFinish / OnError / OnClosed) are all
 * dispatched from that thread.
 *
 * Consumers MAY safely touch UI components (VCL / LCL) inside event
 * handlers, as long as the LingoFuse main thread is the same thread
 * that owns the UI. For llm_tool_frm.pas, that condition holds.
 *
 * Call API methods (Generate, CreateSession, ...) block on the calling
 * thread. They should NOT be called from within an event handler,
 * because the event handler is itself running on the LingoFuse main
 * thread and would deadlock LF_Call. Use a worker thread if you need
 * to issue a Call from within a callback.
 *
 * Unicode
 * -------
 * All Call API payloads are serialized to UTF-8 bytes and transmitted
 * with LF_WriteStringBytes (which appends a trailing NUL). Responses
 * are read with LF_ReadStringBytes, which stops at the first NUL and
 * strips it. This bypasses the AnsiString conversion path entirely, so
 * Chinese text, emoji and other non-ASCII content survive intact across
 * the whole call chain, including the backend HTTP hop performed by
 * llm_proxy.py.
 *
 * Author: LingoFuse-pasAgent project
 * ============================================================================
 *)

unit llm_client;

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\..\zNetV2\source\Z.Define.inc}

interface

uses
  Classes, SysUtils, SyncObjs,
  lingofuse_helper, lingofuse_import,
  Z.Core, Z.Json, Z.PascalStrings, Z.UPascalStrings, Z.Status;

const
  (* Name of the streaming Notify API on the server. Must match the
     server's --notify-api setting (default: 'llm_stream'). *)
  API_NAME_STREAM = 'llm_stream';

  (* Call API names. These match the @server.expose decorators in
     llm_service.py and llm_proxy.py verbatim. *)
  API_NAME_GENERATE = 'generate';
  API_NAME_CREATE_SESSION = 'create_session';
  API_NAME_CLOSE_SESSION = 'close_session';
  API_NAME_CANCEL_SESSION = 'cancel_session';
  API_NAME_LIST_SESSIONS = 'list_sessions';
  API_NAME_SET_SYSTEM_MESSAGE = 'set_system_message';
  API_NAME_GET_CAPABILITIES = 'get_api_capabilities';
  API_NAME_HEALTH = 'health';

type
  (* --------------------------------------------------------------------------
     Streaming event types (aligned with LLM Service v3.0 protocol).

     The server emits structured JSON messages on the notify API. Each
     message has a "type" field that determines its meaning:

       {"type": "chunk",  "session_id": "...", "text": "..."}
           A piece of the final answer. Clients append the text to the
           output as it arrives.

       {"type": "think",  "session_id": "...", "text": "..."}
           A piece of the reasoning chain, emitted only by reasoning
           models (Nemotron, DeepSeek-R1, Qwen3-thinking, ...). Clients
           that do not render the reasoning chain should simply ignore
           these messages; the final answer will still arrive as chunks.

       {"type": "finish", "session_id": "...", "reason": "stop|..."}
           Signals that generation has completed. The "reason" field
           takes one of: "stop" (normal), "error" (backend failure),
           or "cancelled" (client cancellation).

       {"type": "error",  "session_id": "...", "message": "..."}
           The backend reported an error for this session. The client
           should surface the message to the user and expect no further
           chunks for the session.

       {"type": "closed", "session_id": "...", "reason": "..."}
           The session has been closed, either by the client
           (reason="client"), by the server's idle watchdog
           (reason="timeout"), or because the server is shutting down
           (reason="shutdown"). No further messages will arrive for
           this session.

     All event callbacks are invoked on the LingoFuse main thread, so
     consumers can safely touch UI components or other thread-affine
     objects from within them.
     -------------------------------------------------------------------------- *)

  (* Delivers a "chunk" event: a piece of the final answer text. *)
  TLLMChunkEvent = procedure(const SessionId, Text: string) of object;

  (* Delivers a "think" event: a piece of the reasoning chain. *)
  TLLMThinkEvent = procedure(const SessionId, Text: string) of object;

  (* Delivers a "finish" event: generation ended with the given reason. *)
  TLLMFinishEvent = procedure(const SessionId, Reason: string) of object;

  (* Delivers an "error" event: the backend reported a failure. *)
  TLLMErrorEvent = procedure(const SessionId, ErrorMsg: string) of object;

  (* Delivers a "closed" event: the session is now gone. *)
  TLLMClosedEvent = procedure(const SessionId, Reason: string) of object;

  TLLMClient = class
  private
    FApp: LF.TAppHandle;
    FServerApp: string;
    FEndpoint: string;
    FTimeout: integer;
    FConnected: boolean;

    (* FPrepared is True after LF.PrepareDone has returned success once,
       independently of whether the subsequent App setup steps succeeded.
       Disconnect uses this flag to ensure the LingoFuse main thread is
       always terminated, even if Connect aborted midway. Without this
       flag, a partial Connect could leave the main thread running and
       prevent the process from shutting down cleanly. *)
    FPrepared: boolean;

    (* The session ID most recently used by Generate. When ASessionId is
       empty in a Generate call, FCurrentSessionId is used as the fallback
       target. Updated automatically by CreateSession and Generate. *)
    FCurrentSessionId: string;

    (* A process-unique application name for this client, generated by
       LF.Generate_AppName after PrepareDone succeeds. This value is sent
       as "client_name" in every Call API request, and it is what the
       server uses to route streaming notifications back to us. *)
    FClientName: string;

    (* Cached API capability matrix, as returned by the server's
       get_api_capabilities Call API. This object holds ONLY the
       "capabilities" sub-dictionary (the {api_name -> 0|1} mapping);
       the enclosing envelope is discarded after the fetch.

       nil => the matrix has not been fetched successfully (either the
              Connect has not happened yet, or the fetch failed, for
              example because the server is an older version that does
              not expose get_api_capabilities).

       When this is nil, HasCapabilityInfo returns False and
       LLMSupported returns False for every name; callers that need to
       distinguish "unknown" from "unsupported" must consult
       HasCapabilityInfo first. *)
    FCapabilities: TZ_JsonObject;

    (* The server_kind field reported by get_api_capabilities:
       "service" for llm_service.py, "proxy" for llm_proxy.py.
       Empty string when the matrix has not been fetched. *)
    FServerKind: string;

    (* User-assigned event handlers. All five are optional; unassigned
       handlers are silently skipped when the corresponding message
       arrives. *)
    FOnChunk: TLLMChunkEvent;
    FOnThink: TLLMThinkEvent;
    FOnFinish: TLLMFinishEvent;
    FOnError: TLLMErrorEvent;
    FOnClosed: TLLMClosedEvent;

    (* Internal notify handler. Registered with RegisterNotifySync so it
       runs on the LingoFuse main thread. Parses the JSON message and
       dispatches it to the appropriate user-facing event. *)
    procedure OnLLMStream(Input_: TDataHnd___);

    (* Internal dispatchers. Each one checks whether the corresponding
       event handler is assigned, and if so invokes it. *)
    procedure DoChunk(const SessionId, Text: string);
    procedure DoThink(const SessionId, Text: string);
    procedure DoFinish(const SessionId, Reason: string);
    procedure DoError(const SessionId, ErrorMsg: string);
    procedure DoClosed(const SessionId, Reason: string);

    (* Releases any partial resources acquired during a failed Connect,
       and optionally terminates the LingoFuse main thread.

       AExitMainThread should be True only when LF.PrepareDone has already
       returned success in this client's lifetime. If PrepareDone failed
       or was never reached, the main thread is not running and calling
       LF.ExitMainThread would be a no-op (or could interfere with other
       clients of the same process). *)
    procedure CleanupPartialConnect(AExitMainThread: boolean);

    (* Sends a Call API request as a raw UTF-8 byte payload and returns
       the raw UTF-8 byte response. Bypasses `string` so that non-ASCII
       payloads (Chinese content, emoji, etc.) survive intact.

       The request is written with LF_WriteStringBytes (which appends a
       trailing NUL); the response is read with LF_ReadStringBytes (which
       stops at the first NUL and strips it). *)
    function CallAPI(const APIName: string; const RequestBytes: TBytes; out ResponseBytes: TBytes;
      out AError: string): boolean;

    (* Fetches the server's API capability matrix and caches it into
       FCapabilities / FServerKind.

       This is a best-effort operation:
         - On success, FCapabilities holds the {api_name -> 0|1}
           sub-dictionary, FServerKind holds "service" or "proxy", and
           the function returns True.
         - On failure (transport error, invalid JSON, non-zero code,
           or a server that predates the capability API), FCapabilities
           is reset to nil, FServerKind is cleared, AError describes
           the failure, and the function returns False. The caller is
           expected to continue without capability information; this is
           the backward-compatibility path.

       The Connect method calls this right after the connection is
       established. Callers may also invoke it explicitly to refresh
       the cache after a server restart or a configuration change. *)
    function FetchCapabilities(out AError: string): boolean;
  public
    (* Creates a client for the given server. No network activity happens
       here; call Connect to actually establish the connection.

       Parameters:
         AServerApp   LingoFuse application name of the server.
                      Usually 'LLM_Service'. Sent as the target app name
                      in every LF_Call.
         AEndpoint    LingoFuse endpoint. Can be IPC (ipc:llm_service)
                      or TCP (host:port).
         ATimeout     Default timeout for Call API requests, in
                      milliseconds. Individual methods do not override
                      this value. *)
    constructor Create(const AServerApp, AEndpoint: string; ATimeout: integer = 10000);
    destructor Destroy; override;

    (* Connects to the LingoFuse service. On success, FClientName is set
       to a unique application name and the notify callback is registered.
       On failure, ErrorMsg contains the reason and FConnected stays False.

       The connection sequence is:
         1. LF.ResetPrepare to clear any previous preparation state
         2. LF.PrepareClient(endpoint, nil) to open a consumer connection
         3. LF.PrepareDone to start the LingoFuse main thread
         4. LF.Generate_AppName to obtain a unique client name
         5. Create an App and register the notify callback with
            RegisterNotifySync on the 'llm_stream' API
         6. LF_BindApp to attach the App to the client
         7. Best-effort fetch of the API capability matrix (see
            FetchCapabilities). A failure here does NOT fail Connect;
            the client continues to work but HasCapabilityInfo stays
            False and LLMSupported returns False for every name.

       Connect is idempotent: calling it on an already-connected client
       is a no-op that returns True. If a previous Connect aborted
       halfway, its partial state is cleaned up before retrying. *)
    function Connect(out ErrorMsg: string): boolean;

    (* Disconnects from the service, terminating the LingoFuse main thread
       and releasing all resources owned by this client.

       Safe to call when not connected. After Disconnect, the client can
       be re-connected by calling Connect again. *)
    procedure Disconnect;

    (* ------------------------------------------------------------------
       Session management
       ------------------------------------------------------------------ *)

    (* Creates a new persistent session bound to this client's app name.
       If ASystemMessage is non-empty, that system message is snapshotted
       into the session; otherwise the backend's default behaviour
       applies (see the unit header for the difference between
       llm_service.py and llm_proxy.py).

       On success, ASessionId receives the new session ID and
       FCurrentSessionId is updated to match. *)
    function CreateSession(out ASessionId, AError: string): boolean; overload;
    function CreateSession(const ASystemMessage: string; out ASessionId, AError: string): boolean; overload;

    (* Closes a session. If ACancelRunning is True, any in-flight
       generation for that session is cancelled. A "closed" notification
       is sent to this client afterwards, which triggers OnClosed.

       If the closed session is the current session, FCurrentSessionId
       is cleared. *)
    function CloseSession(const ASessionId: string; ACancelRunning: boolean; out AError: string): boolean;

    (* Cancels the current generation of a session but keeps the session
       alive. The next Generate on the same session will continue with
       the accumulated history.

       Unlike CloseSession, this does not remove the session and does
       not clear FCurrentSessionId. *)
    function CancelSession(const ASessionId: string; out AError: string): boolean;

    (* Lists all sessions belonging to this client. Returns the raw JSON
       response so the caller can iterate over the sessions array.

       The session information includes: session_id, client_name,
       created_at, last_active_at, status, and message_count. *)
    function ListSessions(out ASessionsJson, AError: string): boolean;

    (* ------------------------------------------------------------------
       Generation
       ------------------------------------------------------------------ *)

    (* Sends a generate request. This call returns quickly with a task_id;
       the actual generation is streamed back asynchronously through the
       OnChunk / OnThink / OnFinish events.

       ASessionId semantics (IN/OUT):
         - Non-empty on input: continue that session.
         - Empty on input, FCurrentSessionId non-empty: use that.
         - Empty on input, FCurrentSessionId empty: the server creates
           a new session and the assigned ID is written back.
         - On success, ASessionId is updated with the effective session
           ID and FCurrentSessionId follows it.

       NOTE: this is a single method (not overloaded). FPC encodes `var`
       and `out` parameters with the same type signature, so an `out`
       overload would collide with the `var` variant at compile time. *)
    function Generate(const AContent, APrompt: string; var ASessionId: string;
      out AError: string): boolean;

    (* Convenience wrapper: continues the client's current session without
       requiring the caller to pass one. Uses FCurrentSessionId. *)
    function GenerateCurrent(const AContent, APrompt: string; out AError: string): boolean;

    (* ------------------------------------------------------------------
       Server-wide settings
       ------------------------------------------------------------------ *)

    (* Updates the server-wide default system message. Affects only
       sessions created AFTER the call.

       IMPORTANT — llm_proxy.py compatibility:
         llm_service.py supports this API. llm_proxy.py does NOT; it
         returns {"code": -1, "status": "unsupported", "error": "..."}
         and this method therefore returns False.

         If the capability matrix has already been fetched (see
         HasCapabilityInfo), the method detects the unsupported status
         locally and returns immediately with a friendly error message
         that explains the alternative workflow. Otherwise it performs
         the call and passes back whatever error the server reports.

         Callers MUST be prepared for this failure. To use a custom
         system message against llm_proxy.py, pass it to CreateSession
         instead. See the unit header for the recommended workflow. *)
    function SetSystemMessage(const AMessage: string; out AError: string): boolean;

    (* Queries the server for its health/status. Returns the raw JSON
       response so the caller can inspect arbitrary fields.

       The response differs between backends:
         llm_service.py includes backend, model, context_size_actual,
           queue_size, chat_template_path, server_kind,
           api_capabilities, ...
         llm_proxy.py   includes backend_url, backend_model,
           backend_auth_configured, server_kind, api_capabilities, ...
       Both include session counts and limits. *)
    function Health(out AHealthJson, AError: string): boolean;

    (* ------------------------------------------------------------------
       Capability discovery
       ------------------------------------------------------------------ *)

    (* Fetches the server's API capability matrix and returns it as a raw
       JSON string. The same information that Connect fetches
       automatically; call this explicitly to refresh the cache or to
       inspect the whole matrix yourself.

       On success, the returned JSON has the shape:

           {
             "code": 0,
             "server_kind": "service" | "proxy",
             "capabilities": {
                 "generate": 1,
                 "set_system_message": 0,
                 ...
             }
           }

       The internal cache (FCapabilities) is updated as a side effect,
       so a subsequent call to LLMSupported or HasCapabilityInfo will
       reflect the freshly fetched matrix. *)
    function GetAPICapabilities(out ACapabilitiesJson, AError: string): boolean;

    (* Returns True if the API capability matrix has been successfully
       fetched and cached. When this is False, LLMSupported returns
       False for every name, but that should be interpreted as
       "unknown" rather than "unsupported". Callers that need to
       distinguish the two must check this predicate explicitly.

       The matrix is fetched automatically by Connect. It remains nil
       if the server is an older version that does not expose the
       get_api_capabilities API. *)
    function HasCapabilityInfo: boolean;

    (* Returns True if the server supports the given API name.

       Semantics (see also HasCapabilityInfo):
         - capability info available, name present with value 1 -> True
         - capability info available, name present with value 0 -> False
         - capability info available, name absent              -> False
         - capability info NOT available                       -> False
           (callers should consult HasCapabilityInfo first if they
            need to distinguish "unsupported" from "unknown")

       A missing entry is treated as unsupported, matching the
       server-side convention where only value 1 means "supported". *)
    function LLMSupported(const AAPIName: string): boolean;

    (* Events (all callbacks are executed on the main thread). *)
    property OnChunk: TLLMChunkEvent read FOnChunk write FOnChunk;
    property OnThink: TLLMThinkEvent read FOnThink write FOnThink;
    property OnFinish: TLLMFinishEvent read FOnFinish write FOnFinish;
    property OnError: TLLMErrorEvent read FOnError write FOnError;
    property OnClosed: TLLMClosedEvent read FOnClosed write FOnClosed;

    (* Convenience accessors.

       CurrentSessionId is read/write; setting it manually is allowed
       but rare. ClientName is assigned once by Connect and is
       read-only afterwards. Connected reflects the current connection
       state. ServerKind is "" when the capability matrix has not been
       fetched, "service" for llm_service.py, "proxy" for llm_proxy.py. *)
    property CurrentSessionId: string read FCurrentSessionId write FCurrentSessionId;
    property ClientName: string read FClientName;
    property Connected: boolean read FConnected;
    property ServerKind: string read FServerKind;
  end;

implementation

{ ----------------------------------------------------------------------------
  CallAPI helper (byte-level JSON I/O)
  ---------------------------------------------------------------------------- }

function TLLMClient.CallAPI(const APIName: string; const RequestBytes: TBytes;
  out ResponseBytes: TBytes; out AError: string): boolean;
var
  hnd, res: TDataHnd;
begin
  Result := False;
  SetLength(ResponseBytes, 0);
  AError := '';

  // Refuse to send anything if the client has not been connected yet.
  // This protects the caller from a confusing "null handle" failure
  // deeper in LingoFuse.
  if not FConnected then
  begin
    AError := 'Not connected to LingoFuse service';
    Exit;
  end;

  // Allocate a fresh data handle named after the target API. The API
  // name is the string used by the server's @server.expose decorator
  // (e.g., 'generate', 'create_session').
  hnd := LF_CreateDataEx(APIName);
  if hnd = nil then
  begin
    AError := 'LF_CreateDataEx returned nil for API "' + APIName + '"';
    Exit;
  end;
  try
    // LF_WriteStringBytes writes the payload followed by a NUL terminator,
    // which the server-side LF_ReadString expects. Note that the payload
    // is already a TBytes holding UTF-8 JSON; we never round-trip it
    // through a Pascal `string`, which would risk AnsiString conversion
    // issues on non-UTF-8 code pages.
    if not LF_WriteStringBytes(hnd, RequestBytes) then
    begin
      AError := 'LF_WriteStringBytes failed for API "' + APIName + '"';
      Exit;
    end;

    // Perform the synchronous remote call. FServerApp is the target
    // application name registered on the server (usually 'LLM_Service').
    // FTimeout is in milliseconds.
    res := LF_CallEx(FServerApp, hnd, FTimeout);
    if res = nil then
    begin
      AError := 'LF_CallEx returned nil for API "' + APIName + '" (timeout or network error)';
      Exit;
    end;
    try
      // An empty result handle (size 0) usually means the API was not
      // found on the server, or the server returned an empty payload.
      if LF_GetSize(res) <= 0 then
      begin
        AError := 'Empty response from API "' + APIName + '"';
        Exit;
      end;

      LF_SetPos(res, 0);
      // LF_ReadStringBytes reads up to the first NUL and strips it,
      // giving us the raw JSON bytes without the trailing terminator.
      if not LF_ReadStringBytes(res, ResponseBytes) then
      begin
        AError := 'LF_ReadStringBytes failed for API "' + APIName + '"';
        Exit;
      end;
      if Length(ResponseBytes) = 0 then
      begin
        AError := 'Empty response from API "' + APIName + '"';
        Exit;
      end;

      Result := True;
    finally
      LF_FreeData(res);
    end;
  finally
    LF_FreeData(hnd);
  end;
end;

{ ----------------------------------------------------------------------------
  Construction / destruction
  ---------------------------------------------------------------------------- }

constructor TLLMClient.Create(const AServerApp, AEndpoint: string; ATimeout: integer);
begin
  inherited Create;
  FServerApp := AServerApp;
  FEndpoint := AEndpoint;
  FTimeout := ATimeout;
  FConnected := False;
  FPrepared := False;
  FApp := nil;
  FClientName := '';
  FCurrentSessionId := '';
  FCapabilities := nil;
  FServerKind := '';
end;

destructor TLLMClient.Destroy;
begin
  // Disconnect is idempotent and safe to call from the destructor even
  // if the client was never connected. It also frees FCapabilities.
  Disconnect;

  // Defensive: if Disconnect exited early for some reason, still free
  // the capability cache so the destructor never leaks.
  DisposeObjectAndNil(FCapabilities);

  inherited;
end;

{ ----------------------------------------------------------------------------
  Connection
  ---------------------------------------------------------------------------- }

procedure TLLMClient.CleanupPartialConnect(AExitMainThread: boolean);
begin
  // Release the App handle if one was created. This detaches the App
  // from the client and stops its sequenced notification threads. The
  // underlying TLF_App object remains in the global pool until
  // LF_Shutdown is called, which is the responsibility of the process
  // that owns the LingoFuse library.
  if FApp <> nil then
  begin
    try
      FApp.Free;
    except
      // Swallow exceptions so a destructor-time failure never masks
      // the original error that triggered the cleanup.
    end;
    FApp := nil;
  end;

  // Terminate the LingoFuse main thread if we started it and the caller
  // asked for it. AExitMainThread is False on early-failure paths where
  // PrepareDone was never reached, because the main thread is not
  // running in that case.
  if AExitMainThread and FPrepared then
  begin
    try
      LF.ExitMainThread;
    except
    end;
  end;

  // Release the cached API capability matrix, if any. The matrix is
  // tied to the connection lifetime: a new Connect will re-fetch it,
  // and a fresh server on the same endpoint may advertise a different
  // set of capabilities (for example, someone might stop llm_proxy.py
  // and start llm_service.py in its place).
  DisposeObjectAndNil(FCapabilities);
  FServerKind := '';

  FPrepared := False;
  FConnected := False;
  FClientName := '';
  FCurrentSessionId := '';
end;

function TLLMClient.FetchCapabilities(out AError: string): boolean;
var
  joReq, joResp, capsSrc: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  AError := '';

  // Reset any previous cache before attempting a fresh fetch. This
  // guarantees that a failed fetch leaves the client in a clean
  // "unknown" state rather than holding a stale matrix from a
  // different server kind.
  DisposeObjectAndNil(FCapabilities);
  FServerKind := '';

  // get_api_capabilities takes an empty JSON object as input.
  joReq := TZ_JsonObject.Create;
  try
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_GET_CAPABILITIES, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from get_api_capabilities';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'get_api_capabilities failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    // Extract the {api_name -> 0|1} sub-dictionary into an independent
    // object. joResp will be freed in the finally block; the cached
    // copy must outlive it.
    capsSrc := joResp.O['capabilities'];
    FCapabilities := TZ_JsonObject.Create;
    FCapabilities.Assign(capsSrc);

    FServerKind := joResp.S['server_kind'];
    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.Connect(out ErrorMsg: string): boolean;
begin
  Result := False;
  ErrorMsg := '';

  // Idempotent: a connected client just reports success.
  if FConnected then
  begin
    Result := True;
    Exit;
  end;

  // Defensive: if a previous Connect aborted halfway, clean it up before
  // starting a new attempt. This avoids leaving a stale App or a running
  // main thread behind.
  if FPrepared or (FApp <> nil) then
    CleanupPartialConnect(False);

  try
    // Step 1: Prepare network connection WITHOUT binding an App yet.
    // This establishes the LingoFuse client tunnel but leaves the App
    // slot empty, so we can create and register the App on the running
    // main thread in later steps.
    LF.ResetPrepare;

    // Wait_Connection_ReadyOk = True makes PrepareDone block until the
    // client is fully connected. Overlap_Connection = True allows us to
    // re-prepare clients on the same address after a Disconnect.
    LF.SetOption('Wait_Connection_ReadyOk', 'True');
    LF.SetOption('Overlap_Connection', 'True');

    if LF.PrepareClient(FEndpoint, nil) = -1 then
    begin
      ErrorMsg := 'LF.PrepareClient failed (address invalid or already in use)';
      CleanupPartialConnect(False);   // main thread not started yet
      Exit;
    end;

    if not LF.PrepareDone then
    begin
      ErrorMsg := 'LF.PrepareDone failed (network initialization error)';
      CleanupPartialConnect(False);   // main thread not started
      Exit;
    end;

    // From this point on, the main thread IS running. Any failure must
    // pass AExitMainThread = True so the thread is properly stopped.
    FPrepared := True;

    // Step 2: Generate a unique client name. The name is a concatenation
    // of C4 tunnel addresses, the process name (with PID), and a
    // high-resolution timestamp. It MUST be generated after PrepareDone
    // because the tunnel information is only available then.
    FClientName := LF.Generate_AppName;
    if FClientName = '' then
    begin
      ErrorMsg := 'LF.Generate_AppName returned an empty string';
      CleanupPartialConnect(True);
      Exit;
    end;

    // Step 3: Create the App and register the notify callback on the
    // 'llm_stream' API. RegisterNotifySync queues the callback to the
    // main thread, so OnLLMStream runs safely alongside the UI.
    FApp := LF.TAppHandle.Create(FClientName, 'Dynamic LLM Client (v3.3)');
    if not FApp.RegisterNotifySync(API_NAME_STREAM, 'LLM stream callback',
      OnLLMStream) then
    begin
      ErrorMsg := 'Failed to register notify callback for "' + API_NAME_STREAM + '"';
      CleanupPartialConnect(True);
      Exit;
    end;

    // Step 4: Bind the App to the client tunnel created in step 1.
    // A return value of 0 means no free client was available (for
    // example, another App is already attached to the only tunnel).
    if FApp.Bind = 0 then
    begin
      ErrorMsg := 'LF_BindApp returned 0 - no free client available';
      CleanupPartialConnect(True);
      Exit;
    end;

    FConnected := True;

    // Step 5: Best-effort fetch of the API capability matrix. This is
    // optional: if the server is an older version that does not expose
    // get_api_capabilities, the fetch fails and we simply leave the
    // cache empty. HasCapabilityInfo then returns False and
    // LLMSupported returns False for every name; callers that gate on
    // HasCapabilityInfo fall back to unconditional invocation.

    // The fetch is performed AFTER FConnected is set, so CallAPI can
    // run its normal guards. Failure is swallowed: a server that does
    // not implement the capability API must not prevent the client
    // from connecting.
    FetchCapabilities(ErrorMsg);   // discard diagnostic; treated as advisory

    Result := True;
  except
    on E: Exception do
    begin
      ErrorMsg := 'Unexpected exception in Connect: ' + E.Message;
      // Use FPrepared as the AExitMainThread flag: if PrepareDone
      // succeeded before the exception, the main thread needs stopping.
      CleanupPartialConnect(FPrepared);
      FConnected := False;
      Result := False;
    end;
  end;
end;

procedure TLLMClient.Disconnect;
begin
  // Do not early-exit on FConnected: after a partial Connect, FConnected
  // may be False while FPrepared is True and FApp is non-nil. In that
  // case we still need to release the App and stop the main thread.
  if not (FPrepared or FConnected or (FApp <> nil)) then
    Exit;
  CleanupPartialConnect(True);
end;

{ ----------------------------------------------------------------------------
  Notify handler (structured v3.0 protocol)
  ---------------------------------------------------------------------------- }

procedure TLLMClient.OnLLMStream(Input_: TDataHnd___);
var
  jstr: TZ_JsonString;
  jo: TZ_JsonObject;
  buf: Pointer;
  sz: int64;
  msgType, SessionId, Text, Reason, msg: string;
begin
  if Input_ = nil then
    Exit;

  // Access the raw bytes of the incoming notification. The buffer might
  // be nil or empty in edge cases; guard against both.
  buf := LF___.LF_GetBuffer(Input_);
  sz := LF___.LF_GetSize(Input_);
  if (buf = nil) or (sz <= 0) then
    Exit;

  // Decode the UTF-8 JSON string. ReadUTF8AnsiChar is tolerant of both
  // NUL-terminated and non-NUL-terminated payloads, so we do not need
  // to know whether the sender appended a terminator.
  jstr.ReadUTF8AnsiChar(buf, sz);
  if jstr.Text = '' then
    Exit;

  jo := TZ_JsonObject.Create;
  try
    if not jo.ParseText(jstr) then
      Exit;

    msgType := jo.S['type'];
    SessionId := jo.S['session_id'];

    // "closed" may arrive for any session we own; dispatch it as-is so
    // the UI can react (e.g., clear its active session pointer).
    if msgType = 'closed' then
    begin
      Reason := jo.S['reason'];
      DoClosed(SessionId, Reason);
      Exit;
    end;

    // Everything else is addressed to a specific session. The dispatch
    // table mirrors the protocol spec in the unit header.
    if msgType = 'chunk' then
    begin
      Text := jo.S['text'];
      if Text <> '' then
        DoChunk(SessionId, Text);
    end
    else if msgType = 'think' then
    begin
      Text := jo.S['text'];
      if Text <> '' then
        DoThink(SessionId, Text);
    end
    else if msgType = 'finish' then
    begin
      Reason := jo.S['reason'];
      DoFinish(SessionId, Reason);
    end
    else if msgType = 'error' then
    begin
      msg := jo.S['message'];
      DoError(SessionId, msg);
    end;
    // Unknown message types are silently ignored for forward compatibility.
  finally
    jo.Free;
  end;
end;

procedure TLLMClient.DoChunk(const SessionId, Text: string);
begin
  if Assigned(FOnChunk) then FOnChunk(SessionId, Text);
end;

procedure TLLMClient.DoThink(const SessionId, Text: string);
begin
  if Assigned(FOnThink) then FOnThink(SessionId, Text);
end;

procedure TLLMClient.DoFinish(const SessionId, Reason: string);
begin
  if Assigned(FOnFinish) then FOnFinish(SessionId, Reason);
end;

procedure TLLMClient.DoError(const SessionId, ErrorMsg: string);
begin
  if Assigned(FOnError) then FOnError(SessionId, ErrorMsg);
end;

procedure TLLMClient.DoClosed(const SessionId, Reason: string);
begin
  if Assigned(FOnClosed) then FOnClosed(SessionId, Reason);
end;

{ ----------------------------------------------------------------------------
  Session management
  ---------------------------------------------------------------------------- }

function TLLMClient.CreateSession(out ASessionId, AError: string): boolean;
begin
  // Delegate to the system_message overload with an empty message.
  // Note: on llm_service.py, an empty message means "use the server's
  // global default". On llm_proxy.py, an empty message means "no system
  // message"; the backend's chat template decides. See the unit header.
  Result := CreateSession('', ASessionId, AError);
end;

function TLLMClient.CreateSession(const ASystemMessage: string; out ASessionId, AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  ASessionId := '';
  AError := '';

  joReq := TZ_JsonObject.Create;
  try
    joReq.S['client_name'] := FClientName;
    if ASystemMessage <> '' then
      joReq.S['system_message'] := ASystemMessage;
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_CREATE_SESSION, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from create_session';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'create_session failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    ASessionId := joResp.S['session_id'];
    if ASessionId = '' then
    begin
      AError := 'Server did not return session_id';
      Exit;
    end;

    FCurrentSessionId := ASessionId;
    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.CloseSession(const ASessionId: string; ACancelRunning: boolean;
  out AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  AError := '';

  if ASessionId = '' then
  begin
    AError := 'CloseSession: empty session_id';
    Exit;
  end;

  joReq := TZ_JsonObject.Create;
  try
    joReq.S['session_id'] := ASessionId;
    joReq.B['cancel_running'] := ACancelRunning;
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_CLOSE_SESSION, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from close_session';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'close_session failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    // Clear the current-session pointer if it was the one being closed.
    if FCurrentSessionId = ASessionId then
      FCurrentSessionId := '';
    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.CancelSession(const ASessionId: string; out AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  AError := '';

  if ASessionId = '' then
  begin
    AError := 'CancelSession: empty session_id';
    Exit;
  end;

  joReq := TZ_JsonObject.Create;
  try
    joReq.S['session_id'] := ASessionId;
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_CANCEL_SESSION, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from cancel_session';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'cancel_session failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.ListSessions(out ASessionsJson, AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  ASessionsJson := '';
  AError := '';

  joReq := TZ_JsonObject.Create;
  try
    // Restrict to sessions belonging to this client.
    joReq.S['client_name'] := FClientName;
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_LIST_SESSIONS, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from list_sessions';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'list_sessions failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    // Convert the JSON back to a UTF-8 string for the caller. This is the
    // only place where string-level access is unavoidable: the caller needs
    // a string to parse or display. For non-ASCII content, the caller
    // should treat the bytes as UTF-8.
    ASessionsJson := TEncoding.UTF8.GetString(respBytes);
    Result := True;
  finally
    joResp.Free;
  end;
end;

{ ----------------------------------------------------------------------------
  Generate
  ---------------------------------------------------------------------------- }

function TLLMClient.Generate(const AContent, APrompt: string; var ASessionId: string;
  out AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
  newSessionId: string;
begin
  Result := False;
  AError := '';

  if not FConnected then
  begin
    AError := 'Not connected to LingoFuse service';
    Exit;
  end;

  // ---- Build request ----
  joReq := TZ_JsonObject.Create;
  try
    joReq.S['content'] := AContent;
    joReq.S['prompt'] := APrompt;

    if ASessionId <> '' then
      // Continue the explicitly provided session.
      joReq.S['session_id'] := ASessionId
    else if FCurrentSessionId <> '' then
      // Fall back to the client's current session.
      joReq.S['session_id'] := FCurrentSessionId
    else
      // New session. client_name is required.
      joReq.S['client_name'] := FClientName;

    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  // ---- Call ----
  if not CallAPI(API_NAME_GENERATE, reqBytes, respBytes, AError) then
    Exit;

  // ---- Parse response: {code, session_id, task_id, mode} ----
  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from generate';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'generate failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    newSessionId := joResp.S['session_id'];
    if newSessionId = '' then
    begin
      AError := 'Server did not return session_id';
      Exit;
    end;

    // Write back the effective session ID to both the caller (via var)
    // and the client's internal current-session pointer.
    ASessionId := newSessionId;
    FCurrentSessionId := newSessionId;
    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.GenerateCurrent(const AContent, APrompt: string; out AError: string): boolean;
var
  sid: string;
begin
  sid := FCurrentSessionId;
  Result := Generate(AContent, APrompt, sid, AError);
end;

{ ----------------------------------------------------------------------------
  SetSystemMessage
  ---------------------------------------------------------------------------- }

function TLLMClient.SetSystemMessage(const AMessage: string; out AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
  kind: string;
begin
  Result := False;
  AError := '';

  // If we have already fetched the capability matrix (which Connect
  // does automatically), consult it before making a network round-trip.
  // When the server has explicitly advertised that set_system_message
  // is unsupported (which happens for llm_proxy.py), short-circuit with
  // a friendly error message that tells the caller what to do instead.

  // When the matrix is not available (older server, or the fetch failed
  // during Connect), we skip the check and attempt the call as before.
  // This preserves backward compatibility: an old llm_service.py will
  // simply succeed, and an old server that does not support the API
  // will report its own error, which we pass through unchanged.
  if HasCapabilityInfo and (not LLMSupported(API_NAME_SET_SYSTEM_MESSAGE)) then
  begin
    kind := FServerKind;
    if kind = '' then
      kind := 'unknown';

    AError :=
      'set_system_message is not supported by this server (kind=' + kind + '). ' +
      'The system message is fixed at session creation time. ' + 'To use a custom system message, pass it to CreateSession, ' +
      'or close the current session and create a new one with the ' + 'desired system message.';
    Exit;
  end;

  joReq := TZ_JsonObject.Create;
  try
    joReq.S['content'] := AMessage;
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_SET_SYSTEM_MESSAGE, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from set_system_message';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      // This branch is also taken when the server is llm_proxy.py but
      // the capability matrix was not available at check time (for
      // example, an older proxy that predates get_api_capabilities).
      // The server returns
      //     {"code": -1, "status": "unsupported", "error": "..."}
      // and we pass its error string back to the caller verbatim.
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'set_system_message failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    Result := True;
  finally
    joResp.Free;
  end;
end;

{ ----------------------------------------------------------------------------
  Health
  ---------------------------------------------------------------------------- }

function TLLMClient.Health(out AHealthJson, AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
begin
  Result := False;
  AHealthJson := '';
  AError := '';

  // health() takes an empty JSON object as input.
  joReq := TZ_JsonObject.Create;
  try
    reqBytes := joReq.ToBytes;
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_HEALTH, reqBytes, respBytes, AError) then
    Exit;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from health';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'health failed (code ' + IntToStr(code) + ')';
      Exit;
    end;

    AHealthJson := TEncoding.UTF8.GetString(respBytes);
    Result := True;
  finally
    joResp.Free;
  end;
end;

{ ----------------------------------------------------------------------------
  Capability discovery
  ---------------------------------------------------------------------------- }

function TLLMClient.GetAPICapabilities(out ACapabilitiesJson, AError: string): boolean;
var
  joReq, joResp: TZ_JsonObject;
  reqBytes, respBytes: TBytes;
  code: integer;
  capsSrc: TZ_JsonObject;
begin
  Result := False;
  ACapabilitiesJson := '';
  AError := '';

  // The caller may invoke this either on a fresh connection (in which
  // case Connect already fetched the matrix; the call here simply
  // refreshes it) or after a server swap (stop llm_proxy.py, start
  // llm_service.py, or vice versa). Either way, the fetch below
  // replaces the cached matrix.
  joReq := TZ_JsonObject.Create;
  try
    reqBytes := joReq.ToBytes;   // empty {}
  finally
    joReq.Free;
  end;

  if not CallAPI(API_NAME_GET_CAPABILITIES, reqBytes, respBytes, AError) then
  begin
    // Transport failure. Reset the cache so the client does not keep
    // reporting a stale matrix from a previous server.
    DisposeObjectAndNil(FCapabilities);
    FServerKind := '';
    Exit;
  end;

  joResp := TZ_JsonObject.Create;
  try
    if not joResp.Parae(respBytes) then
    begin
      AError := 'Invalid JSON response from get_api_capabilities';
      DisposeObjectAndNil(FCapabilities);
      FServerKind := '';
      Exit;
    end;

    code := joResp.I['code'];
    if code <> 0 then
    begin
      if joResp.Exists('error') then
        AError := joResp.S['error']
      else
        AError := 'get_api_capabilities failed (code ' + IntToStr(code) + ')';
      DisposeObjectAndNil(FCapabilities);
      FServerKind := '';
      Exit;
    end;

    // Populate the internal cache. The cached object holds only the
    // capabilities sub-dictionary; the outer envelope is discarded.
    DisposeObjectAndNil(FCapabilities);
    capsSrc := joResp.O['capabilities'];
    FCapabilities := TZ_JsonObject.Create;
    FCapabilities.Assign(capsSrc);

    FServerKind := joResp.S['server_kind'];

    // Hand the raw JSON back to the caller as a UTF-8 string. The
    // caller can parse or display it however it likes.
    ACapabilitiesJson := TEncoding.UTF8.GetString(respBytes);
    Result := True;
  finally
    joResp.Free;
  end;
end;

function TLLMClient.HasCapabilityInfo: boolean;
begin
  // The cache is populated only on a fully successful fetch: a valid
  // JSON response, code 0, and a "capabilities" sub-dictionary. A nil
  // FCapabilities therefore means "we do not know" rather than "the
  // server supports nothing".
  Result := FCapabilities <> nil;
end;

function TLLMClient.LLMSupported(const AAPIName: string): boolean;
begin
  // Without a fetched matrix, we cannot answer authoritatively. Return
  // False and let the caller decide, via HasCapabilityInfo, whether
  // that should be interpreted as "unsupported" or "unknown".
  if FCapabilities = nil then
  begin
    Result := False;
    Exit;
  end;

  // The capability matrix stores integers: 1 = supported, 0 = not.
  // A missing entry is treated as unsupported, matching the server-side
  // convention where only value 1 means "supported". This is the
  // conservative choice: never assume support that the server did not
  // explicitly advertise.
  if FCapabilities.Exists(AAPIName) then
    Result := FCapabilities.I[AAPIName] = 1
  else
    Result := False;
end;

end.
