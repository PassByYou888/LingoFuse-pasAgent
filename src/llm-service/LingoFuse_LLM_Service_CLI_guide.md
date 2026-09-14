# LingoFuse LLM Service 命令行使用手册

> **适用程序**：`llm_service`（Linux）/ `llm_service_*.exe`（Windows）  
> **文档版本**：V1.0  
> **最后更新**：2026-09-13

---

## 一、程序启动名

`llm_service` 支持两种部署形态，对应两种启动名：

| 平台 | 启动名 | 说明 |
|------|--------|------|
| **Windows** | `llm_service_cpu.exe` / `llm_service_cu124.exe` / `llm_service_vulkan.exe` / `llm_service_metal.exe` / `llm_service_openblas.exe` | 不同后缀对应不同推理后端 |
| **Linux** | `llm_service`（打包后无扩展名）；源码运行为 `python llm_service.py` | 同上，通常按后端区分为不同文件名 |

**后端区别**：

| 文件名 | 后端 | 适用场景 | 显存要求 |
|--------|------|----------|----------|
| `llm_service_cpu` | CPU（llama.cpp） | 无独显、笔记本、云主机 | 仅需内存 |
| `llm_service_cu124` | CUDA 12.4 | NVIDIA 显卡 | ≥ 8GB 显存跑 7B Q4_K_M |
| `llm_service_vulkan` | Vulkan | AMD/Intel/NVIDIA 跨平台 GPU | ≥ 8GB 显存 |
| `llm_service_metal` | Metal | Apple Silicon | 统一内存 |
| `llm_service_openblas` | OpenBLAS | CPU BLAS 加速 | 仅需内存 |

**判定规则**：程序启动时自动检测是否被 PyInstaller / Nuitka 打包。若已打包，`--help` 顶部用法行与示例显示当前可执行文件名；若源码运行，则显示 `llm_service.py`。

**本文档约定**：

- 所有命令示例分 **PowerShell（Windows）** 与 **Shell（Linux）** 两个版本
- Windows 多行续行使用**反引号** `` ` ``
- Linux 多行续行使用**反斜杠** `\`
- 示例中统一用 `llm_service_cpu` 作为程序名代表，实际替换为你所用后端版本即可

```powershell
# Windows PowerShell：查看帮助
llm_service_cpu.exe --help
```

```bash
# Linux Shell：查看帮助
./llm_service --help
```

---

## 二、快速开始

### 2.1 最小启动

前提：当前工作目录下有 `NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf` 模型文件，或通过 `--model-path` 指定。

**Windows（PowerShell）**：

```powershell
cd C:\Temp\temp2
.\llm_service_cpu.exe
```

**Linux（Shell）**：

```bash
cd /opt/llm
./llm_service_cpu
```

### 2.2 指定模型

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --model-path D:\models\qwen2.5-7b.gguf
```

**Linux（Shell）**：

```bash
./llm_service_cpu --model-path /data/models/qwen2.5-7b.gguf
```

### 2.3 GPU 加速（NVIDIA）

**Windows（PowerShell）**：

```powershell
llm_service_cu124.exe --gpu-layers -1 --threads 4
```

**Linux（Shell）**：

```bash
./llm_service_cu124 --gpu-layers -1 --threads 4
```

启动成功后，会打印一段状态横幅，然后进入监听状态：

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

## 三、运行前提

### 3.1 模型文件必须就位

服务默认从**当前工作目录**扫描：

```
NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

**要求**：

- 文件名大小写严格匹配，不要重命名。
- 文件必须与 `exe` 位于同一目录（或通过 `--model-path` 指定路径）。
- 文件完整，约 **4.7 GB**。

未找到时服务将报错退出：

```
[ERROR] Model file not found: ./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf
```

### 3.2 动态库必须可加载

`exe` 启动时首先加载 LingoFuse 动态库。成功时打印：

```
[INFO] Successfully loaded from system PATH: LingoFuse64.dll
```

失败时请检查：

- `LingoFuse64.dll` / `liblingofuse.so` 是否在系统 `PATH`，或在 `exe` 同目录。
- 动态库位数与 `exe` 一致（64 位 vs 32 位）。
- 依赖的 `z_ipc_64.dll` 是否可被找到。

### 3.3 工作目录建议

建议在**放模型和 exe 的目录**里打开命令行，这样默认路径就能生效。

**Windows（PowerShell）**：

```powershell
cd C:\Temp\temp2
.\llm_service_cpu.exe
```

**Linux（Shell）**：

```bash
cd /opt/llm
./llm_service_cpu
```

---

## 四、参数详解

### 4.1 模型与推理参数

#### `--model-path PATH`

- **作用**：指定 GGUF 模型文件路径（或 HuggingFace 模型目录）。
- **默认**：`./NVIDIA-Nemotron-3.5-Lightning-30B-A3B-UD-IQ4_NL.gguf`
- **环境变量**：`LLM_MODEL_PATH`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --model-path D:\models\qwen2.5-7b.gguf
```

**Linux（Shell）**：

```bash
./llm_service_cpu --model-path /data/models/qwen2.5-7b.gguf
```

#### `--context-size N`

- **作用**：上下文窗口大小（token 数）。
- **默认**：`0`（使用模型最大支持上下文）
- **环境变量**：`LLM_CONTEXT_SIZE`

**Windows（PowerShell）**：

```powershell
# 使用模型最大上下文（默认）
llm_service_cpu.exe --context-size 0

# 显式指定 8192
llm_service_cpu.exe --context-size 8192
```

**Linux（Shell）**：

```bash
# 使用模型最大上下文（默认）
./llm_service_cpu --context-size 0

# 显式指定 8192
./llm_service_cpu --context-size 8192
```

#### `--max-tokens N`

- **作用**：单次生成的最大 token 数（默认上限，可被请求级 `options.max_tokens` 覆盖）。
- **默认**：`4096`
- **环境变量**：`LLM_MAX_TOKENS`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --max-tokens 2048
```

**Linux（Shell）**：

```bash
./llm_service_cpu --max-tokens 2048
```

#### `--threads N`

- **作用**：CPU 推理线程数。
- **默认**：`6`
- **环境变量**：`LLM_THREADS`
- **建议**：设为**物理核心数的一半**（避免风扇狂转/温度过高）。

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --threads 8
```

**Linux（Shell）**：

```bash
./llm_service_cpu --threads 8
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
llm_service_cpu.exe --gpu-layers 0

# 全部卸载到 GPU
llm_service_cu124.exe --gpu-layers -1

# 显存不足时逐步下调
llm_service_cu124.exe --gpu-layers 20
```

**Linux（Shell）**：

```bash
# 纯 CPU
./llm_service_cpu --gpu-layers 0

# 全部卸载到 GPU
./llm_service_cu124 --gpu-layers -1

# 显存不足时逐步下调
./llm_service_cu124 --gpu-layers 20
```

#### `--system-message "MESSAGE"`

- **作用**：设置默认 system message（对新会话生效，可在运行时通过 `set_system_message` 修改）。
- **默认**：`Before answering, briefly list your reasoning steps using numbered bullets. Then give the final answer. Do not use Markdown.`
- **环境变量**：`LLM_SYSTEM_MESSAGE`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --system-message "You are a helpful assistant."
```

**Linux（Shell）**：

```bash
./llm_service_cpu --system-message "You are a helpful assistant."
```

### 4.2 LingoFuse 服务参数

#### `--endpoint ADDRESS`

- **作用**：LingoFuse 服务端点。IPC 用于同机通信，TCP 用于跨机通信。
- **默认**：`ipc:llm_service`
- **环境变量**：`LINGOFUSE_ENDPOINT`

**Windows（PowerShell）**：

```powershell
# 同机 IPC（默认）
llm_service_cpu.exe --endpoint ipc:llm_service

# 跨机 TCP（监听所有网卡）
llm_service_cpu.exe --endpoint 0.0.0.0:9898
```

**Linux（Shell）**：

```bash
# 同机 IPC（默认）
./llm_service_cpu --endpoint ipc:llm_service

# 跨机 TCP（监听所有网卡）
./llm_service_cpu --endpoint 0.0.0.0:9898
```

#### `--app-name NAME`

- **作用**：LingoFuse 应用名（客户端通过这个名字查找服务）。
- **默认**：`LLM_Service`
- **环境变量**：`LINGOFUSE_APP_NAME`
- **注意**：若要与 `llm_proxy` 同机共存，**必须**同时改 `--endpoint` 与 `--app-name`。

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --app-name LLM_Service --endpoint ipc:llm_service
```

**Linux（Shell）**：

```bash
./llm_service_cpu --app-name LLM_Service --endpoint ipc:llm_service
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
llm_service_cpu.exe --timeout 10000
```

**Linux（Shell）**：

```bash
./llm_service_cpu --timeout 10000
```

### 4.3 服务行为参数

#### `--session-timeout SECONDS`

- **作用**：会话空闲超时（秒）。**同时满足**以下两个条件时，会话才被 watchdog 回收：
  1. 空闲时长超过此值；
  2. 会话所属的客户端应用已离线。
- **默认**：`600`（10 分钟）
- **环境变量**：`LLM_SESSION_TIMEOUT`

**Windows（PowerShell）**：

```powershell
# 快速回收
llm_service_cpu.exe --session-timeout 300

# 长驻会话
llm_service_cpu.exe --session-timeout 3600
```

**Linux（Shell）**：

```bash
# 快速回收
./llm_service_cpu --session-timeout 300

# 长驻会话
./llm_service_cpu --session-timeout 3600
```

> **双条件回收策略说明**：客户端偶尔会断开重连（笔记本休眠、网络抖动、客户端重启）。如果仅按空闲时长回收，客户端只要暂停超过阈值就会丢失整个对话历史。加上"客户端离线"这一条件后，只要客户端还在线，会话就一直保留；只有当客户端真正离线（进程被杀、机器关机）且空闲超时，会话才被回收。

#### `--queue-max-size N`

- **作用**：待处理生成任务的最大排队数。达到上限后新请求会被拒绝。
- **默认**：`256`
- **环境变量**：`LLM_QUEUE_MAX_SIZE`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --queue-max-size 512
```

**Linux（Shell）**：

```bash
./llm_service_cpu --queue-max-size 512
```

#### `--max-sessions N`

- **作用**：最大并发会话数。达到上限后新建会话会被拒绝。
- **默认**：`1024`
- **环境变量**：`LLM_MAX_SESSIONS`

**Windows（PowerShell）**：

```powershell
# 单机限流
llm_service_cpu.exe --max-sessions 64
```

**Linux（Shell）**：

```bash
# 单机限流
./llm_service_cpu --max-sessions 64
```

### 4.4 聊天模板与推理参数

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
llm_service_cpu.exe --chat-template .\chat_template.jinja
```

**Linux（Shell）**：

```bash
./llm_service_cpu --chat-template ./chat_template.jinja
```

#### `--reasoning-budget-message "TEXT"`

- **作用**：在思考段开头插入的引导文本，用于引导模型用特定语言思考。
- **默认**：`好的，我用简体中文来思考。禁止使用英文。\n`
- **环境变量**：`LLM_REASONING_BUDGET_MESSAGE`
- **模板变量名**：`reasoning_budget_message`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --reasoning-budget-message "Think in English first."
```

**Linux（Shell）**：

```bash
./llm_service_cpu --reasoning-budget-message "Think in English first."
```

### 4.5 日志参数

#### `--log-level {0,1,2}`

- **作用**：日志详细程度。
  - `0` = quiet：抑制 chunk 日志和警告
  - `1` = normal：显示每个 chunk 的推送日志，抑制警告（默认）
  - `2` = debug：显示所有日志，包括"目标客户端不可达"等警告
- **默认**：`1`
- **环境变量**：`LLM_LOG_LEVEL`

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --log-level 1
```

**Linux（Shell）**：

```bash
./llm_service_cpu --log-level 1
```

#### `--debug`

- **作用**：等价于 `--log-level 2`。
- **环境变量**：`LLM_DEBUG`（`1` / `true` / `yes`）

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --debug
```

**Linux（Shell）**：

```bash
./llm_service_cpu --debug
```

#### `--quiet`

- **作用**：等价于 `--log-level 0`。
- **环境变量**：`LLM_QUIET`（`1` / `true` / `yes`）

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --quiet
```

**Linux（Shell）**：

```bash
./llm_service_cpu --quiet
```

**优先级**：`--debug` > `--quiet` > `--log-level`。

---

## 五、环境变量一览

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

### 5.1 Windows（PowerShell）

```powershell
$env:LLM_GPU_LAYERS = "0"
$env:LLM_THREADS = "8"
llm_service_cpu.exe
```

**永久生效**（写入用户环境变量）：

```powershell
[System.Environment]::SetEnvironmentVariable("LLM_GPU_LAYERS", "0", "User")
```

### 5.2 Linux（Shell）

```bash
export LLM_GPU_LAYERS=0
export LLM_THREADS=8
./llm_service_cpu
```

**永久生效**（写入 `~/.bashrc`）：

```bash
echo 'export LLM_GPU_LAYERS=0' >> ~/.bashrc
echo 'export LLM_THREADS=8' >> ~/.bashrc
source ~/.bashrc
```

**优先级**：命令行参数 > 环境变量 > 内置默认值。

---

## 六、完整使用场景

### 场景 1：CPU 纯离线启动（无独显）

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe `
  --gpu-layers 0 `
  --threads 8 `
  --quiet
```

**Linux（Shell）**：

```bash
./llm_service_cpu \
  --gpu-layers 0 \
  --threads 8 \
  --quiet
```

**要点**：

- 6~14 tokens/s（取决于 CPU）。
- 适合 7×24 小时运行，风扇噪声可控。

### 场景 2：NVIDIA 显卡加速（默认全卸载）

**Windows（PowerShell）**：

```powershell
llm_service_cu124.exe `
  --gpu-layers -1 `
  --threads 4
```

**Linux（Shell）**：

```bash
./llm_service_cu124 \
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
llm_service_cu124.exe --gpu-layers 20

# 若仍 OOM，降到 10 层
llm_service_cu124.exe --gpu-layers 10

# 最后回退纯 CPU
llm_service_cu124.exe --gpu-layers 0
```

**Linux（Shell）**：

```bash
# 先试 20 层
./llm_service_cu124 --gpu-layers 20

# 若仍 OOM，降到 10 层
./llm_service_cu124 --gpu-layers 10

# 最后回退纯 CPU
./llm_service_cu124 --gpu-layers 0
```

### 场景 4：自定义端点和应用名（多服务共存）

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe `
  --endpoint ipc:llm_service_A `
  --app-name LLM_Service_A
```

**Linux（Shell）**：

```bash
./llm_service_cpu \
  --endpoint ipc:llm_service_A \
  --app-name LLM_Service_A
```

**要点**：

- 便于同机跑多个 LLM 服务实例（加载不同模型）。
- 客户端需要对应调整 `--endpoint` 和 `--server-app`。

### 场景 5：跨机部署（TCP 模式）

**GPU 工作站（服务端）—— Windows（PowerShell）**：

```powershell
llm_service_cu124.exe `
  --endpoint 0.0.0.0:9898 `
  --app-name LLM_Service
```

**GPU 工作站（服务端）—— Linux（Shell）**：

```bash
./llm_service_cu124 \
  --endpoint 0.0.0.0:9898 \
  --app-name LLM_Service
```

**弱机笔记本（客户端）—— Windows（PowerShell）**：

```powershell
llm_test.exe --endpoint 192.168.1.100:9898 --server-app LLM_Service
```

**弱机笔记本（客户端）—— Linux（Shell）**：

```bash
./llm_test --endpoint 192.168.1.100:9898 --server-app LLM_Service
```

**要点**：

- 防火墙需放行 `9898` 端口。
- 客户端通过 `--endpoint` 指定远程 IP。

### 场景 6：日志调试（开发排查）

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --debug
```

**Linux（Shell）**：

```bash
./llm_service_cpu --debug
```

**要点**：

- 打印每个 chunk 的 JSON、客户端可达性警告、watchdog 决策日志。
- 仅用于排查，生产环境请用 `--quiet`。

### 场景 7：自定义系统提示词

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe `
  --system-message "你是一个代码声明转换助手，只转换声明部分，禁止 markdown 输出。"
```

**Linux（Shell）**：

```bash
./llm_service_cpu \
  --system-message "你是一个代码声明转换助手，只转换声明部分，禁止 markdown 输出。"
```

### 场景 8：自定义聊天模板

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe `
  --chat-template .\chat_template.jinja `
  --reasoning-budget-message "Think in Chinese first."
```

**Linux（Shell）**：

```bash
./llm_service_cpu \
  --chat-template ./chat_template.jinja \
  --reasoning-budget-message "Think in Chinese first."
```

**要点**：

- 模板中可访问 `messages`、`enable_thinking`、`reasoning_budget_message` 等变量。
- 若使用自定义模板，需安装 `jinja2`。

### 场景 9：与 `llm_proxy` 同机共存

**Windows（PowerShell）**：

```powershell
# 终端 1：llm_service 用默认端点
llm_service_cpu.exe

# 终端 2：llm_proxy 换用其他端点
llm_proxy.exe `
  --endpoint ipc:llm_proxy `
  --app-name LLM_Proxy `
  --backend-url http://127.0.0.1:1234/v1
```

**Linux（Shell）**：

```bash
# 终端 1：llm_service 用默认端点
./llm_service_cpu

# 终端 2：llm_proxy 换用其他端点
./llm_proxy \
  --endpoint ipc:llm_proxy \
  --app-name LLM_Proxy \
  --backend-url http://127.0.0.1:1234/v1
```

**要点**：

- 两者**必须**使用不同的 `--endpoint` 和 `--app-name`。
- 客户端连接时相应调整 `--endpoint` 与 `--server-app`。

### 场景 10：会话双条件回收调优

**Windows（PowerShell）**：

```powershell
# 桌面场景：会话保留 1 小时，客户端在线期间即使闲置也保留
llm_service_cpu.exe `
  --session-timeout 3600 `
  --max-sessions 64
```

**Linux（Shell）**：

```bash
# 服务器场景：会话保留 10 分钟，客户端离线且超时后回收
./llm_service_cpu \
  --session-timeout 600 \
  --max-sessions 1024
```

**要点**：

- 会话回收采用**双条件判断**：`空闲时长 > session_timeout` **且** `客户端离线`。
- 客户端在线时，会话不会因空闲被回收；客户端离线且超时才会被回收。

---

## 七、故障排查

### Q1：启动报 `Model file not found`

**原因**：模型文件不在预期位置。

**排查**：

**Windows（PowerShell）**：

```powershell
# 检查当前目录
Get-ChildItem *.gguf

# 或用绝对路径启动
llm_service_cpu.exe --model-path D:\models\qwen2.5-7b.gguf
```

**Linux（Shell）**：

```bash
# 检查当前目录
ls -lh *.gguf

# 或用绝对路径启动
./llm_service_cpu --model-path /data/models/qwen2.5-7b.gguf
```

### Q2：启动报 `Failed to load LingoFuse64.dll`

**原因**：动态库不在 `PATH` 或 `exe` 同目录。

**解决**：

**Windows（PowerShell）**：

```powershell
# 把动态库所在目录加入临时 PATH
$env:PATH = "D:\LingoFuse\Binary;$env:PATH"
llm_service_cpu.exe
```

**Linux（Shell）**：

```bash
# 把动态库所在目录加入临时 LD_LIBRARY_PATH
export LD_LIBRARY_PATH=/opt/LingoFuse/Binary:$LD_LIBRARY_PATH
./llm_service_cpu
```

### Q3：显存不足（`CUDA out of memory`）

**原因**：`--gpu-layers` 设置过大，或 `--context-size` 太大。

**解决**：

**Windows（PowerShell）**：

```powershell
# 逐步降低 GPU 层数
llm_service_cu124.exe --gpu-layers 20
llm_service_cu124.exe --gpu-layers 10
llm_service_cu124.exe --gpu-layers 0

# 或降低上下文
llm_service_cu124.exe --context-size 4096
```

**Linux（Shell）**：

```bash
# 逐步降低 GPU 层数
./llm_service_cu124 --gpu-layers 20
./llm_service_cu124 --gpu-layers 10
./llm_service_cu124 --gpu-layers 0

# 或降低上下文
./llm_service_cu124 --context-size 4096
```

### Q4：CPU 太慢 / 风扇狂转

**原因**：`--threads` 设置过大。

**解决**：

**Windows（PowerShell）**：

```powershell
# 减到物理核心数的一半
llm_service_cpu.exe --threads 4
```

**Linux（Shell）**：

```bash
# 减到物理核心数的一半
./llm_service_cpu --threads 4
```

### Q5：客户端收不到流

**排查顺序**：

1. **客户端是否用 `llm_stream` 注册了 Notify 回调？**
2. **`client_name` 是否在 `PrepareDone` 之后生成？**（`generate_app_name()` 必须在 `LF_PrepareDone()` 成功后调用）
3. **服务端 `--notify-api` 是否被改过？** 若改过，客户端也要相应调整。
4. **服务端日志是否出现 `no found app(...)`？** 表示客户端名字不对。

**Windows（PowerShell）**：

```powershell
# 用 debug 日志排查
llm_service_cpu.exe --debug
```

**Linux（Shell）**：

```bash
# 用 debug 日志排查
./llm_service_cpu --debug
```

### Q6：`Context length exceeded`

**原因**：输入过长。

**解决**：

**Windows（PowerShell）**：

```powershell
# 降低单次最大生成 token
llm_service_cpu.exe --max-tokens 2048

# 或调大上下文（注意内存占用）
llm_service_cpu.exe --context-size 16384
```

**Linux（Shell）**：

```bash
# 降低单次最大生成 token
./llm_service_cpu --max-tokens 2048

# 或调大上下文（注意内存占用）
./llm_service_cpu --context-size 16384
```

### Q7：端口 / IPC 队列被占用

**现象**：日志报 `Queue "llm_service0" is already occupied`。

**原因**：同机已有服务在监听 `ipc:llm_service`。

**解决**：

**Windows（PowerShell）**：

```powershell
llm_service_cpu.exe --endpoint ipc:llm_service_2
```

**Linux（Shell）**：

```bash
./llm_service_cpu --endpoint ipc:llm_service_2
```

### Q8：进程退不干净

**原因**：非优雅退出导致资源未释放。

**解决**：

- 优先使用 `Ctrl+C` 优雅退出。
- 若残留 IPC 队列，重启系统或在任务管理器中结束所有 LingoFuse 相关进程。

### Q9：会话被意外回收

**排查**：检查 `--session-timeout` 设置是否过小，以及客户端是否长时间离线。

**日志特征**：

```
[Session xxx] Idle for 601.3s (> 600s) and client app '@__generate__@...' is offline; reclaiming session
[Session xxx] Closed (reason=timeout+offline)
```

若客户端实际在线但会话仍被回收，可能是 `check_app` 缓存延迟（约 3 秒）导致误判。可调大 `--session-timeout` 缓解。

---

## 八、启动参数速查

```
llm_service_*.exe [OPTIONS]      # Windows
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

## 九、会话回收策略（重点说明）

`llm_service` 的 watchdog 采用**双条件回收**策略：

| 条件 | 状态 | 结果 |
|------|------|------|
| 空闲 > `session_timeout` | 客户端在线 | **保留会话**（客户端稍后可继续） |
| 空闲 > `session_timeout` | 客户端离线 | **回收会话**（reason = `timeout+offline`） |
| 空闲 ≤ `session_timeout` | 任意 | 保留 |
| 会话正在生成（`status != idle`） | 任意 | 保留（watchdog 不介入） |

**为什么这样设计**：

- 客户端偶尔断开重连（笔记本休眠、网络抖动、客户端重启），如果仅按空闲时长回收，客户端只要暂停超过阈值就会丢失整个对话历史。
- 加上"客户端离线"这一条件后，只要客户端还在线，会话就一直保留；只有当客户端真正离线（进程被杀、机器关机）且空闲超时，会话才被回收。

**watchdog 扫描周期**：每 5 秒一次。`check_app` 缓存更新延迟约 3 秒，因此刚断开的客户端在下一轮扫描时会被正确判定为离线。

---

## 十、相关文档

- **服务端命令行手册**：`LingoFuse_LLM_Proxy_CLI_Guide.md` —— `llm_proxy` 的对应使用手册
- **兼容性指南**：`LingoFuse_LLM_Proxy_Compatibility_Guide.md` —— 支持的全部 OpenAI 兼容后端清单
- **流式开发要点**：`LingoFuse_Python_Streaming_LLM_Guide.md` —— 客户端侧流式接入要点
- **模型下载指南**：`Qwen2.5-7B-Instruct-Q4_K_M.md` —— 模型下载与部署

---

**文档版本**：V1.0  
**维护者**：LingoFuse-pasAgent 团队  
**反馈**：问题提 Issue，急事加 Q（600585）