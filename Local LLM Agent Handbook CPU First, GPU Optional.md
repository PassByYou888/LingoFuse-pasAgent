# Local LLM & Agent Handbook: CPU First, GPU Optional

> 硬件不是门槛，认知才是。这篇手册帮你绕开 GPU 焦虑，直通本地智能体实战。

---

## 0. 工具声明：本文档不绑定 LM Studio

LM Studio 确实是新手最友好的图形化工具——**开箱即用、一键启动 API、内置模型搜索**，对刚接触量化模型的人来说极其友好。

但你必须清楚它的局限：

- **闭源软件**：你无法修改其推理逻辑，也无法深度集成到生产项目。
- **版本更新容易踩坑**：新版本可能变更 GGUF 的解析方式、修改 tokenizer 行为，或引入偶发的 `tool_calls` 解析 bug，导致原本正常工作的智能体突然失灵。
- **调试困难**：出错时你只能看界面报错，无法介入底层日志或调整 `llama.cpp` 的编译参数。

> **建议定位**：把 LM Studio 当作 **“驾校教练车”** —— 上手快，帮你理解「模型加载 → 对话 → API 调用」全流程。一旦你跑通了第一个智能体 demo，就应果断向专业工具迁移。

**可自由选择的替代工具（按学习曲线排序）：**

| 工具 | 开源 | 适用阶段 | 特点 |
|------|------|---------|------|
| **LM Studio** | ❌ | 新手入门（0~3天） | 图形化，零配置 |
| **Ollama** | ✅ | 入门→进阶 | 命令行友好，社区模型丰富，API 兼容 OpenAI |
| **llama.cpp 原生** | ✅ | 进阶/生产 | 纯 C++，性能最优，无依赖，可嵌入服务 |
| **llama-cpp-python** | ✅ | 进阶/开发 | Python 绑定，便于二次开发和工具解析 |
| **Text Generation WebUI (oobabooga)** | ✅ | 进阶 | 功能全面，支持多种后端，适合折腾 |
| **KoboldCPP** | ✅ | 进阶 | 专精文本生成，API 稳定 |

**核心原则**：本文档所有原理和代码示例，在上述任意工具上均可复用。我们讲的是**底层逻辑**，不是某个软件的说明书。

---

## 1. 核心引擎：llama.cpp 统一底层

无论你用 LM Studio、Ollama 还是原生命令行，它们底层大概率都依赖 **llama.cpp**（或其衍生）。

- llama.cpp 针对 CPU 做了极致优化（AVX2/AVX512/ARM NEON），让普通笔记本电脑也能流畅推理。
- 它支持 **GGUF 量化格式**，将 7B 模型从 14GB 压缩到 4GB 左右，同时保留足够的功能调用能力。

**所以，你学到的知识是跨平台、跨工具的，永远不会被某个闭源软件绑架。**

---

## 2. 硬件真相：GPU 是奢侈品，CPU 是必需品

| 硬件场景 | 能否运行 7B~8B 模型（Q4_K_M） | 典型速度（tok/s） | 体验评价 |
|---------|-------------------------------|-------------------|---------|
| 现代 CPU（i5-12代+） | ✅ 流畅 | 10~14 | 对话无感，智能体实时响应 |
| 中端 CPU（i7-6700） | ✅ 可行 | 5~8 | 略有停顿，但完全可用 |
| 老旧 CPU（i5-4代） | ✅ 勉强（选 3B 模型） | 3~5 | 适合简单工具调用 |
| 入门独显（GTX 1060） | 可 offload 加速，但非必须 | 15~20 | 锦上添花 |
| 无独显的云主机 | ✅ 纯 CPU 跑 | 取决于核心数 | 适合 7x24 小时服务 |

**划重点**：只要你的 CPU 支持 AVX2（Intel Haswell 2013 年后 / AMD Excavator 2015 年后），就能跑。**你不欠显卡一张门票。**

---

## 3. 模型虽“笨”，但做智能体绰绰有余

### 3.1 推荐的低配“够用”模型

- **Phi-3.5-mini-instruct (3.8B)** — 微软出品，工具调用精准，体积小
- **Qwen2.5-7B-Instruct** — 阿里出品，中文友好，指令遵循强
- **Llama-3.2-3B-Instruct** — Meta 出品，轻量级首选

以上模型均采用 **Q4_K_M 量化**，文件大小约 2.5GB ~ 4.5GB。

### 3.2 为什么“不够聪明”也能当智能体？

因为这些模型在微调阶段已经见过大量 **JSON 格式的工具调用示例**。它们不需要多高的智商，只需要学会：

> 看到用户问“北京天气” → 输出 `{"name": "get_weather", "arguments": {"city": "北京"}}`

这是**模式匹配**，不是深度推理。3B 模型完全胜任，且准确率可达 85%~95%。

---

## 4. 智能体核心：就是工具 API，别被概念忽悠

市面上把智能体包装得神乎其神，什么“自主规划”、“多轮反思”、“记忆网络”…… 对新手都是噪音。

**从工程实现看，智能体只有三个步骤：**

1.  **定义工具**：把 API 的名称、参数、描述塞进 System Prompt 或 `tools` 参数里。
2.  **模型选择**：模型根据用户输入，决定调哪个工具（输出结构化 JSON）。
3.  **执行与回填**：你的代码执行该 API，把结果还给模型，模型生成最终自然语言回复。

Prompt 模板、上下文窗口、思维链 都是**锦上添花**，不是雪中送炭。先跑通裸奔的“工具调用循环”，再谈优化。

---

## 5. 线上 API vs 离线 API：接口一样，灵魂不同

**接口层面完全等价**（OpenAI 兼容格式）：

```python
# 无论是 线上 GPT-4 还是 本地 LM Studio/Ollama/llama.cpp
client = OpenAI(
    base_url="https://api.openai.com/v1"  # 或 "http://localhost:11434/v1"
)
```

**选择策略：**

| 场景 | 推荐用 | 原因 |
|------|--------|------|
| 日常办公自动化（内部系统） | **离线本地** | 数据不出内网，隐私安全 |
| 复杂代码生成 / 长文写作 | **线上 API** | 本地小模型容易胡言乱语 |
| 物联网 / 边缘设备控制 | **离线本地** | 断网可用，低延迟 |
| 批量数据处理（成本敏感） | **离线本地** | 电费远低于 API 计费 |

**实用主义做法**：用本地模型做“工具调度员”，只在必要时（如遇到无法回答的复杂问题）才通过代码转手调用线上 API——不过大多数场景根本不需要这一步。

---

## 6. 新手期用 LM Studio，成长期务必“下车”

### 6.1 LM Studio 的使命
- 让你 10 分钟内体验「下载模型 → 加载 → 开启 API → Python 调用」全流程。
- 帮你直观理解量化等级（Q4、Q5、Q8）对速度和回复质量的影响。

### 6.2 为什么要“下车”并转向专业工具？
- **bug 不可控**：曾有版本更新后，模型输出的 `tool_calls` 字段结构变动，导致下游解析崩溃，而你只能等官方修复。
- **性能天花板**：LM Studio 的并发能力和批处理调度远不如原生 `llama.cpp` 的 `llama-server`。
- **黑盒风险**：生产级智能体需要精确控制 `seed`、`repeat_penalty`、`mirostat` 等采样参数，LM Studio 暴露的选项有限。

### 6.3 转型路线图建议
1. **第 1 天**：LM Studio 跑通第一个 `get_weather` 智能体。
2. **第 3 天**：卸载 LM Studio，安装 **Ollama**（`ollama run qwen2.5:7b`），用同样的 OpenAI SDK 代码无缝切换。
3. **第 7 天**：放弃 Ollama 的 REST API，改用 **llama-cpp-python** 直接加载模型，在 Python 内部完成 `tool_calls` 解析和工具调度，丢掉网络开销。
4. **第 30 天**：编译原生 `llama.cpp` 的 `llama-server`，配合 Nginx 做负载均衡，部署为稳定的内网智能体服务。

---

## 7. 通用代码示例（兼容所有工具）

只要你的本地工具提供了 OpenAI 兼容的 `/v1/chat/completions` 端点，下面这段代码**通吃** LM Studio、Ollama、llama-server：

```python
import json
import openai

# 换 base_url 就能切换工具
client = openai.OpenAI(
    base_url="http://127.0.0.1:1234/v1",  # LM Studio 默认
    # base_url="http://127.0.0.1:11434/v1", # Ollama 默认
    api_key="dummy"
)

def get_weather(city: str) -> str:
    return f"{city}，晴天，25°C"  # 模拟 API

tools = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "查询城市天气",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string"}},
            "required": ["city"]
        }
    }
}]

# 第一轮：用户提问
resp = client.chat.completions.create(
    model="local-model",
    messages=[{"role": "user", "content": "上海天气如何？"}],
    tools=tools,
    tool_choice="auto"
)

msg = resp.choices[0].message

# 判断是否发起工具调用
if msg.tool_calls:
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        result = get_weather(**args)
        
        # 第二轮：回填结果
        final = client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "user", "content": "上海天气如何？"},
                msg,
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result
                }
            ]
        )
        print(final.choices[0].message.content)
```

**关键点**：换工具只需改 `base_url`，业务逻辑零改动。这就是我们强调“不绑定工具”的原因。

---

## 8. 常见踩坑避雷针

| 坑 | 解决办法 |
|----|---------|
| LM Studio 更新后不识别旧模型 | 重新下载该模型的 GGUF 最新版，或换 Ollama |
| 模型不输出 tool_calls，只输出解释文字 | 换 `Qwen` 或 `Phi-3.5` 系列，中文模型指令遵循更稳 |
| CPU 跑起来风扇狂转 | 限制 `threads` 数量（如设为物理核心数的一半），牺牲速度保温度 |
| 量化模型回答胡言乱语 | 升级到 Q5_K_M 或 Q6_K，体积增加不多，智商提升明显 |
| API 返回 “tool_calls” 为空 | 检查 System Prompt 是否覆盖了工具描述，部分模型依赖 System 而非 `tools` 参数 |

---

## 9. 最终结论

- **硬件**：有 CPU 就能起步，GPU 只是加速器，不是入场券。
- **工具**：LM Studio 是最好的启蒙老师，但记住它只是过渡品。真正的生产级智能体，永远跑在开源原生引擎上。
- **智能体本质**：模型 + API 描述 + 循环执行，代码不超过 50 行。
- **心态**：别被“显存不足”吓倒，别被“智能体”概念唬住。今晚就动手，用你手头的办公电脑，跑起第一个会查天气、会读 RSS、会发邮件的本地机器人。

**专业智能体之路，始于 CPU 上的第一个 JSON 输出。**
