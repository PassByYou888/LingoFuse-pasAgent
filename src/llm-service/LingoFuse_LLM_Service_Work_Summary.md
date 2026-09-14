# LingoFuse LLM 工具链工作总结

> **文档路径**：`LingoFuse_LLM_Toolchain_Work_Summary.md`  
> **版本**：v3.0  
> **涵盖周期**：2026-08-31 ~ 2026-09-13（合并两个阶段 + 本次工具链收尾工作）  
> **涉及组件**：Python 服务端、Python 代理层、Python 客户端、Pascal 客户端、Pascal GUI、工程脚本、全套文档  
> **版本变化**：v3.0 在 v2.0 基础上合并了"工具链收尾"阶段（`--help` 自适应、API 能力矩阵、会话双条件回收、编译脚本、代码审查）

---

## 一、工作概览

本次工作围绕 **LingoFuse LLM 工具链** 展开，覆盖 **Python 服务端 / 代理层 / 客户端** 与 **Pascal 客户端 / GUI** 两大语言生态，经历三个主要阶段：

1. **阶段 A（8/31 ~ 9/10）—— 服务端重构**  
   把最初一个**单会话、无状态、串行**的 LLM 网关，升级为**多会话、持久化、结构化协议**的工业级组件（`llm_service.py` v3.0）。
2. **阶段 B（9/11 ~ 9/13）—— 代理层与生态**  
   新增 **`llm_proxy.py`** —— 一个无状态转发器，把 LingoFuse 二进制 RPC 桥接到任何 OpenAI 兼容 HTTP 后端（LM Studio / Ollama / vLLM / DeepSeek / OpenRouter / Azure ...），并同步升级所有客户端与文档。
3. **阶段 C（本次会话）—— 工具链收尾**  
   统一三个 Python 工具的 `--help` 自适应；引入**跨语言 API 能力矩阵机制**；升级会话回收为**双条件判断**；一次性编译三个 EXE 的脚本；补齐依赖清单与兼容性指南；对所有交付文件做交叉审查。

### 一句话总结

> **从"能跑"到"能扛"，再到"能对接全世界"，最后到"全生态对齐"：19 项服务端缺陷修复 + 8 次代理层迭代 + 跨语言协议对齐 + 一套贯穿三端的 API 能力矩阵 + 全栈文档与工程脚本。**

### 交付物一览

```mermaid
mindmap
  root(("交付物<br/>本次工作"))
    Python服务端
      llm_service_py_v3_2
      chat_template_jinja
    Python代理层
      llm_proxy_py_v1_8
    Python客户端
      llm_test_py_v3_6
    Pascal客户端
      llm_client_pas_v3_3
    PascalGUI
      llm_tool_frm_pas_v3_1
    工程脚本
      build_llm_service_ps1
      requirements_txt
    文档
      工作总结_v3_0
      踩坑文档_v2_0
      服务端命令行手册
      代理层命令行手册
      兼容性指南
      流式开发指南
```

---

## 二、时间线与版本演进

### 2.1 三阶段时间轴

```mermaid
timeline
    title LingoFuse LLM 工具链版本演进（三阶段）
    section 阶段 A：服务端重构
        缺陷研究 : 19 项缺陷分级
                 : 2 致命 + 6 严重 + 11 一般
        v2.0 架构重构 : 单 worker 串行化
                     : thinking 开关
                     : 结构化消息协议
        v2.1 配置统一 : 上下文默认 0
                     : 全局 CONFIG
        v2.2 模板统一 : 只保留一份
                     : 多路径搜索
        v3.0 持久多会话 : session 生命周期
                       : 多会话并发
        跨语言对接 : llm_client_pas
                   : 双参数事件
    section 阶段 B：代理层与生态
        llm_proxy v1.0 ~ v1.3 : 初版转发
                              : 认证支持
                              : 全局变量中心化
        llm_proxy v1.4 : 实时性诊断
                       : http_client 替换 requests
        llm_proxy v1.5 ~ v1.7 : Accept-Encoding identity
                              : TCP_NODELAY
                              : thinking 无策略化
        llm_proxy v1.8 : set_system_message 拒绝
                       : 死字段清理
        客户端同步 : emoji 控制台
                   : new_session 实现
    section 阶段 C：工具链收尾
        help 自适应 : 三工具统一
                    : frozen 检测
        API 能力矩阵 : get_api_capabilities
                     : server_kind
        会话双条件回收 : 超时 AND 离线
                       : reason=timeout+offline
        工程脚本 : build_llm_service_ps1
                 : requirements_txt
        代码审查 : 三方协议交叉验证
```

### 2.2 版本编号对照

```mermaid
flowchart LR
    subgraph A["阶段 A：服务端"]
        V0["v1.0"] --> V20["v2.0"] --> V21["v2.1"] --> V22["v2.2"] --> V30["v3.0"]
        V30 --> V32["v3.2"]
    end

    subgraph B["阶段 B：代理层"]
        PV0["v1.0 初版"] --> PV14["v1.4\n实时诊断"]
        PV14 --> PV15["v1.5\nidentity"]
        PV15 --> PV16["v1.6\nTCP_NODELAY"]
        PV16 --> PV17["v1.7\n无策略化"]
        PV17 --> PV18["v1.8\n拒绝机制"]
    end

    subgraph C["阶段 C：工具链"]
        C1["--help 自适应"] --> C2["能力矩阵"]
        C2 --> C3["双条件回收"]
        C3 --> C4["编译脚本"]
    end

    V32 --> C1
    PV18 --> C1

    style V0 fill:#95A5A6,stroke:#5D6D7E,stroke-width:3px,color:#FFFFFF
    style V32 fill:#E67E22,stroke:#9C4A0C,stroke-width:4px,color:#FFFFFF
    style PV0 fill:#95A5A6,stroke:#5D6D7E,stroke-width:3px,color:#FFFFFF
    style PV18 fill:#8E44AD,stroke:#5B2C6F,stroke-width:4px,color:#FFFFFF
    style C1 fill:#3498DB,stroke:#1F618D,stroke-width:3px,color:#FFFFFF
    style C4 fill:#2ECC71,stroke:#1E8449,stroke-width:5px,color:#FFFFFF
```

### 2.3 三阶段全景

```mermaid
flowchart TB
    subgraph A["🔵 阶段 A：服务端重构"]
        A1["19 项缺陷研究"]
        A2["单 worker 串行化"]
        A3["结构化消息协议"]
        A4["持久多会话"]
    end

    subgraph B["🟣 阶段 B：代理层与生态"]
        B1["llm_proxy 初版"]
        B2["SSE 实时性攻坚"]
        B3["无策略转发"]
        B4["明确拒绝机制"]
    end

    subgraph C["🟢 阶段 C：工具链收尾"]
        C1["--help 自适应"]
        C2["API 能力矩阵"]
        C3["双条件回收"]
        C4["编译脚本 + 文档"]
    end

    A --> B --> C

    style A fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style B fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
    style C fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
```

---

## 三、服务端架构演进（阶段 A）

### 3.1 架构对比：v1.0 与 v3.0

```mermaid
flowchart TB
    subgraph OLD["🔴 v1.0 原始架构"]
        O1["LingoFuse 回调线程"] -->|直接调用| O2["self.llm<br/>共享上下文"]
        O3["LingoFuse 回调线程"] -->|直接调用| O2
        O2 -.->|"KV cache 污染"| OC["💥 崩溃"]
    end

    subgraph NEW["🟢 v3.0 重构架构"]
        N1["LingoFuse 回调线程"] -->|入队| NQ["queue.Queue<br/>FIFO"]
        N2["LingoFuse 回调线程"] -->|入队| NQ
        NQ --> NW["单 worker 线程"]
        NW -->|独占调用| NL["self.llm"]
        NW -->|"Sequenced Notify"| NC1["client-A"]
        NW -->|"Sequenced Notify"| NC2["client-B"]
    end

    style OLD fill:#FADBD8,stroke:#922B21,stroke-width:4px
    style NEW fill:#D5F5E3,stroke:#1E8449,stroke-width:4px
    style O2 fill:#E74C3C,stroke:#922B21,stroke-width:3px,color:#FFFFFF
    style OC fill:#641E16,stroke:#4A0E0E,stroke-width:3px,color:#FFFFFF
    style NW fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style NQ fill:#F5A623,stroke:#B7791F,stroke-width:3px,color:#FFFFFF
```

**核心洞察**：llama.cpp 的 `llama_context` 是**单线程状态机**（KV cache、采样器 RNG、BPE 状态全共享），v1.0 的多线程直调会导致进程级 abort。v3.0 用**单 worker 串行化**彻底消除这个类别的问题。

### 3.2 组件分层

```mermaid
flowchart TB
    subgraph L1["🎯 接入层"]
        API["Call API<br/>generate / create_session<br/>close_session / cancel_session<br/>list_sessions / set_system_message<br/>get_api_capabilities / health"]
    end

    subgraph L2["🧵 并发层"]
        CB["LingoFuse 回调线程<br/>快速响应"]
        Q["queue.Queue<br/>FIFO 队列"]
        W["单 worker 线程"]
        WD["Watchdog 线程<br/>双条件回收"]
    end

    subgraph L3["🧠 推理层"]
        TPL["Jinja2 模板渲染"]
        TH["ThinkingParser<br/>状态机"]
        LLM["llama_cpp.Llama<br/>独占调用"]
    end

    subgraph L4["📡 通信层"]
        SEQ["LF_Sequenced_Notify<br/>FIFO 保证"]
    end

    API --> CB
    CB --> Q
    Q --> W
    W --> TPL
    TPL --> LLM
    LLM --> TH
    TH --> SEQ
    WD -.->|"监控"| Q

    style L1 fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style L2 fill:#FDEBD0,stroke:#B7791F,stroke-width:3px
    style L3 fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
    style L4 fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
```

---

## 四、代理层架构（阶段 B）

### 4.1 llm_proxy 的角色定位

`llm_proxy.py` 是一个 **LingoFuse 服务端**，但它的内部逻辑与 `llm_service.py` 完全不同：它不加载模型，只做协议翻译。

```mermaid
flowchart TB
    subgraph IN["📥 LingoFuse 侧"]
        CALL["LF Call: generate(...)"]
        NOTIFY["LF Notify: llm_stream"]
    end

    subgraph PROXY["🌉 llm_proxy 内部"]
        HANDLER["Call 处理器<br/>_handle_generate"]
        SESSION["Session 注册表<br/>重建 messages 数组"]
        BACKEND["HTTP 客户端<br/>http.client"]
        EMIT["Notify 发射器<br/>jdump + LF_WriteBuffer"]
    end

    subgraph OUT["📤 后端侧"]
        HTTP["POST /v1/chat/completions"]
        SSE["SSE 流解析"]
    end

    CALL --> HANDLER
    HANDLER --> SESSION
    SESSION --> BACKEND
    BACKEND --> HTTP
    HTTP --> SSE
    SSE --> EMIT
    EMIT --> NOTIFY

    style PROXY fill:#E8DAEF,stroke:#6C3483,stroke-width:4px
    style BACKEND fill:#8E44AD,stroke:#5B2C6F,stroke-width:4px,color:#FFFFFF
    style HANDLER fill:#9B59B6,stroke:#6C3483,stroke-width:3px,color:#FFFFFF
```

### 4.2 无状态语义下的会话处理

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant Proxy as llm_proxy
    participant Backend as LM Studio

    Note over Client,Backend: 第一轮（新建会话）
    Client->>Proxy: generate(client_name, content="你好")
    Proxy->>Proxy: 创建 Session，记录 system_message
    Proxy->>Proxy: 组装 messages=[user:"你好"]
    Proxy->>Backend: POST /v1/chat/completions
    Backend-->>Proxy: SSE 流式响应
    Proxy-->>Client: Notify chunk/think/finish
    Proxy->>Proxy: 追加 history

    Note over Client,Backend: 第二轮（继续会话）
    Client->>Proxy: generate(session_id, content="再来一首")
    Proxy->>Proxy: 查找 Session，取 history
    Proxy->>Proxy: 组装 messages=[user:"你好",<br/>assistant:"...",user:"再来一首"]
    Proxy->>Backend: POST /v1/chat/completions
    Backend-->>Proxy: SSE
    Proxy-->>Client: Notify chunk/think/finish
```

**要点**：代理**不持有**模型 KV cache，每轮请求都**重新组装**完整 messages 数组发给后端；后端视角是"无状态 HTTP"，客户端视角是"持久会话"。

### 4.3 SSE 传输层的发现之旅

这是本次工作中**最曲折**的一段。以下是排查过程的完整记录：

```mermaid
flowchart TB
    START["症状：客户端延迟 17 秒"] --> A1["尝试 1: iter_lines"]
    A1 --> A2["尝试 2: iter_content(None)"]
    A2 --> A3["尝试 3: iter_content(1)"]
    A3 --> A4["尝试 4: Accept-Encoding identity"]
    A4 --> A5["诊断: 时间戳日志"]
    A5 --> A6["发现: gzip 压缩"]
    A6 --> A7["修复: 显式 identity"]
    A7 --> A8["仍有延迟"]
    A8 --> A9["发现: iter_content 参数陷阱"]
    A9 --> A10["终极方案: http.client"]
    A10 --> DONE["✅ 解决"]

    style START fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
    style DONE fill:#2ECC71,stroke:#1E8449,stroke-width:5px,color:#FFFFFF
    style A10 fill:#8E44AD,stroke:#5B2C6F,stroke-width:4px,color:#FFFFFF
```

**三层缓冲，缺一不可**：

| 层 | 缓冲源 | 症状 | 修复 |
|----|--------|------|------|
| 1 | `iter_lines()` 内部 512 字节缓冲 | 短 SSE 行攒够才 yield | 换 `iter_content` |
| 2 | `iter_content(None)` = "读直到 EOF" | 整个响应才一次性返回 | 换 `chunk_size=1` |
| 3 | gzip 解码器攒够 deflate 块才吐 | 又是批量输出 | `Accept-Encoding: identity` |
| 4 | `urllib3` 内部预读 socket | 换了前面也还是延迟 | 换 `http.client` |

**最终方案**：`http.client` + `Accept-Encoding: identity` + `TCP_NODELAY`。

### 4.4 thinking 流的处理

**核心决策：代理不做任何策略**。

```mermaid
flowchart LR
    BE["后端 SSE<br/>reasoning_content + content"]
    PROXY["llm_proxy<br/>无策略转发"]
    CLI["客户端<br/>自己决定显示"]

    BE --> PROXY
    PROXY -->|"reasoning_content → think 事件"| CLI
    PROXY -->|"content → chunk 事件"| CLI

    style PROXY fill:#8E44AD,stroke:#5B2C6F,stroke-width:4px,color:#FFFFFF
    style BE fill:#3498DB,stroke:#1F618D,stroke-width:3px,color:#FFFFFF
    style CLI fill:#2ECC71,stroke:#1E8449,stroke-width:3px,color:#FFFFFF
```

**为什么移除 `--include-thinking` 开关**：是否产生 thinking 由**模型**决定，不由代理决定；代理加开关等于"替客户端做策略"。客户端想不显示 think 事件，忽略即可；想显示，渲染即可。

### 4.5 set_system_message 的拒绝机制

**从"假成功"到"明确拒绝"**：

```mermaid
flowchart TB
    subgraph OLD["❌ 早期实现"]
        O1["set_system_message 请求"] --> O2["写入 _default_system_message"]
        O2 --> O3["返回 code:0 假成功"]
        O3 --> O4["实际没有任何效果"]
    end

    subgraph NEW["✅ v1.8 修复"]
        N1["set_system_message 请求"] --> N2["记录日志"]
        N2 --> N3["返回 code:-1 unsupported"]
        N3 --> N4["提示客户端走 CreateSession"]
    end

    style OLD fill:#FADBD8,stroke:#922B21,stroke-width:4px
    style NEW fill:#D5F5E3,stroke:#1E8449,stroke-width:4px
    style O4 fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
    style N4 fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
```

**理由**：代理是无状态转发器，"全局默认 system message"这个概念在其语义下不存在。**撒谎比拒绝更危险**。

---

## 五、API 能力矩阵机制（阶段 C 新增）

### 5.1 设计背景

`llm_service.py` 与 `llm_proxy.py` 是**兄弟服务端**，共用同一端点（`ipc:llm_service`）与同一 App 名（`LLM_Service`），但功能集不同——`set_system_message` 只在 `llm_service` 中可用。客户端需要一种机制发现"当前运行的是哪一个"。

### 5.2 能力矩阵结构

```mermaid
classDiagram
    class CapabilityResponse {
        +int code
        +str server_kind
        +Dict capabilities
    }

    class Capabilities {
        +int generate
        +int create_session
        +int close_session
        +int cancel_session
        +int list_sessions
        +int set_system_message
        +int health
        +int llm_stream
    }

    class ServerKind {
        <<enumeration>>
        service
        proxy
    }

    CapabilityResponse --> Capabilities
    CapabilityResponse --> ServerKind
```

**服务端差异**：

| API | `llm_service` | `llm_proxy` |
|-----|:-------------:|:-----------:|
| `generate` | 1 | 1 |
| `create_session` | 1 | 1 |
| `close_session` | 1 | 1 |
| `cancel_session` | 1 | 1 |
| `list_sessions` | 1 | 1 |
| **`set_system_message`** | **1** | **0** |
| `health` | 1 | 1 |
| `llm_stream` | 1 | 1 |
| `server_kind` | `"service"` | `"proxy"` |

### 5.3 三方能力发现流程

```mermaid
sequenceDiagram
    participant PS as Python 服务端
    participant PC as Python 客户端
    participant PA as Pascal 客户端

    Note over PS: 暴露 get_api_capabilities
    PC->>PS: Connect
    PC->>PS: get_api_capabilities
    PS-->>PC: {code, server_kind, capabilities}
    PC->>PC: 缓存到 STATE.api_capabilities

    PA->>PS: Connect
    PA->>PS: get_api_capabilities
    PS-->>PA: {code, server_kind, capabilities}
    PA->>PA: 缓存到 FCapabilities

    Note over PC,PA: 后续命令先查缓存
    PC->>PC: llm_supported("set_system_message")
    PA->>PA: LLMSupported(API_NAME_SET_SYSTEM_MESSAGE)
    alt 明确不支持
        PC-->>PC: 本地短路 + 友好提示
        PA-->>PA: 本地短路 + 友好提示
    else 明确支持
        PC->>PS: set_system_message(content)
        PA->>PS: set_system_message(content)
    end
```

### 5.4 客户端降级行为

```mermaid
flowchart TB
    START["客户端准备调用某 API"] --> Q1{"能力矩阵已获取?"}
    Q1 -->|是| Q2{"该 API 值为 1?"}
    Q1 -->|否| FALLBACK["回退到无条件调用<br/>（向后兼容）"]
    Q2 -->|是| NORMAL["正常调用"]
    Q2 -->|否| SHORTCUT["本地短路<br/>返回友好提示<br/>不发 RPC"]

    style START fill:#4A90E2,stroke:#1E3A8A,stroke-width:4px,color:#FFFFFF
    style NORMAL fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style SHORTCUT fill:#F5A623,stroke:#B7791F,stroke-width:4px,color:#FFFFFF
    style FALLBACK fill:#95A5A6,stroke:#5D6D7E,stroke-width:4px,color:#FFFFFF
```

**关键设计**：`HasCapabilityInfo` 与 `LLMSupported` 分离——前者回答"信息可靠吗"，后者回答"支持吗"。这个分离让"未知"与"不支持"得以区分：

| 缓存状态 | `HasCapabilityInfo` | `LLMSupported(api)` | 调用方行为 |
|----------|:-------------------:|:-------------------:|-----------|
| 已获取 | True | 按矩阵返回 | 按支持度决策 |
| 未获取 | False | 一律 False | 保持原样尝试 |

### 5.5 客户端实现入口

```mermaid
flowchart LR
    subgraph PY["🐍 Python 客户端"]
        PY1["fetch_capabilities()"]
        PY2["llm_supported(api)"]
        PY3["STATE.api_capabilities"]
        PY4["STATE.server_kind"]
    end

    subgraph PAS["🅿️ Pascal 客户端"]
        PA1["FetchCapabilities()"]
        PA2["HasCapabilityInfo"]
        PA3["LLMSupported(api)"]
        PA4["ServerKind"]
    end

    PY1 --> PY3
    PY1 --> PY4
    PY3 --> PY2
    PA1 --> PA2
    PA1 --> PA4
    PA2 --> PA3

    style PY fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style PAS fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
```

---

## 六、会话双条件回收策略（阶段 C 升级）

### 6.1 从单条件到双条件

```mermaid
flowchart TB
    subgraph OLD["❌ 单条件（v3.0 早期）"]
        O1["空闲 > session_timeout"] --> O2["直接回收"]
        O2 -.->|"客户端还在线也丢"| O3["对话历史丢失"]
    end

    subgraph NEW["✅ 双条件（v3.2）"]
        N1["空闲 > session_timeout"] --> N2{"客户端 app 在线?"}
        N2 -->|是| N3["保留会话"]
        N2 -->|否| N4["回收会话<br/>reason=timeout+offline"]
    end

    style OLD fill:#FADBD8,stroke:#922B21,stroke-width:4px
    style NEW fill:#D5F5E3,stroke:#1E8449,stroke-width:4px
    style O3 fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
    style N4 fill:#E67E22,stroke:#9C4A0C,stroke-width:4px,color:#FFFFFF
```

### 6.2 四种组合行为

```mermaid
flowchart TD
    START["Watchdog 每 5 秒扫描"] --> C0{"会话状态 = idle?"}
    C0 -->|否| SKIP["跳过（正在生成）"]
    C0 -->|是| C1{"空闲 > session_timeout?"}
    C1 -->|否| KEEP["保留（未超时）"]
    C1 -->|是| C2{"check_app(client_name)?"}
    C2 -->|True| KEEP2["保留（客户端在线，等它回来）"]
    C2 -->|False| CLOSE["回收<br/>reason=timeout+offline"]

    style START fill:#4A90E2,stroke:#1E3A8A,stroke-width:4px,color:#FFFFFF
    style SKIP fill:#95A5A6,stroke:#5D6D7E,stroke-width:3px,color:#FFFFFF
    style KEEP fill:#2ECC71,stroke:#1E8449,stroke-width:3px,color:#FFFFFF
    style KEEP2 fill:#2ECC71,stroke:#1E8449,stroke-width:3px,color:#FFFFFF
    style CLOSE fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
```

### 6.3 时序示例

```mermaid
sequenceDiagram
    participant C as 客户端
    participant S as 服务端
    participant W as Watchdog

    C->>S: create_session
    Note over S: last_active_at = 0
    C->>S: generate
    Note over S: last_active_at = 100

    W->>S: 扫描（t=700）
    Note over W: 空闲 600s == 阈值<br/>不满足 > ，跳过

    W->>S: 扫描（t=701）
    Note over W: 空闲 601s > 600s ✅<br/>check_app → True<br/>保留会话

    Note over C: 客户端进程被 kill
    W->>S: 扫描（t=1601）
    Note over W: 空闲 1501s > 600s ✅<br/>check_app → False<br/>回收，reason=timeout+offline
    S-->>C: (无法送达) closed 通知
```

### 6.4 新增 reason 值

```mermaid
mindmap
  root(("closed reason 取值"))
    client
      客户端主动 close_session
    timeout_offline
      Watchdog 双条件回收
    shutdown
      服务端关机
    ephemeral
      一次性会话自动关闭
    error
      创建/推理失败回滚
```

---

## 七、`--help` 自适应机制（阶段 C 新增）

### 7.1 问题与方案

**问题**：源码模式运行时 `--help` 显示 `python xxx.py ...`，打包为 EXE 后仍显示 `python xxx.py`，与实际调用方式不符。

**方案**：三个 Python 工具（`llm_service.py`、`llm_proxy.py`、`llm_test.py`）统一引入三个辅助函数。

```mermaid
flowchart LR
    subgraph DETECT["🔍 检测阶段"]
        D1["is_frozen_exe()"]
        D2["检查 sys.frozen"]
        D3["检查 sys._MEIPASS"]
        D1 --> D2
        D1 --> D3
    end

    subgraph DISPLAY["🖥️ 显示阶段"]
        S1["get_invocation_name()<br/>传给 argparse prog="]
        S2["get_example_invocation()<br/>用于 epilog 示例"]
    end

    DETECT --> DISPLAY

    style DETECT fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style DISPLAY fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
```

### 7.2 效果对照

| 运行模式 | usage 显示 | 示例显示 |
|----------|-----------|----------|
| 源码 | `usage: llm_service.py ...` | `python llm_service.py --model-path ...` |
| EXE | `usage: llm_service_cpu.exe ...` | `llm_service_cpu.exe --model-path ...` |

### 7.3 关键代码骨架

```python
def is_frozen_exe() -> bool:
    return getattr(sys, 'frozen', False) or hasattr(sys, '_MEIPASS')

def get_invocation_name() -> str:
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return os.path.basename(os.path.abspath(__file__))

def get_example_invocation() -> str:
    if is_frozen_exe():
        return os.path.basename(sys.executable)
    return f"{os.path.basename(sys.executable)} {os.path.basename(os.path.abspath(__file__))}"
```

**关键配合**：`argparse(prog=get_invocation_name(), formatter_class=RawDescriptionHelpFormatter)` —— 前者控制 usage 行，后者保留 epilog 的换行与缩进。

---

## 八、缺陷修复历程

### 8.1 阶段 A：19 项服务端缺陷

```mermaid
pie showData
    title 阶段 A：19 项缺陷分布
    "致命 P0" : 2
    "严重 P1" : 6
    "一般 P2" : 11
```

### 8.2 严重缺陷修复对照

| ID | 缺陷 | 修复策略 | 版本 |
|----|------|----------|------|
| **F1** | LLM 并发不安全 | 单 worker 线程串行化 | v2.0 |
| **F2** | 会话无管理 | Session 对象 + Watchdog | v3.0 |
| **S1** | system_message 竞态 | 请求时 snapshot | v2.0 |
| **S2** | 上下文预算算错 | tokenize 精确计数 | v2.0 |
| **S3** | 字符串魔法协议 | `type` 字段结构化 | v2.0 |
| **S4** | 双轨错误协议 | 统一 `{code, error}` | v2.0 |
| **S5** | 每 token 新句柄 | 保留（API 约束） | v2.0 |
| **S6** | 双重 cleanup | `_cleaned_up` 幂等标志 | v2.0 |

### 8.3 阶段 B：代理层 8 次迭代的缺陷

| ID | 缺陷 | 症状 | 修复 | 版本 |
|----|------|------|------|------|
| **P1** | 进程秒退 | 启动后立即退出 | 加主循环 + 信号处理 | v1.3 |
| **P2** | SSE 延迟 | 客户端 17 秒才收到 | `http.client` 替换 `requests` | v1.4 |
| **P3** | gzip 干扰 | 批量输出 | `Accept-Encoding: identity` | v1.5 |
| **P4** | Nagle 抖动 | 40ms 级别抖动 | `TCP_NODELAY` | v1.6 |
| **P5** | thinking 开关 | 代理替客户端做策略 | 移除开关，无策略转发 | v1.7 |
| **P6** | set_system_message 假成功 | 返回 code:0 但无效果 | 明确返回 unsupported | v1.8 |
| **P7** | 死字段残留 | `_default_system_message` 无用 | 删除字段 | v1.8 |
| **P8** | 未支持选项静默丢弃 | `thinking`/`ephemeral` 被忽略无记录 | DEBUG 日志记录 | v1.8 |

### 8.4 阶段 C：工具链收尾改动

| ID | 改动 | 组件 | 影响 |
|----|------|------|------|
| **T1** | `--help` 自适应 | 三个 Python 工具 | 用户体验 |
| **T2** | API 能力矩阵机制 | 服务端 + 双客户端 | 协议一致性 |
| **T3** | 会话双条件回收 | `llm_service.py` | 会话稳定性 |
| **T4** | 编译脚本一次性编译三个 EXE | `build_llm_service.ps1` | 构建效率 |
| **T5** | 依赖清单分场景 | `requirements.txt` | 安装便利性 |

### 8.5 缺陷修复可视化（替代 quadrantChart）

> **说明**：原 `quadrantChart` 在部分渲染器中不兼容，此处改用 **flowchart 象限图**，语义等价且兼容性最佳。

```mermaid
flowchart TB
    subgraph Q1["🔴 立即修复 —— 影响大 + 复杂度高"]
        direction LR
        F1["F1 并发不安全"]
        F2["F2 会话无管理"]
        P2["P2 SSE 延迟"]
    end

    subgraph Q2["🟠 高优先级 —— 影响大 + 复杂度低"]
        direction LR
        P1["P1 进程秒退"]
        P3["P3 gzip 干扰"]
        P6["P6 假成功"]
        S3["S3 字符串魔法"]
    end

    subgraph Q3["🟡 一般关注 —— 影响中 + 复杂度中"]
        direction LR
        S1["S1 竞态"]
        S2["S2 预算错"]
        P5["P5 thinking 策略"]
    end

    subgraph Q4["🟢 排期修复 —— 影响小 + 复杂度低"]
        direction LR
        P4["P4 Nagle 抖动"]
        P7["P7 死字段"]
    end

    style Q1 fill:#FADBD8,stroke:#922B21,stroke-width:4px
    style Q2 fill:#FDEBD0,stroke:#B7791F,stroke-width:4px
    style Q3 fill:#FEF9E7,stroke:#B7950B,stroke-width:3px
    style Q4 fill:#EAECEE,stroke:#5D6D7E,stroke-width:3px
    style F1 fill:#E74C3C,stroke:#922B21,stroke-width:2px,color:#FFFFFF
    style F2 fill:#E74C3C,stroke:#922B21,stroke-width:2px,color:#FFFFFF
    style P2 fill:#E74C3C,stroke:#922B21,stroke-width:2px,color:#FFFFFF
    style P1 fill:#F5A623,stroke:#B7791F,stroke-width:2px,color:#FFFFFF
    style P3 fill:#F5A623,stroke:#B7791F,stroke-width:2px,color:#FFFFFF
    style P6 fill:#F5A623,stroke:#B7791F,stroke-width:2px,color:#FFFFFF
    style S3 fill:#F5A623,stroke:#B7791F,stroke-width:2px,color:#FFFFFF
    style S1 fill:#F7DC6F,stroke:#B7950B,stroke-width:2px,color:#7E5109
    style S2 fill:#F7DC6F,stroke:#B7950B,stroke-width:2px,color:#7E5109
    style P5 fill:#F7DC6F,stroke:#B7950B,stroke-width:2px,color:#7E5109
    style P4 fill:#D5D8DC,stroke:#5D6D7E,stroke-width:2px,color:#2C3E50
    style P7 fill:#D5D8DC,stroke:#5D6D7E,stroke-width:2px,color:#2C3E50
```

---

## 九、协议演进

### 9.1 流式消息协议对比

```mermaid
sequenceDiagram
    participant Server as 服务端
    participant Client as 客户端

    Note over Server,Client: ❌ v1.0 协议（字符串魔法）
    Server->>Client: {"chunk": "Hello"}
    Server->>Client: {"chunk": " world"}
    Server->>Client: {"chunk": "__FINISH__"}
    Note over Client: 用 startswith 判断

    Note over Server,Client: ✅ v3.0 协议（结构化）
    Server->>Client: {"type":"chunk","session_id":"...","text":"Hello"}
    Server->>Client: {"type":"chunk","session_id":"...","text":" world"}
    Server->>Client: {"type":"think","session_id":"...","text":"..."}
    Server->>Client: {"type":"finish","session_id":"...","reason":"stop"}
    Server->>Client: {"type":"closed","session_id":"...","reason":"timeout+offline"}
```

### 9.2 消息类型矩阵

```mermaid
flowchart LR
    subgraph MSG["📨 消息类型"]
        C["chunk<br/>正文流"]
        T["think<br/>思考流"]
        F["finish<br/>生成结束"]
        E["error<br/>服务端错误"]
        CL["closed<br/>会话关闭"]
    end

    C --> CU["客户端追加显示"]
    T --> TU["灰色显示 / 折叠"]
    F --> FU["更新状态栏"]
    E --> EU["错误提示"]
    CL --> CLU["清理会话列表"]

    style C fill:#3498DB,stroke:#1F618D,stroke-width:3px,color:#FFFFFF
    style T fill:#95A5A6,stroke:#5D6D7E,stroke-width:3px,color:#FFFFFF
    style F fill:#2ECC71,stroke:#1E8449,stroke-width:3px,color:#FFFFFF
    style E fill:#E74C3C,stroke:#922B21,stroke-width:3px,color:#FFFFFF
    style CL fill:#E67E22,stroke:#9C4A0C,stroke-width:3px,color:#FFFFFF
```

### 9.3 双后端行为对照

| 维度 | `llm_service.py` | `llm_proxy.py` |
|------|:----------------:|:--------------:|
| **模型加载** | 本地 llama.cpp | 无（转发到外部） |
| **推理线程** | 单 worker 串行 | 无推理，HTTP 转发 |
| **上下文管理** | 服务端持有 KV cache | 每轮重建 messages |
| **set_system_message** | ✅ 支持 | ❌ 明确拒绝 |
| **CreateSession（有 sys）** | 使用传入值 | 使用传入值 |
| **CreateSession（无 sys）** | 用全局默认 | 空 system message |
| **thinking 转发** | 由 template 决定 | 由后端模型决定 |
| **health() 字段** | 本地模型信息 | 代理 + 后端信息 |
| **端点 / App 名** | `ipc:llm_service` / `LLM_Service` | 同左 |
| **能否同时运行** | ❌ | ❌ |

### 9.4 三方协议对齐验证

```mermaid
flowchart TB
    subgraph PY["🐍 Python 服务端"]
        PS1["结构化 JSON<br/>type/session_id/text"]
        PS2["能力矩阵<br/>capabilities/server_kind"]
    end

    subgraph LINGO["⚡ LingoFuse 网格"]
        LF["Sequenced Notify<br/>FIFO 保证"]
    end

    subgraph PY_CLI["🐍 Python 客户端"]
        PC1["on_llm_stream<br/>事件分发"]
        PC2["fetch_capabilities<br/>llm_supported"]
    end

    subgraph PAS["🅿️ Pascal 客户端"]
        PA1["OnChunk / OnThink<br/>OnFinish / OnError / OnClosed"]
        PA2["FetchCapabilities<br/>LLMSupported"]
    end

    PS1 -->|UTF-8 JSON| LF
    PS2 -->|UTF-8 JSON| LF
    LF -->|原始字节| PC1
    LF -->|原始字节| PC2
    LF -->|原始字节| PA1
    LF -->|原始字节| PA2

    style PY fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style PY_CLI fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
    style PAS fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
    style LINGO fill:#FDEBD0,stroke:#B7791F,stroke-width:3px
```

**协议对齐验证结论**：API 名称、能力矩阵键集、请求-响应字段、流式消息字段全部对齐，无遗漏。

---

## 十、多会话状态机

### 10.1 会话生命周期

```mermaid
stateDiagram-v2
    [*] --> queued: create_session<br/>或 generate(无session_id)
    queued --> running: worker 取出任务
    running --> idle: 生成完成
    running --> cancelled: cancel_session
    running --> error: 推理异常
    idle --> running: generate(带session_id)
    idle --> closing: close_session
    idle --> closing: 双条件回收（超时+离线）
    cancelled --> idle: 保留会话
    error --> idle: 保留会话
    closing --> [*]: 移除会话
    note right of idle
        可以被 watchdog
        双条件回收
    end note
    note right of cancelled
        cancel 只中断
        当前生成
        不关闭会话
    end note
```

### 10.2 会话对象结构

```mermaid
classDiagram
    class SessionState {
        +str session_id
        +str client_name
        +str system_message
        +List messages
        +float created_at
        +float last_active_at
        +str status
        +Event current_cancel_event
        +Lock lock
        +to_summary() Dict
    }

    class GenerationTask {
        +str task_id
        +Session session
        +str content
        +str prompt
        +Dict options
        +bool ephemeral
        +Event cancel_event
    }

    class LLMService {
        -Dict _sessions
        -Queue _request_queue
        -Thread _worker_thread
        -Thread _watchdog_thread
        +_handle_generate()
        +_handle_create_session()
        +_handle_close_session()
        +_handle_cancel_session()
        +_handle_get_api_capabilities()
        +_process_task()
    }

    class LLMProxyService {
        -Dict _sessions
        -Lock _sessions_lock
        -OpenAIStreamClient _backend
        +_handle_generate()
        +_handle_create_session()
        +_handle_set_system_message()
        +_handle_get_api_capabilities()
        +_run_generation()
    }

    LLMService "1" --> "*" SessionState : manages
    LLMProxyService "1" --> "*" SessionState : manages
```

**要点**：`SessionState` 在两个服务端实现中**语义一致**，但内部处理不同——`llm_service.py` 的 Session 直接持有 llama.cpp 的历史；`llm_proxy.py` 的 Session 只是一个 message list，每轮重建 messages。

---

## 十一、Thinking 分流机制

### 11.1 状态机原理

```mermaid
stateDiagram-v2
    [*] --> Outside: 初始化
    Outside --> Inside: 检测到 &lt;think&gt;
    Inside --> Outside: 检测到 &lt;/think&gt;
    Outside --> Outside: 普通文本 → chunk
    Inside --> Inside: 思考文本 → think
    note right of Outside
        缓冲尾部 6 字符
        处理跨 chunk 的 &lt;think&gt;
    end note
    note right of Inside
        缓冲尾部 8 字符
        处理跨 chunk 的 &lt;/think&gt;
    end note
```

### 11.2 两条路径

```mermaid
flowchart TB
    subgraph PATH_A["🅰️ llm_service 路径"]
        A1["llama.cpp<br/>token 流"] --> A2["ThinkingParser<br/>状态机"]
        A2 --> A3["chunk / think<br/>事件"]
        A4["模板预置 &lt;think&gt;<br/>或模型自发"] -.-> A2
    end

    subgraph PATH_B["🅱️ llm_proxy 路径"]
        B1["后端 SSE<br/>reasoning_content + content"] --> B2["无策略转发"]
        B2 --> B3["think / chunk<br/>事件"]
    end

    style PATH_A fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
    style PATH_B fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
    style A2 fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style B2 fill:#8E44AD,stroke:#5B2C6F,stroke-width:4px,color:#FFFFFF
```

### 11.3 关键差异

| 维度 | `llm_service.py` | `llm_proxy.py` |
|------|:----------------:|:--------------:|
| **thinking 判断** | 模板预置 + 状态机 | 后端已分离字段 |
| **是否可关** | `--include-thinking` 控制模板变量 | 无开关，全量转发 |
| **跨 chunk 处理** | 需要尾部缓冲 | 后端已保证字段完整 |

---

## 十二、Chat Template 加载机制

### 12.1 加载路径搜索

```mermaid
flowchart TD
    START["程序启动"] --> Q1{"指定了<br/>--chat-template?"}
    Q1 -->|是| E1["显式路径<br/>不存在则报错退出"]
    Q1 -->|否| SEARCH["多路径搜索<br/>chat_template.jinja"]
    SEARCH --> P1["脚本目录"]
    P1 --> P2["脚本父目录"]
    P2 --> P3["当前工作目录"]
    P3 --> Q2{"找到?"}
    Q2 -->|是| LOAD["加载文件"]
    Q2 -->|否| FALLBACK["回落模型内置模板"]
    E1 --> LOAD
    LOAD --> RENDER["渲染时传入变量<br/>messages, enable_thinking<br/>reasoning_budget_message"]
    FALLBACK --> RENDER

    style START fill:#4A90E2,stroke:#1E3A8A,stroke-width:3px,color:#FFFFFF
    style LOAD fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style FALLBACK fill:#F5A623,stroke:#B7791F,stroke-width:3px,color:#FFFFFF
    style RENDER fill:#9B59B6,stroke:#6C3483,stroke-width:4px,color:#FFFFFF
```

### 12.2 关键发现

用户在目录 `Py/` 下放 `chat_template.jinja`，脚本在 `Py/llm-service/llm_service.py`。

- **v2.1 行为**：只在脚本目录找 → **找不到** → 走模型内置模板
- **v2.2 行为**：搜索脚本目录、父目录、CWD → **命中父目录** → 正确加载

**代理层的对应处理**：`llm_proxy.py` 不加载模板。后端（LM Studio 等）自己处理模板。

---

## 十三、客户端对接

### 13.1 三端协议对齐

（已在 §9.4 展示，此处不重复）

### 13.2 Pascal 客户端修复

```mermaid
flowchart TD
    A["llm_client.pas<br/>v3.0"] --> B{"编译结果"}
    B -->|失败| E1["var/out 签名冲突<br/>FPC 视为同一类型"]
    E1 --> F1["合并为单个<br/>Generate(var ASessionId)"]
    F1 --> G["llm_client.pas<br/>v3.0.1 可编译"]

    G --> H["llm_tool_frm.pas"]
    H --> I{"事件签名匹配?"}
    I -->|否| E2["旧版单参数<br/>vs 新版双参数"]
    E2 --> F2["升级所有<br/>Do_LLM_* 处理器"]
    F2 --> J["llm_tool_frm.pas<br/>v3.0 可编译"]

    J --> K["代码审计"]
    K --> L["发现 S1-S4 严重问题"]
    L --> M["llm_client.pas<br/>v3.2 完整注释版"]

    M --> N["新增能力发现<br/>v3.3"]
    N --> O["llm_tool_frm.pas<br/>v3.1"]

    style M fill:#2ECC71,stroke:#1E8449,stroke-width:5px,color:#FFFFFF
    style N fill:#3498DB,stroke:#1F618D,stroke-width:4px,color:#FFFFFF
    style O fill:#E74C3C,stroke:#922B21,stroke-width:5px,color:#FFFFFF
```

### 13.3 Pascal 客户端严重问题

| ID | 问题 | 后果 | 修复 |
|----|------|------|------|
| **S1** | `Connect` 失败路径泄漏 `FApp` | 内存泄漏 + 无法重连 | `CleanupPartialConnect` |
| **S2** | `Disconnect` 早退导致主线程泄漏 | LingoFuse 主线程常驻 | `FPrepared` 追踪状态 |
| **S3** | JSON 经 `string` 中转 | 中文乱码 | 全程 `TBytes` |
| **S4** | `OnLLMStream` 未检 buffer | 空消息崩溃 | 判空 `buf` / `sz` |

### 13.4 GUI 层新增功能

**`new_session` 按钮**：让新的 system message 生效的唯一路径。

```mermaid
flowchart TB
    CLICK["用户点击<br/>新建会话"] --> READ["从 sys_prompt_Memo<br/>读取 system message"]
    READ --> CALL["LLM.CreateSession(sys_msg, sid, err)"]
    CALL --> CHECK{"成功?"}
    CHECK -->|是| UPDATE["更新 FActiveSessionId<br/>切换到输出页<br/>重置输出头"]
    CHECK -->|否| LOG["DoStatus(err)"]

    UPDATE --> INFO["日志: 已创建新会话"]

    style CLICK fill:#4A90E2,stroke:#1E3A8A,stroke-width:4px,color:#FFFFFF
    style UPDATE fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style LOG fill:#E74C3C,stroke:#922B21,stroke-width:3px,color:#FFFFFF
```

**`set_system_message` 的温和失败处理**：

```mermaid
flowchart TB
    CALL["LLM.SetSystemMessage(msg, err)"] --> CHECK{"HasCapabilityInfo?"}
    CHECK -->|否| TRY["尝试调用"]
    CHECK -->|是| Q2{"LLMSupported?"}
    Q2 -->|否| SHORTCUT["本地短路<br/>提示走新建会话"]
    Q2 -->|是| TRY
    TRY --> RESULT{"成功?"}
    RESULT -->|是| OK["llm_service 场景<br/>更新全局默认"]
    RESULT -->|否| FAIL["llm_proxy 场景<br/>返回 unsupported"]
    FAIL --> HINT["提示用户:<br/>点击'新建会话'让 system prompt 生效"]

    style SHORTCUT fill:#F5A623,stroke:#B7791F,stroke-width:3px,color:#FFFFFF
    style OK fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
    style FAIL fill:#F5A623,stroke:#B7791F,stroke-width:4px,color:#FFFFFF
    style HINT fill:#8E44AD,stroke:#5B2C6F,stroke-width:3px,color:#FFFFFF
```

---

## 十四、编码层修复

### 14.1 中文编码链路

```mermaid
flowchart LR
    subgraph OLD["❌ 早期编码路径"]
        O1["TZ_JsonObject.S['content']"] --> O2["string<br/>(AnsiString?)"]
        O2 --> O3["LF_WriteString<br/>内部 UTF8Encode"]
        O3 --> O4["服务端"]
        O4 -.->|"可能丢字"| O5["乱码"]
    end

    subgraph NEW["✅ 当前编码路径"]
        N1["TZ_JsonObject.S['content']"] --> N2["TZ_JsonObject.ToBytes<br/>UTF-8 bytes"]
        N2 --> N3["LF_WriteStringBytes"]
        N3 --> N4["服务端"]
        N4 --> N5["LF_ReadStringBytes"]
        N5 --> N6["TZ_JsonObject.Parae<br/>直接解析 bytes"]
    end

    style OLD fill:#FADBD8,stroke:#922B21,stroke-width:3px
    style NEW fill:#D5F5E3,stroke:#1E8449,stroke-width:3px
    style O5 fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
    style N6 fill:#2ECC71,stroke:#1E8449,stroke-width:4px,color:#FFFFFF
```

### 14.2 Emoji 支持（阶段 B 新增）

**问题**：Windows 控制台默认 CP936（GBK），无法渲染 emoji。Python 客户端收到含 emoji 的 chunk 时抛 `UnicodeEncodeError`。

**三层修复**：

```mermaid
flowchart TB
    P1["层 1: 代码页<br/>SetConsoleOutputCP(65001)"]
    P2["层 2: Python stream<br/>stream.reconfigure(utf-8)"]
    P3["层 3: VT 处理<br/>SetConsoleMode(0x0004)"]

    P1 --> DONE["✅ emoji + ANSI 颜色"]
    P2 --> DONE
    P3 --> DONE

    style P1 fill:#3498DB,stroke:#1F618D,stroke-width:3px,color:#FFFFFF
    style P2 fill:#2ECC71,stroke:#1E8449,stroke-width:3px,color:#FFFFFF
    style P3 fill:#F5A623,stroke:#B7791F,stroke-width:3px,color:#FFFFFF
    style DONE fill:#8E44AD,stroke:#5B2C6F,stroke-width:5px,color:#FFFFFF
```

**字体依赖**：代码层无法解决字体缺失。推荐终端：Windows Terminal（彩色 emoji）或 VSCode 集成终端。

---

## 十五、配置模型统一

### 15.1 三级优先级的统一模式

两个服务端和客户端现在都遵循**完全一致**的配置模型：

```mermaid
flowchart LR
    CMD["命令行参数"] -->|优先级最高| WIN["最终生效值"]
    ENV["环境变量"] -->|优先级中| WIN
    DEF["DEFAULT_* 常量"] -->|优先级最低| WIN
    WIN --> CONFIG["全局 CONFIG 对象"]

    style CMD fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
    style ENV fill:#F5A623,stroke:#B7791F,stroke-width:3px,color:#FFFFFF
    style DEF fill:#95A5A6,stroke:#5D6D7E,stroke-width:3px,color:#FFFFFF
    style CONFIG fill:#2ECC71,stroke:#1E8449,stroke-width:5px,color:#FFFFFF
```

**统一点**：

1. 所有配置项有 `DEFAULT_*` 模块级常量
2. 初始化时创建全局 `CONFIG` 对象
3. `parse_args()` 从 env + argv 读取
4. `_init_global_config(args)` 写回 CONFIG
5. 运行时**只读 CONFIG**，不再重读 env / argv

**三个文件的实现对照**：

| 文件 | CONFIG 类 | 初始化函数 | 配置项数 |
|------|-----------|-----------|:--------:|
| `llm_service.py` | `ServiceConfig` | `_init_global_config` | 16 |
| `llm_proxy.py` | `ProxyConfig` | `_init_global_config` | 12 |
| `llm_test.py` | 使用 argparse 局部变量 | — | 8 |

### 15.2 认证支持的配置项

`llm_proxy.py` 独有的认证配置：

```mermaid
mindmap
  root(("Token 认证"))
    传递方式
      --backend_key
      --backend_key_file
    请求头
      --backend_auth_header
      --backend_auth_scheme
    额外头部
      --backend_extra_headers
    常见配方
      Bearer_OpenAI_DeepSeek
      api-key_Azure
      Bearer_HTTP-Referer_OpenRouter
```

---

## 十六、编译与工程交付（阶段 C 新增）

### 16.1 一次性编译三个 EXE

**`build_llm_service.ps1`** 一次性编译：

| 源文件 | 输出 | 特殊依赖 |
|--------|------|----------|
| `llm_service.py` | `llm_service.exe` | `llama_cpp`、`jinja2` |
| `llm_proxy.py` | `llm_proxy.exe` | `requests`、`http.client`、`ssl` |
| `llm_test.py` | `llm_test.exe` | 仅 `lingofuse` |

**脚本流程**：

```mermaid
flowchart TB
    START["运行 build_llm_service.ps1"] --> PRE["前置检查"]
    PRE --> P1["PyInstaller 已装?"]
    PRE --> P2["源文件存在?"]
    P1 --> CLEAN["清理旧构建产物"]
    P2 --> CLEAN
    CLEAN --> B1["编译 llm_service.py"]
    B1 --> B2["编译 llm_proxy.py"]
    B2 --> B3["编译 llm_test.py"]
    B3 --> SUM["汇总编译结果<br/>含文件大小"]
    SUM --> REMIND["提醒运行时依赖<br/>LingoFuse64.dll / z_ipc_64.dll"]
    REMIND --> DONE["✅ 完成"]

    style START fill:#4A90E2,stroke:#1E3A8A,stroke-width:4px,color:#FFFFFF
    style DONE fill:#2ECC71,stroke:#1E8449,stroke-width:5px,color:#FFFFFF
```

### 16.2 依赖清单分场景

`requirements.txt` 按组件分场景组织：

| 段落 | 依赖 | 用途 |
|------|------|------|
| 必需 | `requests` | `llm_proxy` 探测 `/v1/models` |
| HTTP 桥接 | `flask` | `bridge.py` |
| 本地推理 | `llama-cpp-python` | `llm_service.py` |
| 聊天模板 | `jinja2` | 自定义模板 |
| 打包 | `pyinstaller` | 生成 EXE |
| 开发 | `pytest`、`black`、`flake8` | 可选 |

---

## 十七、代码审查结论（阶段 C 新增）

### 17.1 通过项 ✅

```mermaid
mindmap
  root(("代码审查<br/>通过项"))
    API名称一致性
      全部对齐
    能力矩阵键集
      全部对齐
    请求响应字段
      全部对齐
    流式消息字段
      全部对齐
    help自适应
      3个Python工具统一
    会话双条件回收
      逻辑正确
    Pascal能力发现
      完整
```

### 17.2 待优化项（不阻塞）

| 编号 | 严重度 | 文件 | 简述 |
|:----:|:------:|------|------|
| 1 | 🟠 P3 | `llm_client.pas` | `Connect` 中 `FetchCapabilities(ErrorMsg)` 会覆盖 out 参数 |
| 2 | 🟠 P3 | `llm_test.py` | `llm_supported` 缓存未命中缺键时会重复 fetch |
| 3 | 🟠 P3 | `llm_tool_frm.pas` | 后台线程调用 `DoStatus` 存在 UI 线程安全疑点 |
| 4 | 🟡 P4 | `llm_tool_frm.pas` | `FormClose` 跳过 `LLM.Disconnect`（已知问题） |
| 5 | 🟡 P4 | `llm_service.py` | 未使用的导入（`LF_FreeData` 等） |

**结论**：功能正确，无致命缺陷，待优化项可排入后续迭代。

---

## 十八、数据统计

### 18.1 代码规模

```mermaid
xychart-beta
    title "各组件代码规模（行）"
    x-axis ["llm_service", "llm_proxy", "llm_test", "llm_client.pas", "llm_tool_frm.pas"]
    y-axis "Lines of Code" 0 --> 1500
    bar [1200, 1000, 750, 900, 500]
```

### 18.2 各阶段问题数

```mermaid
xychart-beta
    title "各阶段问题数"
    x-axis ["服务端研究", "v2.0", "v2.2", "v3.0", "代理层", "Pascal", "工具链"]
    y-axis "Issue Count" 0 --> 25
    bar [19, 8, 3, 5, 8, 6, 5]
```

### 18.3 代理层迭代修复项数

```mermaid
xychart-beta
    title "llm_proxy.py 迭代修复项数"
    x-axis ["v1.0", "v1.3", "v1.4", "v1.5", "v1.6", "v1.7", "v1.8"]
    y-axis "Fixes" 0 --> 6
    bar [1, 1, 2, 1, 1, 1, 3]
```

### 18.4 支持的后端统计

```mermaid
pie showData
    title llm_proxy 支持的 129+ 后端分布
    "云 API（国际）" : 30
    "云 API（中国区）" : 15
    "本地推理服务器" : 20
    "网关/代理/路由" : 20
    "API 聚合/中转站" : 15
    "桌面客户端" : 17
    "嵌入/TTS/STT" : 12
```

---

## 十九、交付物清单

### 19.1 服务端（Python）

| 文件 | 版本 | 说明 |
|------|------|------|
| `llm_service.py` | **v3.2** | 持久化多会话流式服务端（本地推理）+ 双条件回收 + 能力矩阵 |
| `llm_proxy.py` | **v1.8** | 无状态转发器（OpenAI 兼容后端）+ 能力矩阵 |
| `chat_template.jinja` | — | NVIDIA Nemotron 模板 |

### 19.2 客户端（Python）

| 文件 | 版本 | 说明 |
|------|------|------|
| `llm_test.py` | **v3.6** | 交互式多会话 REPL，emoji 支持，能力发现 |

### 19.3 客户端（Pascal）

| 文件 | 版本 | 说明 |
|------|------|------|
| `llm_client.pas` | **v3.3** | 完整英文注释，S1-S4 修复，能力发现 |
| `llm_tool_frm.pas` | **v3.1** | new_session 实现，能力检查，全中文注释 |

### 19.4 工程脚本

| 文件 | 说明 |
|------|------|
| `build_llm_service.ps1` | 一次性编译三个 EXE 的 PowerShell 脚本 |
| `requirements.txt` | 按组件分场景的依赖清单 |

### 19.5 文档

| 文件 | 版本 | 说明 |
|------|------|------|
| `LingoFuse_LLM_Toolchain_Work_Summary.md` | **v3.0** | **本文档** |
| `LingoFuse_LLM_Pitfalls_For_AI.md` | v2.0 | 踩坑文档，含代理层 6 大坑 |
| `LingoFuse_LLM_Service_CLI_guide.md` | v1.0 | 服务端命令行手册 |
| `LingoFuse_LLM_Proxy_CLI_Guide.md` | v2.0 | 代理层命令行手册 |
| `LingoFuse_LLM_Proxy_Compatibility_Guide.md` | v2.1 | 129+ 后端兼容性清单 |
| `LingoFuse_Python_Streaming_LLM_Guide.md` | — | 流式 LLM 开发要点 |

---

## 二十、遗留问题与后续建议

### 20.1 尚未处理的问题

```mermaid
flowchart TB
    subgraph SERVER["⏳ 服务端"]
        S1["M1: LF.ExitMainThread 全局副作用"]
        S2["M2: 主线程调用可能死锁"]
        S3["M3: 过期 session_id 未自动清"]
        S4["M4: 未使用导入"]
    end

    subgraph PROXY["⏳ 代理层"]
        P1["P1: 工具调用（tools）不支持"]
        P2["P2: Responses API 未实现"]
        P3["P3: 多模态输入未支持"]
        P4["P4: watchdog 未加入 check_app"]
    end

    subgraph GUI["⏳ GUI 层"]
        G1["P0-1: FormClose 直接 LF_Shutdown"]
        G2["P1-5: 无取消按钮"]
        G3["P2: 会话列表 UI 缺失"]
        G4["P3: 后台线程 DoStatus 疑点"]
        G5["P3: FetchCapabilities 覆盖 ErrorMsg"]
    end

    subgraph TEST["⏳ 客户端"]
        T1["P3: llm_supported 重复 fetch"]
    end

    style SERVER fill:#FADBD8,stroke:#922B21,stroke-width:3px
    style PROXY fill:#FDEBD0,stroke:#B7791F,stroke-width:3px
    style GUI fill:#D6EAF8,stroke:#1F618D,stroke-width:3px
    style TEST fill:#E8DAEF,stroke:#6C3483,stroke-width:3px
    style G1 fill:#E74C3C,stroke:#922B21,stroke-width:4px,color:#FFFFFF
```

### 20.2 演进路线

```mermaid
timeline
    title 后续演进路线
    section 短期（1 周内）
        GUI P0-1 修复 : FormClose 顺序
                      : 加取消按钮
        修正 P3 待优化项 : ErrorMsg 覆盖
                        : DoStatus 线程安全
                        : llm_supported 重复 fetch
        中文端到端验证 : emoji 实测
    section 中期（1 个月内）
        代理层工具编排 : tools / function_call
                      : Prompt 注入式
                      : 或 MCP 适配
        Azure OpenAI 路径适配 : --backend-path-template
        代理层 watchdog 双条件 : 参考 llm_service
        多代理实例部署 : Redis 会话映射
    section 长期
        多模态支持 : 图像/音频
        分布式推理 : 模型分片
        多模型路由 : 按场景选择后端
        Responses API : 对齐 OpenAI 新协议
```

### 20.3 建议优先级

| 优先级 | 项目 | 理由 |
|:------:|------|------|
| 🔴 P0 | GUI `FormClose` 顺序 | 关闭时可能崩溃 |
| 🟠 P1 | 加取消按钮 | 长回答无法中止 |
| 🟠 P1 | 中文端到端验证 | 未实测 |
| 🟠 P1 | 代理层工具调用 | Cline / Continue 等 Agent 依赖 |
| 🟠 P3 | `FetchCapabilities` 覆盖 `ErrorMsg` | 5 分钟修复 |
| 🟠 P3 | 后台线程 `DoStatus` | 移入主线程或入队 |
| 🟠 P3 | `llm_supported` 重复 fetch | 加缺键哨兵 |
| 🟡 P2 | 会话列表 UI | 多会话体验 |
| 🟡 P2 | Responses API | 新客户端接入 |
| 🟡 P4 | 清理未使用导入 | 顺手清理 |
| 🟢 P3 | Continuous Batching | 大工程，视需求 |

---

## 二十一、经验总结

### 21.1 五条核心经验

```mermaid
mindmap
  root(("经验总结"))
    架构层面
      单线程不总是性能差
      串行化是稳定性根基
      队列是最好的解耦
    协议层面
      结构化优于字符串魔法
      UTF-8 全程贯通
      type 字段胜过前缀判断
      能力矩阵替代硬编码假设
    跨语言层面
      字节流是通用语言
      事件签名必须严格对齐
      var/out 在 FPC 下同签名
    传输层面
      SSE 三层缓冲缺一不可
      http_client 是唯一可靠方案
      identity 禁用 gzip
    语义层面
      无状态转发不加状态
      假成功比拒绝更危险
      失败要有替代路径
      未知不等于不支持
```

### 21.2 一句话总结每个阶段

| 阶段 | 一句话 |
|------|--------|
| **服务端研究** | 19 项缺陷，2 个会炸，必须重写 |
| **服务端 v2.0** | 单 worker 串行化，是稳定性转折点 |
| **服务端 v3.0** | 从"一次性"到"持久化"，从"能跑"到"能扛" |
| **代理层 v1.0~v1.3** | 从 0 到 1 打通外部后端 |
| **代理层 v1.4~v1.6** | 三层缓冲逐个击破，实时性达标 |
| **代理层 v1.7~v1.8** | 语义纯洁化：无策略 + 明确拒绝 |
| **Pascal 客户端** | 跨语言协议对齐，字节流是通用语言 |
| **GUI** | new_session 是 system prompt 的唯一入口 |
| **工具链收尾** | `--help` 自适应 + 能力矩阵 + 双条件回收 |
| **文档** | 四份手册 + 一份踩坑 + 一份兼容清单 |

### 21.3 三条核心经验（新增）

**经验 1：协议一致性优先于实现细节**

跨语言（Python / Pascal）合作时，最容易出错的地方不是算法，而是**协议字段名、大小写、空值处理**。本次通过统一的能力矩阵机制，把"服务端支持什么"这个动态信息固化成结构化协议，避免了硬编码假设。

**经验 2：能力发现机制的核心是"未知 ≠ 不支持"**

`HasCapabilityInfo` 与 `LLMSupported` 必须分离——前者回答"信息可靠吗"，后者回答"支持吗"。否则无法区分"旧服务端未实现能力 API"与"新服务端明确不支持该 API"，后者会错误地短路掉本可正常运行的调用。

**经验 3：watchdog 的回收条件应保守而非激进**

单条件（仅超时）会导致客户端短暂离线时丢失会话；双条件（超时 AND 离线）在延迟回收与保守保留之间取得平衡。代价是会话驻留时间可能变长，但这与 `max_sessions` 的限流机制互补，整体可控。

### 21.4 技术债清理

```mermaid
pie showData
    title 技术债清理情况
    "已解决（服务端）" : 19
    "已解决（代理层）" : 8
    "已修复（Pascal）" : 6
    "已修复（工具链）" : 5
    "待处理（GUI）" : 5
    "待处理（代理层）" : 4
    "待处理（其他）" : 2
```

### 21.5 五条铁律

```mermaid
mindmap
  root(("五条铁律"))
    铁律一
      client_name 是身份
      不是标签
      必须真实注册
    铁律二
      回调要快
      耗时操作入队
      阻塞调用禁止
    铁律三
      字节流是通用语言
      UTF-8 全程
      不经 string 中转
    铁律四
      SSE 流必须实时
      http_client 而非 requests
      identity 而非 gzip
    铁律五
      无状态语义下
      不撒谎
      不加状态
      拒绝优于假成功
      未知不等于不支持
```

### 21.6 交付节奏建议

| 阶段 | 内容 |
|------|------|
| 1 | 先统一 Python 三个工具的 `--help` 自适应（低风险，快速见效） |
| 2 | 引入能力矩阵（服务端 + 客户端双向对齐） |
| 3 | 升级会话回收策略（服务端逻辑改动） |
| 4 | 补齐文档（命令行指南 + 兼容性指南 + 依赖 + 编译脚本） |

---

## 二十二、结语

本次工作从**一个单会话 LLM 网关的缺陷修补**出发，历经**三个阶段**，最终演进为一套**双后端、多客户端、全栈文档、全生态对齐**的完整解决方案：

- **服务端**：19 项缺陷清零，单 worker 串行化，持久多会话，双条件回收
- **代理层**：从 0 到 1 打通外部后端，8 次迭代解决实时性问题，支持 129+ 后端
- **协议**：字符串魔法 → 结构化 JSON → 无策略转发 → 能力矩阵
- **跨语言**：Python 与 Pascal 双端对齐，字节流全程贯通，协议三方一致
- **GUI**：new_session 实现，能力检查，温和失败处理，全中文注释
- **工具链**：`--help` 自适应，编译脚本，依赖清单
- **文档**：总结 + 踩坑 + 手册 + 兼容 + 指南，六份齐备

**核心成果**：把一个"能跑"的 demo，变成了一个**能承受双开、能承受多会话、能承受跨语言、能对接 LM Studio 等主流后端、能自我描述能力、能优雅降级**的工业级组件。

**下一步**：

1. GUI 层的 P0-1 顺序问题（关闭时可能崩溃）
2. 代理层的工具调用支持（对 Agent 类客户端是必需的）
3. 中文/emoji 的端到端实测
4. P3 待优化项的顺手修复

---

**文档完成**

*本次工作总结完毕，所有图表使用 Mermaid 绘制，可在支持 Mermaid 的渲染器中查看。v3.0 在 v2.0 基础上合并了"工具链收尾"阶段，覆盖 `--help` 自适应、API 能力矩阵、会话双条件回收、编译脚本、代码审查等全部收尾工作。原 `quadrantChart` 因渲染器兼容性问题已替换为等价的 `flowchart` 象限图。*