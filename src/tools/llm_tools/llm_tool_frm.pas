(*
 * ============================================================================
 * llm_tool_frm — LingoFuse LLM 客户端测试工具（主窗体）
 * ============================================================================
 *
 * 本窗体是一个用于测试 LingoFuse LLM 服务的图形界面客户端，扮演
 * llm_client.pas（TLLMClient）的 UI 层。它提供以下功能：
 *
 *   - 连接 / 断开 LingoFuse LLM 服务（ipc:llm_service 或 TCP 端点）
 *   - 创建新会话（携带用户自定义的 system message），并立即发起第一次生成
 *   - 发送 generate 请求，实时显示流式输出
 *   - 显示服务端错误、会话结束、会话关闭等生命周期事件
 *   - 通过 get_api_capabilities 自动发现服务端 API 能力，对不支持的
 *     功能提前短路，避免无谓的 RPC 往返
 *
 * 数据流概览
 * ----------
 *
 *   用户点击"发送 generate 请求"
 *       ↓
 *   test_generate_ButtonClick
 *       ├─ 读取 code_Edit（正文输入）
 *       ├─ 读取 prompt_edit（附加提示）
 *       ├─ 调用 LLM.Generate(..., sid, err)
 *       └─ 立即返回 task_id，不等待生成完成
 *
 *   服务端推送 chunk
 *       ↓
 *   llm_client.OnLLMStream（由 LingoFuse 主线程调用）
 *       ├─ 解析 JSON 消息类型（chunk / think / finish / error / closed）
 *       ├─ 通过事件转发到 Do_LLM_Chunk / Do_LLM_Think / Do_LLM_Finish / ...
 *       └─ 各事件处理器直接操作 UI 控件
 *          （因为使用 RegisterNotifySync，回调在主线程执行，可安全操作 VCL/LCL）
 *
 *   sysTimer（周期触发）
 *       ↓
 *   驱动 LingoFuse 的软同步队列，并轮询其内部状态日志
 *
 * 线程模型
 * --------
 * - TLLMClient 注册的是 RegisterNotifySync 回调，因此所有 Do_LLM_*
 *   事件处理器都在主线程执行，可以安全地操作 VCL/LCL 控件。
 * - 连接过程（Do_Thread_Connect）放在后台线程执行，避免界面冻结；
 *   完成后用 TCompute.SyncM 切回主线程更新 UI。
 *
 * 关于"更新系统消息"按钮与连接时的可选同步
 * ----------------------------------------
 * LingoFuse LLM Service 有两种后端：
 *   - llm_service.py：本地推理服务，语义上支持"修改全局默认 system
 *     message，仅影响之后新建的会话"。
 *   - llm_proxy.py  ：无状态转发器，不支持运行时修改，会明确返回
 *     {"code": -1, "status": "unsupported", "error": "..."}。
 *
 * 为兼容两种服务端，本工具在调用 set_system_message 之前会先通过
 * LLM.HasCapabilityInfo / LLM.LLMSupported 检查能力矩阵：
 *   - 明确不支持：跳过调用，直接给出中文提示；
 *   - 信息未知（旧服务端）：保持原样尝试调用，向后兼容；
 *   - 明确支持：正常调用。
 *
 * 因此"更新系统消息"按钮在 llm_proxy.py 下不会发出无谓的 RPC，
 * 只显示友好提示，引导用户改用"新建会话"按钮让新的 system message
 * 生效。
 *
 * ============================================================================
 *)

unit llm_tool_frm;

{$DEFINE FPC_DELPHI_MODE}
{$I ..\..\..\zNetV2\source\Z.Define.inc}

interface

uses
  Classes, SysUtils, Forms, Controls, Graphics, Dialogs, StdCtrls, ExtCtrls, ComCtrls,
  SynEdit, SynEditMiscClasses, SynHighlighterAny,
  llm_client, lingofuse_import, lingofuse_helper,
  Z.Core, Z.PascalStrings, Z.UPascalStrings, Z.Json, Z.UnicodeMixedLib, Z.Status;

type

  { Tllm_tool_form — 主窗体 }
  Tllm_tool_form = class(TForm)
    BottomPanel: TPanel;
    BottomSplitter: TSplitter;
    Update_Sys_Prompt_Button: TButton;                    // "更新系统消息"按钮
    conn_llm_Button: TButton;            // "连接"按钮
    Label1: TLabel;
    Label2: TLabel;
    Label3: TLabel;
    Label4: TLabel;
    llm_APP_Edit: TLabeledEdit;          // 服务端 App 名称输入框
    LLM_Service_Edit: TLabeledEdit;      // LingoFuse 端点输入框
    LogMemo: TMemo;                      // 底部日志区
    MainPageControl: TPageControl;       // 主 Tab 容器
    LLM_Opt_TabSheet: TTabSheet;
    Input_TabSheet: TTabSheet;           // 输入页
    Output_TabSheet: TTabSheet;          // 输出页
    Panel1: TPanel;
    Panel2: TPanel;
    Panel3: TPanel;
    Splitter1: TSplitter;
    SynAnySyn1: TSynAnySyn;
    sys_prompt_Memo: TMemo;              // 系统提示词输入框
    code_Edit: TSynEdit;                 // 正文输入框（支持语法高亮）
    test_generate_Button: TButton;       // "发送 generate 请求"按钮
    prompt_edit: TMemo;                  // 附加提示输入框
    sse_Edit: TSynEdit;                  // 流式输出显示区
    sysTimer: TTimer;                    // 主线程定时器，驱动 LF 同步
    new_session_Button: TButton;         // "新建会话"按钮

    procedure Update_Sys_Prompt_ButtonClick(Sender: TObject);
    procedure conn_llm_ButtonClick(Sender: TObject);
    procedure FormClose(Sender: TObject; var CloseAction: TCloseAction);
    procedure new_session_ButtonClick(Sender: TObject);
    procedure sysTimerTimer(Sender: TObject);
    procedure test_generate_ButtonClick(Sender: TObject);
  private
    { 当前在输出页显示的会话 ID。
      流式回调只处理 session_id 等于此值的消息，
      其他会话的消息会被静默忽略。空字符串表示"尚未选定会话"。 }
    FActiveSessionId: string;

    { --- 流式事件处理器（全部在 LingoFuse 主线程执行） --- }
    procedure Backcall_DoStatus(Text_: SystemString; const ID: integer);
    procedure Do_LLM_Chunk(const SessionId, Chunk: string);
    procedure Do_LLM_Think(const SessionId, Text: string);
    procedure Do_LLM_Error(const SessionId, ErrorMsg: string);
    procedure Do_LLM_Finish(const SessionId, Reason: string);
    procedure Do_LLM_Closed(const SessionId, Reason: string);

    { --- 输出辅助 --- }
    procedure AppendChunkToOutput(const Text: string);
    procedure ResetOutputHeader(const SessionId: string);

    { --- 连接工作线程 --- }
    procedure Do_Thread_Connect_Done;
    procedure Do_Thread_Connect;
  public
    constructor Create(AOwner: TComponent); override;
    destructor Destroy; override;
    procedure Enabled_All;
    procedure Disable_All;
  end;

var
  llm_tool_form: Tllm_tool_form;
  { 全局唯一的 LLM 客户端对象。
    连接成功后非 nil；断开后重新置为 nil。 }
  LLM: TLLMClient;

implementation

{$R *.lfm}

{ ----------------------------------------------------------------------------
  输出辅助过程
  ---------------------------------------------------------------------------- }

(*
 * AppendChunkToOutput — 把一段文本追加到输出区 sse_Edit 的末尾。
 *
 * 输入：
 *   Text  服务端推送的一段文本（可能包含 \r\n 或 \n 换行符）。
 *
 * 行为：
 *   1. 如果输出区是空的，先添加一行空行，确保始终有"当前行"可写。
 *   2. 归一化换行符：去除所有 \r，只保留 \n 作为换行依据。
 *   3. 查找 \n：
 *      - 找到：把 \n 之前的部分追加到当前行，然后新开一行，
 *              递归处理剩余部分。
 *      - 未找到：把剩余部分追加到当前行；
 *              如果当前行长度超过 80，自动换行（改善可读性）。
 *
 * 注意事项：
 *   - 本过程是递归实现。若某段 chunk 含大量换行符，递归深度会随之
 *     增加。实际业务中服务端每个 chunk 通常不超过几十字符，不会触发
 *     栈溢出。若未来要处理超长文本，可改为迭代实现。
 *   - 只操作 VCL/LCL 控件，必须在主线程调用。流式回调因为使用
 *     RegisterNotifySync，天然满足此要求。
 *)
procedure Tllm_tool_form.AppendChunkToOutput(const Text: string);
var
  s, First, rest: string;
  p: integer;
begin
  // 1) 保证输出区至少有一行可写
  if sse_Edit.Lines.Count <= 0 then
    sse_Edit.Lines.Add('');

  // 2) 归一化换行：去除所有 \r，只保留 \n
  s := StringReplace(Text, #13, '', [rfReplaceAll]);
  if s = '' then
    Exit;

  // 3) 按 \n 分段处理
  p := Pos(#10, s);
  if p > 0 then
  begin
    First := Copy(s, 1, p - 1);
    rest := Copy(s, p + 1, MaxInt);

    // 追加 \n 之前的部分到当前行，然后新开一行
    sse_Edit.Lines[sse_Edit.Lines.Count - 1] :=
      sse_Edit.Lines[sse_Edit.Lines.Count - 1] + First;
    sse_Edit.Lines.Add('');

    // 递归处理剩余部分
    if rest <> '' then
      AppendChunkToOutput(rest);
  end
  else
  begin
    // 没有换行：全部追加到当前行
    sse_Edit.Lines[sse_Edit.Lines.Count - 1] :=
      sse_Edit.Lines[sse_Edit.Lines.Count - 1] + s;

    // 自动换行：单行超过 80 字符时新开一行（纯 UI 优化）
    if length(sse_Edit.Lines[sse_Edit.Lines.Count - 1]) > 80 then
      sse_Edit.Lines.Add('');
  end;
end;

(*
 * ResetOutputHeader — 清空输出区并写入新会话的头部信息。
 *
 * 用途：在开始新一轮会话输出前，重置显示状态，避免上一次会话的
 * 内容残留造成混淆。
 *
 * 参数：
 *   SessionId  新会话的 session_id，会作为头部一行显示。
 *
 * 后置条件：
 *   - 输出区被清空
 *   - 第一行是 "[session <id>]"
 *   - 第二行是空行，便于正文从第三行开始
 *   - 输出区暂时设为可写（调用方通常随后设为只读）
 *)
procedure Tllm_tool_form.ResetOutputHeader(const SessionId: string);
begin
  sse_Edit.Clear;
  sse_Edit.Lines.Add('[session ' + SessionId + ']');
  sse_Edit.Lines.Add('');
  sse_Edit.ReadOnly := False;
end;

{ ----------------------------------------------------------------------------
  流式事件处理器
  ----------------------------------------------------------------------------
  以下五个 Do_LLM_* 过程由 TLLMClient 通过事件回调调用。因为使用了
  RegisterNotifySync 注册回调，它们都在 LingoFuse 主线程执行，可以
  直接操作 UI 控件。

  每个处理器都会先检查 SessionId 是否等于 FActiveSessionId：
  - FActiveSessionId 为空：接受所有会话的消息（尚未选定会话时的兜底）；
  - SessionId 与 FActiveSessionId 相同：正常处理；
  - 其他：忽略（避免多个会话的输出互相干扰）。
  ---------------------------------------------------------------------------- }

(*
 * Do_LLM_Chunk — 处理服务端推送的正文内容块。
 *
 * 触发时机：服务端推 {"type":"chunk", "session_id":"...", "text":"..."}。
 *
 * 流程：
 *   1. 校验 SessionId 是否属于当前显示的会话，不是则忽略。
 *   2. 把正文内容追加到输出区。
 *)
procedure Tllm_tool_form.Do_LLM_Chunk(const SessionId, Chunk: string);
begin
  // 会话过滤
  if (FActiveSessionId <> '') and (SessionId <> FActiveSessionId) then
    Exit;

  // 追加正文内容
  AppendChunkToOutput(Chunk);
end;

(*
 * Do_LLM_Think — 处理服务端推送的思考链内容块。
 *
 * 触发时机：服务端推 {"type":"think", "session_id":"...", "text":"..."}。
 * 只有 Reasoning 模型（如 Nemotron、DeepSeek-R1）会产生这类消息。
 *
 * 流程：
 *   1. 校验会话。
 *   2. 追加思考内容。
 *)
procedure Tllm_tool_form.Do_LLM_Think(const SessionId, Text: string);
begin
  if (FActiveSessionId <> '') and (SessionId <> FActiveSessionId) then
    Exit;

  AppendChunkToOutput(Text);
end;

(*
 * Do_LLM_Error — 处理服务端推送的错误事件。
 *
 * 触发时机：服务端推 {"type":"error", "session_id":"...", "message":"..."}。
 * 常见原因：后端 HTTP 错误、上下文超限、会话不存在等。
 *
 * 处理：
 *   1. 在输出区显示 [ERROR] 前缀和错误消息。
 *   2. 把输出区设为可写，方便用户复制错误信息。
 *)
procedure Tllm_tool_form.Do_LLM_Error(const SessionId, ErrorMsg: string);
begin
  if (FActiveSessionId <> '') and (SessionId <> FActiveSessionId) then
    Exit;

  AppendChunkToOutput(sLineBreak + '[ERROR] ' + ErrorMsg + sLineBreak);
  sse_Edit.ReadOnly := False;
end;

(*
 * Do_LLM_Finish — 处理服务端推送的"生成完成"事件。
 *
 * 触发时机：服务端推 {"type":"finish", "session_id":"...", "reason":"..."}。
 * reason 取值：
 *   - "stop"      正常完成
 *   - "error"     因错误结束
 *   - "cancelled" 被客户端取消
 *
 * 处理：在输出区末尾加一行分隔，标明 reason。
 *)
procedure Tllm_tool_form.Do_LLM_Finish(const SessionId, Reason: string);
begin
  if (FActiveSessionId <> '') and (SessionId <> FActiveSessionId) then
    Exit;

  sse_Edit.Lines.Add('');
  sse_Edit.Lines.Add('--- 会话结束 (reason=' + Reason + ') ---');
  sse_Edit.ReadOnly := False;
end;

(*
 * Do_LLM_Closed — 处理服务端推送的"会话已关闭"事件。
 *
 * 触发时机：服务端推 {"type":"closed", "session_id":"...", "reason":"..."}。
 * reason 取值：
 *   - "client"    客户端主动关闭
 *   - "timeout"   服务端空闲超时
 *   - "shutdown"  服务端关机
 *
 * 处理：
 *   - 如果关闭的会话是当前显示的会话，清空 FActiveSessionId，
 *     以便用户可以直接点击"新建会话"重新开始。
 *   - 在输出区显示关闭原因。
 *)
procedure Tllm_tool_form.Do_LLM_Closed(const SessionId, Reason: string);
begin
  // 只处理当前显示的会话，其他会话的关闭事件被忽略
  if SessionId <> FActiveSessionId then
    Exit;

  FActiveSessionId := '';
  sse_Edit.Lines.Add('');
  sse_Edit.Lines.Add('--- 会话被关闭 (reason=' + Reason + ') ---');
  sse_Edit.ReadOnly := False;
end;

{ ----------------------------------------------------------------------------
  按钮事件处理器
  ---------------------------------------------------------------------------- }

(*
 * Button1Click — "更新系统消息"按钮。
 *
 * 用途：把 sys_prompt_Memo 里的内容推送给服务端，期望修改默认
 * system message。**此操作对已经存在的会话不生效**，只影响之后
 * 通过 Generate(无 session_id) 创建的新会话。
 *
 * API 能力检查：
 *   在发出 RPC 之前，先查询服务端能力矩阵：
 *     - 明确不支持（例如 llm_proxy.py）：直接短路，给出中文提示，
 *       不发出无谓的请求；
 *     - 信息未知（旧服务端）：保持原样尝试调用，向后兼容；
 *     - 明确支持（例如 llm_service.py）：正常调用。
 *
 * 无论成功或失败，本过程都不会中断 UI。
 *)
procedure Tllm_tool_form.Update_Sys_Prompt_ButtonClick(Sender: TObject);
var
  err: string;
  n: TP_String;
begin
  if LLM = nil then Exit;

  // ---- 前置 API 能力检查 ----
  // 只有在"能力信息已获取"且"明确声明不支持"时才短路；
  // 能力信息未知的情况下保持原样，向后兼容旧服务端。
  if LLM.HasCapabilityInfo and (not LLM.LLMSupported(API_NAME_SET_SYSTEM_MESSAGE)) then
  begin
    DoStatus('当前服务端类型为 "' + LLM.ServerKind + '"，不支持 set_system_message，已跳过。');
    DoStatus('提示：点击"新建会话"按钮可以让新的系统提示词生效。');
    Exit;
  end;

  // 读取系统提示词输入框内容并去除首尾空白
  n := sys_prompt_Memo.Lines.Text;
  n := n.TrimChar(#13#10#32#9);

  // 调用服务端的 set_system_message API
  if not LLM.SetSystemMessage(n, err) then
  begin
    // 失败（例如旧服务端未实现能力矩阵，且确实不支持）
    DoStatus('更新系统消息失败: ' + err);
    DoStatus('提示：点击"新建会话"按钮可以让新的系统提示词生效。');
    Exit;
  end;

  // 成功（通常只在 llm_service.py 下）
  DoStatus('已更新系统消息（仅对之后新建的会话生效）');
end;

(*
 * conn_llm_ButtonClick — "连接"按钮。
 *
 * 流程：
 *   1. 如果已经连接，忽略点击。
 *   2. 禁用所有控件（避免用户在连接过程中重复操作）。
 *   3. 在后台线程执行 Do_Thread_Connect（真正的连接工作）。
 *
 * 连接完成（无论成功失败）会通过 TCompute.SyncM 回到主线程，
 * 由 Do_Thread_Connect_Done 恢复 UI 状态。
 *)
procedure Tllm_tool_form.conn_llm_ButtonClick(Sender: TObject);
begin
  if LLM <> nil then Exit;

  Disable_All;
  TCompute.RunM_NP(Do_Thread_Connect);
end;

(*
 * new_session_ButtonClick — "新建会话"按钮。
 *
 * 用途：
 *   1. 显式创建一个新会话，并把 sys_prompt_Memo 里的内容作为该会话
 *      的 system message 固化到服务端。
 *   2. 建完后立即用 code_Edit / prompt_edit 里的内容发起一次生成，
 *      让用户"一次点击完成创建会话 + 首发提问"。
 *
 * 流程：
 *   1. 前置检查：必须已经连接（LLM <> nil）。
 *   2. 读取 sys_prompt_Memo 内容，去除首尾空白，作为新会话的
 *      system message。
 *   3. 调用 LLM.CreateSession(system_msg, sid, err)：
 *      - 成功：服务端返回一个全新的 session_id，赋值给 sid。
 *      - 失败：err 中包含失败原因，直接提示用户并返回。
 *   4. 成功时更新 UI：
 *      - FActiveSessionId := sid（后续流式回调只处理该会话的消息）
 *      - 切换到"输出"页
 *      - 清空输出区，写入新会话的头部信息
 *      - 输出区设为只读（防止用户在流式过程中直接编辑）
 *   5. 立即调用 LLM.Generate，用输入框里的内容发起第一次生成。
 *      成功时同步更新 FActiveSessionId 和输出区头部。
 *
 * 与"更新系统消息"按钮的区别：
 *   - 本按钮创建新会话，system message 立即对新会话生效。
 *   - "更新系统消息"按钮修改的是服务端的全局默认值，只影响之后
 *     隐式创建的新会话；在 llm_proxy.py 下会短路。
 *
 * 设计意图：本按钮是推荐的自定义 system message + 首发的入口。
 *)
procedure Tllm_tool_form.new_session_ButtonClick(Sender: TObject);
var
  sid, err: string;
  sys_msg: TP_String;
begin
  // 1) 前置检查：必须先连接
  if LLM = nil then
  begin
    DoStatus('尚未连接 LLM 服务，请先点击"连接"按钮。');
    Exit;
  end;

  // 2) 读取系统提示词并归一化
  sys_msg := sys_prompt_Memo.Lines.Text;
  sys_msg := sys_msg.TrimChar(#13#10#32#9);

  // 3) 请求服务端创建新会话
  if not LLM.CreateSession(sys_msg, sid, err) then
  begin
    DoStatus('创建新会话失败: ' + err);
    Exit;
  end;

  // 4) 更新 UI 状态
  FActiveSessionId := sid;    // 后续回调只处理该会话的消息

  // 切换到输出页并重置显示
  MainPageControl.ActivePage := Output_TabSheet;
  ResetOutputHeader(sid);
  sse_Edit.ReadOnly := True;

  // 5) 日志
  DoStatus('已创建新会话: ' + sid);
  if sys_msg <> '' then
    DoStatus('系统提示词长度: ' + umlIntToStr(sys_msg.L) + ' 字符');

  // 6) 立即用 code_Edit / prompt_edit 里的内容发起第一次生成。
  //    若 code_Edit 为空，服务端会返回错误，日志中会体现。
  sid := FActiveSessionId;

  if LLM.Generate(code_Edit.Text, prompt_edit.Lines.Text, sid, err) then
  begin
    FActiveSessionId := sid;
    MainPageControl.ActivePage := Output_TabSheet;
    ResetOutputHeader(sid);
    sse_Edit.ReadOnly := True;
  end
  else
    DoStatus(err);
end;

(*
 * test_generate_ButtonClick — "发送 generate 请求"按钮。
 *
 * 用途：把 code_Edit 的正文和 prompt_edit 的附加提示发送给服务端，
 * 触发一次生成。服务端会立即返回一个 task_id；实际的流式输出
 * 通过 llm_stream Notify 回调异步推送。
 *
 * 流程：
 *   1. 前置检查：必须已经连接。
 *   2. 读取当前会话 ID（FActiveSessionId）。
 *      - 非空：继续该会话。
 *      - 空：由 LLM 内部决定（FCurrentSessionId 非空则继续，
 *             否则在服务端创建新会话）。
 *   3. 调用 LLM.Generate。成功后 sid 被写回为实际生效的会话 ID。
 *   4. 更新 UI 状态：
 *      - FActiveSessionId := sid
 *      - 切换到输出页
 *      - 重置输出头
 *      - 输出区设为只读（流式回调即将开始写入）
 *   5. 失败时通过 DoStatus 输出错误。
 *)
procedure Tllm_tool_form.test_generate_ButtonClick(Sender: TObject);
var
  sid, err: string;
begin
  if LLM = nil then Exit;

  // 使用当前会话；若为空，LLM 内部会按"当前会话 → 新建"策略处理
  sid := FActiveSessionId;

  if LLM.Generate(code_Edit.Text, prompt_edit.Lines.Text, sid, err) then
  begin
    FActiveSessionId := sid;
    MainPageControl.ActivePage := Output_TabSheet;
    ResetOutputHeader(sid);
    sse_Edit.ReadOnly := True;
  end
  else
    DoStatus(err);
end;

{ ----------------------------------------------------------------------------
  sysTimer — 主线程定时器
  ---------------------------------------------------------------------------- }

(*
 * sysTimerTimer — 定时器事件。
 *
 * 触发频率：由 sysTimer.Interval 决定（通常 10~50 毫秒）。
 *
 * 职责：
 *   1. 从 LingoFuse 的状态队列拉取所有消息并转发到 LogMemo。
 *   2. 驱动 LingoFuse 的软同步队列（Check_Soft_Thread_Synchronize）。
 *      这是 RegisterNotifySync 生效的关键：没有这一步，同步回调
 *      将永远得不到执行。
 *   3. 调用 LF_Sync 处理 LingoFuse 内部的其他同步任务。
 *
 * 若此定时器未启用或间隔过大，流式输出会有明显延迟甚至完全收不到。
 *)
procedure Tllm_tool_form.sysTimerTimer(Sender: TObject);
begin
  // 1) 拉取 LF 状态日志
  while LF_GetStatusCount > 0 do
    DoStatus(LF_GetStatusEx);

  // 2) 驱动软同步队列（同步回调的执行入口）
  Check_Soft_Thread_Synchronize(0);

  // 3) 处理 LF 内部同步任务
  LF_Sync;
end;

{ ----------------------------------------------------------------------------
  连接工作线程
  ---------------------------------------------------------------------------- }

(*
 * Do_Thread_Connect — 在后台线程执行实际的连接流程。
 *
 * 流程：
 *   1. 如果 LLM 尚未创建，先创建一个 TLLMClient 实例，
 *      并注册所有流式事件处理器（OnChunk/OnThink/OnError/...）。
 *   2. 调用 LLM.Connect：
 *      - 内部会执行 LF.ResetPrepare → PrepareClient → PrepareDone
 *        → Generate_AppName → CreateApp → RegisterNotifySync → BindApp
 *        → FetchCapabilities（best-effort 拉取能力矩阵）。
 *      - 失败时释放 LLM 并返回。
 *   3. 通过 LF.CheckApp 二次确认服务端已看到本客户端。
 *   4. 尝试把 sys_prompt_Memo 的内容推送给服务端的全局默认
 *      system message（可选步骤）：
 *        - 明确不支持（如 llm_proxy.py）：跳过调用，给出中文提示；
 *        - 信息未知（旧服务端）：尝试调用，向后兼容；
 *        - 明确支持（如 llm_service.py）：正常调用。
 *      无论哪种情况，都不影响连接本身的成功。
 *   5. 通过 TCompute.SyncM 回到主线程，触发 Do_Thread_Connect_Done。
 *
 * 注意：本过程在后台线程执行，只能操作 LLM 对象和数据。UI 相关的
 * 更新应尽可能回到主线程处理。当前的 DoStatus 调用依赖 Z 框架的
 * 内部线程安全策略；若后续出现偶发异常，可考虑改为入队 + 主线程
 * 消费的模式。
 *)
procedure Tllm_tool_form.Do_Thread_Connect;
var
  err: string;
  n: TP_String;
begin
  if LLM = nil then
  begin
    // 创建客户端并注册流式事件
    LLM := TLLMClient.Create(llm_APP_Edit.Text, LLM_Service_Edit.Text, 5000);

    LLM.OnChunk := Do_LLM_Chunk;
    LLM.OnThink := Do_LLM_Think;
    LLM.OnError := Do_LLM_Error;
    LLM.OnFinish := Do_LLM_Finish;
    LLM.OnClosed := Do_LLM_Closed;

    if not LLM.Connect(err) then
    begin
      DoStatus(err);
      disposeObjectAndNil(LLM);
      Exit;
    end;

    // 二次确认服务端已注册本客户端
    if not LF.CheckApp(llm_APP_Edit.Text) then
    begin
      disposeObjectAndNil(LLM);
      Exit;
    end;

    DoStatus('app "%s" 确认握手', [llm_APP_Edit.Text]);

    // 连接成功时报告一次服务端类型，便于用户 / 日志快速判断
    if LLM.HasCapabilityInfo then
      DoStatus('服务端类型: %s（能力矩阵已获取）', [LLM.ServerKind])
    else
      DoStatus('服务端未声明能力矩阵，相关调用将按兼容模式处理');
  end;

  // ---- 可选步骤：尝试同步默认系统消息 ----

  // 先通过能力矩阵做一次 API 检查：
  //   - 明确不支持（如 llm_proxy.py）：跳过，仅提示；
  //   - 信息未知（旧服务端）：尝试调用，向后兼容；
  //   - 明确支持（如 llm_service.py）：正常同步。

  // 该步骤失败不会影响连接；真正的系统提示词生效路径仍然是
  // "新建会话"按钮。
  if LLM.HasCapabilityInfo and (not LLM.LLMSupported(API_NAME_SET_SYSTEM_MESSAGE)) then
  begin
    DoStatus('（可选）当前服务端类型为 "%s"，不支持 set_system_message，' + '已跳过同步默认系统消息。',
      [LLM.ServerKind]);
    DoStatus('提示：点击"新建会话"按钮可以让系统提示词生效。');
  end
  else
  begin
    n := sys_prompt_Memo.Lines.Text;
    n := n.TrimChar(#13#10#32#9);
    if not LLM.SetSystemMessage(n, err) then
      DoStatus('（可选）同步默认系统消息失败：' + err + '。请点击"新建会话"让系统提示词生效。')
    else
      DoStatus('已同步默认系统消息');
  end;

  // 回到主线程更新 UI
  TCompute.SyncM(Do_Thread_Connect_Done);
end;

(*
 * Do_Thread_Connect_Done — 连接完成后的 UI 恢复（主线程执行）。
 *
 * 流程：
 *   1. 启用所有控件（连接过程中它们被 Disable_All 禁用了）。
 *   2. 切换到"输入"页。
 *
 * 注意：失败路径（Do_Thread_Connect 里提前 Exit）不会调用 SyncM，
 * 因此本过程只在成功路径下执行。
 *)
procedure Tllm_tool_form.Do_Thread_Connect_Done;
begin
  Enabled_All();
  sys_prompt_Memo.Enabled := LLM.LLMSupported(API_NAME_SET_SYSTEM_MESSAGE);
  Update_Sys_Prompt_Button.Enabled := LLM.LLMSupported(API_NAME_SET_SYSTEM_MESSAGE);
  if not LLM.LLMSupported(API_NAME_SET_SYSTEM_MESSAGE) then
  begin
    sys_prompt_Memo.Text := 'llm_proxy的系统提示词只能在智能体工具端设置!!' + #13#10 + '只有使用llm_service才能支持这个功能!!';
  end;
end;

{ ----------------------------------------------------------------------------
  生命周期
  ---------------------------------------------------------------------------- }

(*
 * Backcall_DoStatus — DoStatus 的全局钩子。
 *
 * 每当 Z 框架内部的 DoStatus 被调用时触发，把消息追加到 LogMemo。
 *
 * 参数：
 *   Text_  状态文本（SystemString，即 string）
 *   ID     状态 ID（此处未使用）
 *
 * 保护措施：日志超过 5000 行时清空，避免内存无限增长。
 *)
procedure Tllm_tool_form.Backcall_DoStatus(Text_: SystemString; const ID: integer);
begin
  if LogMemo.Lines.Count > 5000 then
    LogMemo.Lines.Clear;
  LogMemo.Lines.Add(UTF8Encode(Text_));
end;

(*
 * Create — 构造函数。
 *
 * 流程：
 *   1. 挂载 DoStatus 钩子，让所有 Z 框架日志自动出现在 LogMemo。
 *   2. 初始化内部状态（LLM := nil、FActiveSessionId := ''）。
 *   3. 禁用所有控件，然后只启用连接相关的几个控件
 *      （连接按钮、端点输入框、App 名称输入框）以及系统提示词和
 *      输出区，让用户可以先填写连接参数。
 *)
constructor Tllm_tool_form.Create(AOwner: TComponent);
begin
  inherited Create(AOwner);
  AddDoStatusHook(self, Backcall_DoStatus);

  LLM := nil;
  FActiveSessionId := '';

  Disable_All();

  // 连接前只允许操作这几个控件
  conn_llm_Button.Enabled := True;
  LLM_Service_Edit.Enabled := True;
  llm_APP_Edit.Enabled := True;
  sys_prompt_Memo.Enabled := True;
  sse_Edit.Enabled := True;
end;

(*
 * Destroy — 析构函数。
 *
 * 流程：卸载 DoStatus 钩子，然后调用 inherited Destroy。
 *
 * 注意：此处不释放 LLM 对象。LLM 的释放由 FormClose 或
 * 窗体外部逻辑负责（例如连接失败路径里的 disposeObjectAndNil）。
 *)
destructor Tllm_tool_form.Destroy;
begin
  RemoveDoStatusHook(self);
  inherited Destroy;
end;

(*
 * Enabled_All — 启用窗体上所有交互控件。
 *
 * 被调用的时机：
 *   - 连接成功后的 Do_Thread_Connect_Done
 *
 * 实现细节：遍历 ComponentCount，只对 TControl 及其子类
 * （输入框、Memo、SynEdit、Label、Button）设置 Enabled := True。
 *)
procedure Tllm_tool_form.Enabled_All;
var
  i: integer;
begin
  conn_llm_Button.Enabled := True;
  test_generate_Button.Enabled := True;
  for i := 0 to ComponentCount - 1 do
    if (Components[i] is TControl) then
    begin
      if (Components[i] is TCustomEdit) or (Components[i] is TCustomMemo) or (Components[i] is TSynEditBase) or
        (Components[i] is TCustomLabel) or (Components[i] is TCustomButton) then
      begin
        TControl(Components[i]).Enabled := True;
      end;
    end;
end;

(*
 * Disable_All — 禁用窗体上所有交互控件。
 *
 * 被调用的时机：
 *   - 窗体初始化
 *   - 连接按钮点击后、真正连接开始前（防止用户在连接过程中
 *     重复操作）
 *
 * 实现细节与 Enabled_All 对称。
 *)
procedure Tllm_tool_form.Disable_All;
var
  i: integer;
begin
  conn_llm_Button.Enabled := False;
  test_generate_Button.Enabled := False;
  for i := 0 to ComponentCount - 1 do
    if (Components[i] is TControl) then
    begin
      if (Components[i] is TCustomEdit) or (Components[i] is TCustomMemo) or (Components[i] is TSynEditBase) or
        (Components[i] is TCustomLabel) or (Components[i] is TCustomButton) then
      begin
        TControl(Components[i]).Enabled := False;
      end;
    end;
end;

(*
 * FormClose — 窗体关闭事件。
 *
 * 行为：
 *   1. 设置 CloseAction := caFree，让窗体在关闭时被释放。
 *   2. 调用 LF_Shutdown 释放 LingoFuse 全局资源。
 *
 * 已知问题（P0-1，参考 LingoFuse_LLM_Pitfalls_For_AI.md）：
 *   直接调用 LF_Shutdown 会跳过 LLM.Disconnect，可能：
 *   - 让正在执行的回调线程访问已释放的控件；
 *   - 造成 LingoFuse 主线程与 LLM 对象的资源释放顺序错误。
 *
 *   推荐做法（后续修复）：
 *     if LLM <> nil then
 *     begin
 *       LLM.Disconnect;      // 内部会 ExitMainThread + FreeApp
 *       disposeObjectAndNil(LLM);
 *     end;
 *     LF_Shutdown;
 *
 *   本版本保持不变以便与既有部署兼容，但请留意此风险。
 *)
procedure Tllm_tool_form.FormClose(Sender: TObject; var CloseAction: TCloseAction);
begin
  CloseAction := caFree;
  LF_Shutdown;
end;

end.
