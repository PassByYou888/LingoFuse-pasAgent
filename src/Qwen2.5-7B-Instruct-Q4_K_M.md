# Qwen2.5-7B-Instruct-Q4_K_M 模型下载与部署指南

---

## 一、模型简介

`Qwen2.5-7B-Instruct-Q4_K_M.gguf` 是通义千问 2.5（Qwen2.5）系列 7B 参数模型的 **4-bit 量化（Q4_K_M）GGUF 格式**版本。该模型专为指令遵循与对话场景优化，在**智能体（Agent）任务**和**多轮对话**中均有良好表现。其上下文长度支持 **32,768 tokens**，可生成最长 **8,192 tokens** 的回复。

**Q4_K_M 量化**在模型大小与推理质量间取得了较好的平衡，文件大小约 **4.7 GB**，适合在 **8GB 显存/内存**的硬件上流畅运行。

---

## 二、下载指南

### 方式一：Hugging Face 官方源

这是最权威的下载渠道，模型由通义千问官方账号发布。

*   **模型主页**：[Qwen/Qwen2.5-7B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF)
*   **直接下载链接**：
    ```
    https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf
    ```

**使用 `huggingface-cli` 下载（推荐）**：
```bash
# 安装 huggingface-hub
pip install -U huggingface_hub

# 仅下载 Q4_K_M 版本
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
    --include "qwen2.5-7b-instruct-q4_k_m*.gguf" \
    --local-dir . \
    --local-dir-use-symlinks False
```

### 方式二：hf-mirror 国内镜像站

若官方源下载缓慢，可使用 Hugging Face 国内镜像站 `hf-mirror.com`。

1.  访问 [hf-mirror.com](https://hf-mirror.com)
2.  搜索 **`Qwen2.5-7B-Instruct-GGUF`**
3.  找到并下载 `qwen2.5-7b-instruct-q4_k_m.gguf` 文件

> **提示**：镜像站也支持 `huggingface-cli`，只需将环境变量指向镜像即可：
> ```bash
> export HF_ENDPOINT=https://hf-mirror.com
> huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
>     --include "qwen2.5-7b-instruct-q4_k_m*.gguf" \
>     --local-dir .
> ```

### 方式三：ModelScope 魔搭社区

国内开发者还可通过阿里系平台 ModelScope 获取模型。

*   **模型主页**：[modelscope.cn/models/qwen/Qwen2.5-7B-Instruct-gguf](https://modelscope.cn/models/qwen/Qwen2.5-7B-Instruct-gguf)

**使用 `modelscope` 库下载**：
```bash
pip install modelscope
```

```python
from modelscope.hub.snapshot_download import snapshot_download

model_dir = snapshot_download('qwen/Qwen2.5-7B-Instruct-gguf', 
                              cache_dir='./models',
                              revision='master')
```

下载后，模型文件位于 `./models/qwen/Qwen2.5-7B-Instruct-gguf/` 目录下，您需将其中的 `qwen2.5-7b-instruct-q4_k_m.gguf` 复制到目标目录。

---

## 三、部署说明（针对 LingoFuse LLM 服务）

### 3.1 文件放置要求

下载完成后，请将 `qwen2.5-7b-instruct-q4_k_m.gguf` 文件放置于 **`llm_service_*.exe` 同目录**下（例如 `llm_service_cpu.exe`、`llm_service_cu124.exe` 或 `llm_service_vulkan.exe` 所在的文件夹）。

**重要**：文件名必须严格匹配 **`qwen2.5-7b-instruct-q4_k_m.gguf`**（大小写敏感，请勿重命名）。若您下载的文件名不同（例如包含额外后缀），请重命名为该标准名称。

### 3.2 自动加载机制

`llm_service_*.exe` 启动时会**自动扫描**同目录下的模型文件，优先加载名为 `qwen2.5-7b-instruct-q4_k_m.gguf` 的模型。若未找到该文件，服务将报错并退出，因此请确保文件存在且完整。

### 3.3 使用方式

启动 `llm_service_*.exe` 后，它将作为一个 LingoFuse 服务注册到服务网格中（默认端点 `ipc:llm_service`）。此时，您可以通过 LingoFuse 客户端调用该服务提供的 **`generate`** 和 **`set_system_message`** 等 API 进行对话或生成任务。

**配套工具**：`pascal_decl_to_mcp.exe` 可生成对应的 MCP 工具声明，方便将 LLM 能力集成到 MCP 智能体客户端中。您可使用该工具生成工具定义，并通过 `register_agent` 注册到后端，使 MCP Server 能够将其暴露给豆包等客户端。

---

## 四、模型适用场景

### ✅ 智能体（Agent）任务

Qwen2.5 系列在**指令遵循**和**结构化输出**（如 JSON）方面有显著增强。这使得它非常适合作为智能体的“大脑”，能够：
- 理解复杂的多步指令
- 以结构化格式（如 JSON）输出工具调用参数
- 处理函数调用（Function Calling）场景

### ✅ 简单对话工具

该模型原生支持**多语言**（包括中文、英文等 29 种语言），且对系统提示（System Prompt）的多样性更具韧性，便于实现角色扮演和聊天机器人的条件设定。

配合 LingoFuse LLM 服务（`llm_service_*.exe`），可在本地快速搭建一个**开箱即用的对话服务**，并通过 LingoFuse 服务网格供其他应用调用。

---

## 五、总结

| 下载源 | 地址 / 命令 | 适用场景 |
|--------|-------------|----------|
| **Hugging Face（官方）** | `huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF --include "qwen2.5-7b-instruct-q4_k_m*.gguf" --local-dir .` | 全球用户，追求最新版本 |
| **hf-mirror（镜像）** | 访问 [hf-mirror.com](https://hf-mirror.com) 搜索 `Qwen2.5-7B-Instruct-GGUF` | 国内用户，加速下载 |
| **ModelScope（魔搭）** | `snapshot_download('qwen/Qwen2.5-7B-Instruct-gguf', cache_dir='./models')` | 国内用户，阿里云生态 |

**关键部署要点**：
- 模型文件约 **4.7 GB**，下载后**必须**与 `llm_service_*.exe` 放在同一目录。
- 文件名固定为 `qwen2.5-7b-instruct-q4_k_m.gguf`，请勿更改。
- `llm_service_*.exe` 启动后自动加载该模型，并提供标准 LingoFuse API。
- `pascal_decl_to_mcp.exe` 可生成工具声明，便于集成到 MCP 智能体系统。

---