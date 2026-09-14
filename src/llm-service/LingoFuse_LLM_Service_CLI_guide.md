# LingoFuse LLM Service 命令行使用手册

> **适用程序**：`llm_service.exe`（Windows）/ `llm_service`（Linux）  
> **文档版本**：V2.1  
> **最后更新**：2026-09-14  
> **相关文档**（同目录）：
> - LLM 生态体系使用指南：`LingoFuse_LLM_Ecosystem_User_Guide.md`
> - LLM 代理命令行手册：`LingoFuse_LLM_Proxy_CLI_Guide.md`
> - 代理兼容性指南：`LingoFuse_LLM_Proxy_Compatibility_Guide.md`
> - 踩坑大全：`LingoFuse_LLM_Pitfalls_For_AI.md`
> - 版本演进总结：`LingoFuse_LLM_Service_Work_Summary.md`
> - llama-cpp-python 安装：`llama_cpp_python_guide.md`

---

## 一、程序定位

`llm_service.exe` 是一个 **基于 LingoFuse 服务网格的多会话流式 LLM 服务端**。它加载本地 GGUF 模型，暴露标准 LingoFuse API，供 AI 客户端或 MCP 网关调用。

它是 pasAgent 闭环中**“AI 的大脑”**这一环节，负责让 AI 理解用户意图、决定调用哪个工具、接收工具执行结果并生成最终回复。

### 图 1：llm_service 在闭环中的位置

```mermaid
flowchart LR
    A["📡 信标"] --> B["🌉 MCP 网关"]
    B --> C["🤖 AI 客户端"]
    C --> D["🧠 LLM 服务<br/>llm_service.exe"]
    D -->|"决策：调用工具"| B

    style A fill:#5B2C6F,stroke:#321640,stroke-width:3px,color:#FFFFFF
    style B fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style C fill:#922B21,stroke:#5A1A14,stroke-width:3px,color:#FFFFFF
    style D fill:#8E44AD,stroke:#5B2C6F,stroke-width:3px,color:#FFFFFF
```

**运行环境**：Windows / Linux。  
**依赖**：`LingoFuse64.dll` / `liblingofuse.so`（位于系统 PATH 或 exe 同目录）。

---

## 二、快速开始

### 2.1 最小启动

前提：当前工作目录下有 `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf` 模型文件，或通过 `--model-path` 指定。

**Windows（PowerShell）**：

```powershell
cd C:\Temp\temp2
.\llm_service.exe
```

**Linux（Shell）**：

```bash
cd /opt/llm
./llm_service
```

### 2.2 显存/内存不足时的替代方案

若本地加载 20 GB 模型资源不足，可改用 `llm_proxy.exe` 转发到 LM Studio：

```powershell
.\llm_proxy.exe --backend-url http://127.0.0.1:1234/v1
```

此时无需 `llm_service.exe` 和模型文件。详见同目录 `LingoFuse_LLM_Proxy_CLI_Guide.md`。

---

## 三、运行前提

### 3.1 模型文件必须就位

服务默认从**当前工作目录**扫描：

```
NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

**要求**：

- 文件名大小写严格匹配，不要重命名。
- 文件必须与 `llm_service.exe` 位于同一目录（或通过 `--model-path` 指定路径）。
- 文件完整，约 **20 GB**。

未找到时服务将报错退出：

```
[ERROR] Model file not found: ./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

> **模型下载**：请参考预编译包同目录下的模型文档，或从 Hugging Face 搜索 `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-GGUF`。

### 3.2 动态库必须可加载

启动时首先加载 LingoFuse 动态库。成功时打印：

```
[INFO] Successfully loaded from system PATH: LingoFuse64.dll
```

失败时请检查：

- `LingoFuse64.dll` / `liblingofuse.so` 是否在系统 `PATH`，或在 exe 同目录。
- 动态库位数与 exe 一致（64 位 vs 32 位）。
- 依赖的 `z_ipc_64.dll` 是否可被找到。

### 3.3 工作目录建议

建议在**放模型和 exe 的目录**里打开命令行，这样默认路径就能生效。

**Windows（PowerShell）**：

```powershell
cd C:\Temp\temp2
.\llm_service.exe
```

**Linux（Shell）**：

```bash
cd /opt/llm
./llm_service
```

---

## 四、启动流程一览

为避免一张图信息过载，按**启动阶段**拆分为两张小图。

### 图 2：启动阶段

```mermaid
flowchart LR
    A["1️⃣ 加载动态库"] --> B["2️⃣ 检测 LLM 后端"]
    B --> C["3️⃣ 加载 GGUF 模型"]
    C --> D["4️⃣ 注册 Call API"]
    D --> E["5️⃣ 启动服务网格"]
    E --> F["6️⃣ 进入监听状态"]

    style A fill:#1A5490,stroke:#0D2F52,stroke-width:3px,color:#FFFFFF
    style B fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
    style C fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style D fill:#5B2C6F,stroke:#321640,stroke-width:3px,color:#FFFFFF
    style E fill:#8E44AD,stroke:#5B2C6F,stroke-width:3px,color:#FFFFFF
    style F fill:#922B21,stroke:#5A1A14,stroke-width:3px,color:#FFFFFF
```

### 图 3：请求处理流程

```mermaid
flowchart LR
    A["客户端调用 generate"] --> B["立即返回 session_id"]
    B --> C["后台线程流式生成"]
    C --> D["逐 token 推送<br/>Sequenced Notify"]
    D --> E["发送 finish 事件"]

    style A fill:#1A5490,stroke:#0D2F52,stroke-width:3px,color:#FFFFFF
    style B fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
    style C fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style D fill:#8E44AD,stroke:#5B2C6F,stroke-width:3px,color:#FFFFFF
    style E fill:#922B21,stroke:#5A1A14,stroke-width:3px,color:#FFFFFF
```

启动成功后打印状态横幅：

```
======================================================================
 LINGOFUSE LLM SERVICE STATUS (v3.2)
======================================================================
  Server kind             : service
  Backend                 : llama_cpp
  Model path              : ./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
  Context size requested  : auto (model maximum)
  Context size actual     : 32768
  Default max tokens      : 4096
  CPU threads             : 6
  GPU layers offloaded    : -1
  LingoFuse endpoint      : ipc:llm_service
  Service app name        : LLM_Service
  Notify API name         : llm_stream
  Session idle timeout(s) : 600
  Queue max size          : 256
  Max sessions            : 1024
  Chat template           : (model built-in)
  Reasoning budget msg    : "好的，我用简体中文来思考。禁止使用英文。\n"
  Log level               : 1
----------------------------------------------------------------------
  Watchdog policy         : reclaim only when idle past the timeout
                            AND the client app is offline
  Supported APIs          : generate, create_session, close_session, cancel_session, list_sessions, set_system_message, health, llm_stream
  Unsupported APIs        : (none)
======================================================================
[Service] LLM Service is running on ipc:llm_service
[Service] Press Ctrl+C to stop...
```

---

## 五、参数详解

### 5.1 模型与推理参数

#### `--model-path PATH`

- **作用**：指定 GGUF 模型文件路径。
- **默认**：`./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf`
- **环境变量**：`LLM_MODEL_PATH`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --model-path D:\models\qwen2.5-7b.gguf
```

**Linux（Shell）**：

```bash
./llm_service --model-path /data/models/qwen2.5-7b.gguf
```

#### `--context-size N`

- **作用**：上下文窗口大小（token 数）。
- **默认**：`0`（使用模型最大支持上下文）
- **环境变量**：`LLM_CONTEXT_SIZE`

**Windows（PowerShell）**：

```powershell
# 使用模型最大上下文（默认）
.\llm_service.exe --context-size 0

# 显式指定 8192
.\llm_service.exe --context-size 8192
```

**Linux（Shell）**：

```bash
# 使用模型最大上下文（默认）
./llm_service --context-size 0

# 显式指定 8192
./llm_service --context-size 8192
```

#### `--max-tokens N`

- **作用**：单次生成的最大 token 数（默认上限，可被请求级 `options.max_tokens` 覆盖）。
- **默认**：`4096`
- **环境变量**：`LLM_MAX_TOKENS`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --max-tokens 2048
```

**Linux（Shell）**：

```bash
./llm_service --max-tokens 2048
```

#### `--threads N`

- **作用**：CPU 推理线程数。
- **默认**：`6`
- **环境变量**：`LLM_THREADS`
- **建议**：设为**物理核心数的一半**（避免风扇狂转/温度过高）。

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --threads 8
```

**Linux（Shell）**：

```bash
./llm_service --threads 8
```

#### `--gpu-layers N`

- **作用**：卸载到 GPU 的模型层数。
- **默认**：`-1`（全部卸载到 GPU；GPU 不可用时回退 CPU）
- **环境变量**：`LLM_GPU_LAYERS`
- **取值**：
  - `-1` = 全部层卸载到 GPU（有独显时性能最佳）
  - `0` = 纯 CPU 模式
  - `N > 0` = 卸载前 N 层到 GPU（显存不足时逐步下调）

**Windows（PowerShell）**：

```powershell
# 纯 CPU
.\llm_service.exe --gpu-layers 0

# 全部卸载到 GPU
.\llm_service.exe --gpu-layers -1

# 显存不足时逐步下调
.\llm_service.exe --gpu-layers 20
```

**Linux（Shell）**：

```bash
# 纯 CPU
./llm_service --gpu-layers 0

# 全部卸载到 GPU
./llm_service --gpu-layers -1

# 显存不足时逐步下调
./llm_service --gpu-layers 20
```

#### `--system-message "MESSAGE"`

- **作用**：设置默认 system message（对新会话生效，可在运行时通过 `set_system_message` 修改）。
- **默认**：`Before answering, briefly list your reasoning steps using numbered bullets. Then give the final answer. Do not use Markdown.`
- **环境变量**：`LLM_SYSTEM_MESSAGE`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --system-message "You are a helpful assistant."
```

**Linux（Shell）**：

```bash
./llm_service --system-message "You are a helpful assistant."
```

### 5.2 LingoFuse 服务参数

#### `--endpoint ADDRESS`

- **作用**：LingoFuse 服务端点。IPC 用于同机通信，TCP 用于跨机通信。
- **默认**：`ipc:llm_service`
- **环境变量**：`LINGOFUSE_ENDPOINT`

**Windows（PowerShell）**：

```powershell
# 同机 IPC（默认）
.\llm_service.exe --endpoint ipc:llm_service

# 跨机 TCP（监听所有网卡）
.\llm_service.exe --endpoint 0.0.0.0:9898
```

**Linux（Shell）**：

```bash
# 同机 IPC（默认）
./llm_service --endpoint ipc:llm_service

# 跨机 TCP（监听所有网卡）
./llm_service --endpoint 0.0.0.0:9898
```

#### `--app-name NAME`

- **作用**：LingoFuse 应用名（客户端通过这个名字查找服务）。
- **默认**：`LLM_Service`
- **环境变量**：`LINGOFUSE_APP_NAME`
- **注意**：若要与 `llm_proxy` 同机共存，**必须**同时改 `--endpoint` 与 `--app-name`。

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --app-name LLM_Service --endpoint ipc:llm_service
```

**Linux（Shell）**：

```bash
./llm_service --app-name LLM_Service --endpoint ipc:llm_service
```

#### `--notify-api NAME`

- **作用**：流式 token 推送使用的 Notify API 名。
- **默认**：`llm_stream`
- **环境变量**：`LINGOFUSE_NOTIFY_API`
- **注意**：客户端必须用**同一个名字**注册 Notify 回调才能收到流。除非有特殊需求，一般不改。

#### `--timeout MS`

- **作用**：Call API 的超时（毫秒），**不影响流式推送**。
- **默认**：`5000`
- **环境变量**：`LINGOFUSE_TIMEOUT_MS`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --timeout 10000
```

**Linux（Shell）**：

```bash
./llm_service --timeout 10000
```

### 5.3 服务行为参数

#### `--session-timeout SECONDS`

- **作用**：会话空闲超时（秒）。**同时满足**以下两个条件时，会话才被 watchdog 回收：
  1. 空闲时长超过此值；
  2. 会话所属的客户端应用已离线。
- **默认**：`600`（10 分钟）
- **环境变量**：`LLM_SESSION_TIMEOUT`

**Windows（PowerShell）**：

```powershell
# 快速回收
.\llm_service.exe --session-timeout 300

# 长驻会话
.\llm_service.exe --session-timeout 3600
```

**Linux（Shell）**：

```bash
# 快速回收
./llm_service --session-timeout 300

# 长驻会话
./llm_service --session-timeout 3600
```

> **双条件回收策略说明**：客户端偶尔会断开重连（笔记本休眠、网络抖动、客户端重启）。如果仅按空闲时长回收，客户端只要暂停超过阈值就会丢失整个对话历史。加上“客户端离线”这一条件后，只要客户端还在线，会话就一直保留；只有当客户端真正离线（进程被杀、机器关机）且空闲超时，会话才被回收。

### 图 4：会话回收双条件判断

```mermaid
flowchart TB
    A["Watchdog 每 5 秒扫描"] --> B{"会话状态 = idle?"}
    B -->|否| C["跳过（正在生成）"]
    B -->|是| D{"空闲 > session_timeout?"}
    D -->|否| E["保留（未超时）"]
    D -->|是| F{"客户端 app 在线?"}
    F -->|是| G["保留（客户端可能回来）"]
    F -->|否| H["回收会话<br/>reason=timeout+offline"]

    style A fill:#1A5490,stroke:#0D2F52,stroke-width:3px,color:#FFFFFF
    style B fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
    style C fill:#5D6D7E,stroke:#2C3E50,stroke-width:3px,color:#FFFFFF
    style D fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
    style E fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style F fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
    style G fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style H fill:#922B21,stroke:#5A1A14,stroke-width:3px,color:#FFFFFF
```

#### `--queue-max-size N`

- **作用**：待处理生成任务的最大排队数。达到上限后新请求会被拒绝。
- **默认**：`256`
- **环境变量**：`LLM_QUEUE_MAX_SIZE`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --queue-max-size 512
```

**Linux（Shell）**：

```bash
./llm_service --queue-max-size 512
```

#### `--max-sessions N`

- **作用**：最大并发会话数。达到上限后新建会话会被拒绝。
- **默认**：`1024`
- **环境变量**：`LLM_MAX_SESSIONS`

**Windows（PowerShell）**：

```powershell
# 单机限流
.\llm_service.exe --max-sessions 64
```

**Linux（Shell）**：

```bash
# 单机限流
./llm_service --max-sessions 64
```

### 5.4 聊天模板与推理参数

#### `--chat-template PATH`

- **作用**：指定 Jinja2 聊天模板文件路径。
- **默认**：（空）自动在脚本目录、父目录、当前工作目录中搜索 `chat_template.jinja`
- **环境变量**：`LLM_CHAT_TEMPLATE`
- **查找顺序**：
  1. 若指定此参数 / 环境变量，使用该路径（文件不存在则报错退出）。
  2. 否则在脚本目录、脚本父目录、当前工作目录中依次查找 `chat_template.jinja`。
  3. 都没有则使用模型内置模板。

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --chat-template .\chat_template.jinja
```

**Linux（Shell）**：

```bash
./llm_service --chat-template ./chat_template.jinja
```

#### `--reasoning-budget-message "TEXT"`

- **作用**：在思考段开头插入的引导文本，用于引导模型用特定语言思考。
- **默认**：`好的，我用简体中文来思考。禁止使用英文。\n`
- **环境变量**：`LLM_REASONING_BUDGET_MESSAGE`
- **模板变量名**：`reasoning_budget_message`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --reasoning-budget-message "Think in English first."
```

**Linux（Shell）**：

```bash
./llm_service --reasoning-budget-message "Think in English first."
```

### 5.5 日志参数

#### `--log-level {0,1,2}`

- **作用**：日志详细程度。
  - `0` = quiet：抑制 chunk 日志和警告
  - `1` = normal：显示每个 chunk 的推送日志，抑制警告（默认）
  - `2` = debug：显示所有日志，包括“目标客户端不可达”等警告
- **默认**：`1`
- **环境变量**：`LLM_LOG_LEVEL`

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --log-level 1
```

**Linux（Shell）**：

```bash
./llm_service --log-level 1
```

#### `--debug`

- **作用**：等价于 `--log-level 2`。
- **环境变量**：`LLM_DEBUG`（`1` / `true` / `yes`）

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --debug
```

**Linux（Shell）**：

```bash
./llm_service --debug
```

#### `--quiet`

- **作用**：等价于 `--log-level 0`。
- **环境变量**：`LLM_QUIET`（`1` / `true` / `yes`）

**Windows（PowerShell）**：

```powershell
.\llm_service.exe --quiet
```

**Linux（Shell）**：

```bash
./llm_service --quiet
```

**优先级**：`--debug` > `--quiet` > `--log-level`。

---

## 六、环境变量一览

所有命令行参数均可用同名环境变量替代。适合在启动脚本或系统服务中统一配置。

| 环境变量 | 对应参数 | 示例值 |
|----------|----------|--------|
| `LLM_MODEL_PATH` | `--model-path` | `D:\models\qwen.gguf` |
| `LLM_CONTEXT_SIZE` | `--context-size` | `8192` |
| `LLM_MAX_TOKENS` | `--max-tokens` | `2048` |
| `LLM_THREADS` | `--threads` | `8` |
| `LLM_GPU_LAYERS` | `--gpu-layers` | `0` |
| `LLM_SYSTEM_MESSAGE` | `--system-message` | `You are...` |
| `LINGOFUSE_ENDPOINT` | `--endpoint` | `ipc:llm_service` |
| `LINGOFUSE_APP_NAME` | `--app-name` | `LLM_Service` |
| `LINGOFUSE_NOTIFY_API` | `--notify-api` | `llm_stream` |
| `LINGOFUSE_TIMEOUT_MS` | `--timeout` | `10000` |
| `LLM_SESSION_TIMEOUT` | `--session-timeout` | `120` |
| `LLM_QUEUE_MAX_SIZE` | `--queue-max-size` | `256` |
| `LLM_MAX_SESSIONS` | `--max-sessions` | `1024` |
| `LLM_CHAT_TEMPLATE` | `--chat-template` | `./chat_template.jinja` |
| `LLM_REASONING_BUDGET_MESSAGE` | `--reasoning-budget-message` | `Think in Chinese.` |
| `LLM_LOG_LEVEL` | `--log-level` | `1` |
| `LLM_DEBUG` | `--debug` | `1` / `true` / `yes` |
| `LLM_QUIET` | `--quiet` | `1` / `true` / `yes` |

### 6.1 Windows（PowerShell）

```powershell
$env:LLM_GPU_LAYERS = "0"
$env:LLM_THREADS = "8"
.\llm_service.exe
```

**永久生效**（写入用户环境变量）：

```powershell
[System.Environment]::SetEnvironmentVariable("LLM_GPU_LAYERS", "0", "User")
```

### 6.2 Linux（Shell）

```bash
export LLM_GPU_LAYERS=0
export LLM_THREADS=8
./llm_service
```

**永久生效**（写入 `~/.bashrc`）：

```bash
echo 'export LLM_GPU_LAYERS=0' >> ~/.bashrc
echo 'export LLM_THREADS=8' >> ~/.bashrc
source ~/.bashrc
```

**优先级**：命令行参数 > 环境变量 > 内置默认值。

---

## 七、完整使用场景

### 场景 1：CPU 纯离线启动（无独显）

**Windows（PowerShell）**：

```powershell
.\llm_service.exe `
  --gpu-layers 0 `
  --threads 8 `
  --context-size 8192 `
  --quiet
```

**Linux（Shell）**：

```bash
./llm_service \
  --gpu-layers 0 \
  --threads 8 \
  --context-size 8192 \
  --quiet
```

**要点**：

- 6~14 tokens/s（取决于 CPU）。
- 20 GB 模型需 32 GB 以上内存，可适当降低上下文。

### 场景 2：GPU 加速（默认全卸载）

**Windows（PowerShell）**：

```powershell
.\llm_service.exe `
  --gpu-layers -1 `
  --threads 4
```

**Linux（Shell）**：

```bash
./llm_service \
  --gpu-layers -1 \
  --threads 4
```

**要点**：

- 20~40 tokens/s（取决于显卡）。
- `--threads 4`：GPU 推理时 CPU 线程数影响不大。

### 场景 3：显存不足时的渐进式调整

**Windows（PowerShell）**：

```powershell
# 先试 20 层
.\llm_service.exe --gpu-layers 20

# 若仍 OOM，降到 10 层
.\llm_service.exe --gpu-layers 10

# 最后回退纯 CPU
.\llm_service.exe --gpu-layers 0
```

**Linux（Shell）**：

```bash
# 先试 20 层
./llm_service --gpu-layers 20

# 若仍 OOM，降到 10 层
./llm_service --gpu-layers 10

# 最后回退纯 CPU
./llm_service --gpu-layers 0
```

### 场景 4：自定义端点和应用名（与 llm_proxy 共存）

**Windows（PowerShell）**：

```powershell
.\llm_service.exe `
  --endpoint ipc:llm_service `
  --app-name LLM_Service
```

**Linux（Shell）**：

```bash
./llm_service \
  --endpoint ipc:llm_service \
  --app-name LLM_Service
```

**要点**：

- `llm_proxy` 需要改用 `--endpoint ipc:llm_proxy --app-name LLM_Proxy`。
- 两者**不能**共享同一个 endpoint。

### 场景 5：跨机部署（TCP 模式）

**GPU 工作站（服务端）**：

```powershell
.\llm_service.exe `
  --endpoint 0.0.0.0:9898 `
  --app-name LLM_Service
```

**弱机笔记本（客户端）**：

```powershell
.\llm_test.exe --endpoint 192.168.1.100:9898 --server-app LLM_Service
```

**要点**：

- 防火墙需放行 `9898` 端口。
- 客户端通过 `--endpoint` 指定远程 IP。

### 场景 6：日志调试（开发排查）

```powershell
.\llm_service.exe --debug
```

- 打印每个 chunk 的 JSON、客户端可达性警告、watchdog 决策日志。
- 仅用于排查，生产环境请用 `--quiet`。

### 场景 7：自定义系统提示词

```powershell
.\llm_service.exe --system-message "你是一个代码声明转换助手，只转换声明部分，禁止 markdown 输出。"
```

### 场景 8：验证 LLM 服务是否正常

启动 `llm_service.exe` 后，在另一个窗口执行：

```powershell
.\llm_test.exe
```

进入交互式命令行，输入问题测试，`/quit` 退出。

---

## 八、运行时行为说明

### 8.1 多会话并发

每个 `generate` 请求独立 `session_id`、独立线程。多客户端并发**互不干扰**。每个会话的状态（`client_name`、`start_time`、`status`）由内部字典跟踪。

### 8.2 流式消息协议

服务端通过 `llm_stream` Notify API 推送以下结构化 JSON：

| 类型 | 字段 | 含义 |
|------|------|------|
| `chunk` | `session_id`, `text` | 正文流 |
| `think` | `session_id`, `text` | 思考流 |
| `finish` | `session_id`, `reason` | 生成结束 |
| `error` | `session_id`, `message` | 服务端错误 |
| `closed` | `session_id`, `reason` | 会话关闭 |

### 图 5：消息类型与客户端行为

```mermaid
flowchart LR
    A["chunk<br/>正文流"] --> B["客户端追加显示"]
    C["think<br/>思考流"] --> D["灰色显示 / 折叠"]
    E["finish<br/>生成结束"] --> F["更新状态栏"]
    G["error<br/>服务端错误"] --> H["错误提示"]
    I["closed<br/>会话关闭"] --> J["清理会话列表"]

    style A fill:#1A5490,stroke:#0D2F52,stroke-width:3px,color:#FFFFFF
    style C fill:#5D6D7E,stroke:#2C3E50,stroke-width:3px,color:#FFFFFF
    style E fill:#1E8449,stroke:#0E4D2A,stroke-width:3px,color:#FFFFFF
    style G fill:#922B21,stroke:#5A1A14,stroke-width:3px,color:#FFFFFF
    style I fill:#B7791F,stroke:#7E5109,stroke-width:3px,color:#FFFFFF
```

### 8.3 退出

- 按 `Ctrl+C`：优雅退出，打印 `[Service] Shutting down...`，清理资源。
- 通过 `atexit` 确保 `cleanup()` 被调用。
- **不建议**直接关窗口或 `kill -9`，可能残留 IPC 队列。

---

## 九、故障排查

### Q1：启动报 `Model file not found`

**排查**：

**Windows（PowerShell）**：

```powershell
# 检查当前目录
Get-ChildItem *.gguf

# 或用绝对路径启动
.\llm_service.exe --model-path D:\models\NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

**Linux（Shell）**：

```bash
# 检查当前目录
ls -lh *.gguf

# 或用绝对路径启动
./llm_service --model-path /data/models/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

### Q2：启动报 `Failed to load LingoFuse64.dll`

**解决**：

**Windows（PowerShell）**：

```powershell
# 把动态库所在目录加入临时 PATH
$env:PATH = "D:\LingoFuse\Binary;$env:PATH"
.\llm_service.exe
```

**Linux（Shell）**：

```bash
# 把动态库所在目录加入临时 LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/opt/LingoFuse/Binary:$LD_LIBRARY_PATH
./llm_service
```

### Q3：显存不足（`CUDA out of memory`）

**解决**：

**Windows（PowerShell）**：

```powershell
# 逐步降低 GPU 层数
.\llm_service.exe --gpu-layers 20
.\llm_service.exe --gpu-layers 10
.\llm_service.exe --gpu-layers 0

# 或降低上下文
.\llm_service.exe --context-size 4096
```

**Linux（Shell）**：

```bash
# 逐步降低 GPU 层数
./llm_service --gpu-layers 20
./llm_service --gpu-layers 10
./llm_service --gpu-layers 0

# 或降低上下文
./llm_service --context-size 4096
```

### Q4：内存不足（纯 CPU 场景）

20 GB 模型 + KV cache 需要 32 GB 以上内存。若内存不足：

- 降低 `--context-size`（如 4096）。
- 改用 `llm_proxy.exe` 转发到 LM Studio（LM Studio 可在有独显的机器上运行）。

### Q5：CPU 太慢 / 风扇狂转

**解决**：

**Windows（PowerShell）**：

```powershell
# 减到物理核心数的一半
.\llm_service.exe --threads 4
```

**Linux（Shell）**：

```bash
# 减到物理核心数的一半
./llm_service --threads 4
```

### Q6：客户端收不到流

**排查顺序**：

1. 客户端是否用 `llm_stream` 注册了 Notify 回调？
2. `client_name` 是否在 `PrepareDone` 之后生成？
3. 服务端 `--notify-api` 是否被改过？
4. 服务端日志是否出现 `no found app(...)`？

**用 debug 日志排查**：

```powershell
.\llm_service.exe --debug
```

### Q7：`Context length exceeded`

**解决**：

```powershell
# 降低单次最大生成 token
.\llm_service.exe --max-tokens 2048

# 或调大上下文（注意内存占用）
.\llm_service.exe --context-size 16384
```

### Q8：端口 / IPC 队列被占用

**现象**：日志报 `Queue "llm_service0" is already occupied`。

**解决**：

```powershell
.\llm_service.exe --endpoint ipc:llm_service_2
```

### Q9：会话被意外回收

**排查**：检查 `--session-timeout` 设置是否过小，以及客户端是否长时间离线。

**日志特征**：

```
[Session xxx] Idle for 601.3s (> 600s) and client app '@__generate__@...' is offline; reclaiming session
[Session xxx] Closed (reason=timeout+offline)
```

若客户端实际在线但会话仍被回收，可能是 `check_app` 缓存延迟（约 3 秒）导致误判。可调大 `--session-timeout` 缓解。

### Q10：llm_service 启动后立刻退出

**排查**：

- 是否缺少模型文件（见 Q1）。
- 是否有另一个 `llm_service` 或 `llm_proxy` 已占用 `ipc:llm_service`（见 Q8）。
- 查看窗口中的错误信息，或者截图发给豆包。

---

## 十、启动参数速查

```
llm_service.exe [OPTIONS]        # Windows
./llm_service [OPTIONS]          # Linux

模型与推理
  --model-path PATH           GGUF 模型路径 (默认: ./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf)
  --context-size N            上下文窗口 token 数 (默认: 0=自动)
  --max-tokens N              单次最大生成 token 数 (默认: 4096)
  --threads N                 CPU 线程数 (默认: 6)
  --gpu-layers N              GPU 层数, -1=全部, 0=纯CPU (默认: -1)
  --system-message "MSG"      默认系统提示词

LingoFuse 服务
  --endpoint ADDR             服务端点 (默认: ipc:llm_service)
  --app-name NAME             应用名 (默认: LLM_Service)
  --notify-api NAME           流式通知 API 名 (默认: llm_stream)
  --timeout MS                Call 超时 ms (默认: 5000)

服务行为
  --session-timeout SEC       会话空闲超时秒 (默认: 600)
  --queue-max-size N          最大排队任务数 (默认: 256)
  --max-sessions N            最大并发会话数 (默认: 1024)

聊天模板与推理
  --chat-template PATH        自定义 Jinja2 聊天模板
  --reasoning-budget-message  思考段引导文本

日志与调试
  --log-level {0,1,2}         日志级别 (默认: 1)
  --debug                     等价 --log-level 2
  --quiet                     等价 --log-level 0

环境变量与参数一一对应 (前缀 LLM_* 和 LINGOFUSE_*)
```

---

## 十一、相关文档（同目录）

| 文档 | 说明 |
|------|------|
| `LingoFuse_LLM_Ecosystem_User_Guide.md` | 闭环架构与生态总览 |
| `LingoFuse_LLM_Proxy_CLI_Guide.md` | `llm_proxy.exe` 命令行手册 |
| `LingoFuse_LLM_Proxy_Compatibility_Guide.md` | 支持的 129+ OpenAI 兼容后端清单 |
| `LingoFuse_LLM_Pitfalls_For_AI.md` | 踩坑大全，症状-根因-正确做法 |
| `LingoFuse_LLM_Service_Work_Summary.md` | LLM 工具链版本演进与架构决策（历史参考） |
| `llama_cpp_python_guide.md` | `llama-cpp-python` 安装与使用 |

---

**文档版本**：V2.1（仅保留同目录链接）  
**维护者**：LingoFuse-pasAgent 团队  
**反馈**：问题提 Issue，急事加 Q（600585）