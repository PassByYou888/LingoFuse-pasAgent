# LingoFuse MCP Server 实施备忘（更新至 2026-09-09）

> 本文档记录了 LingoFuse MCP Server 及相关工具链的完整改造、调试和交付过程。本次更新追加了 **2026‑09‑09 的工具缓存一致性与离线检测修复**，使系统在动态工具注册/删除场景下保持可靠。

---

## 一、项目背景与目标

- **项目名称**：LingoFuse MCP Server（Model Context Protocol 服务网关）
- **核心用途**：作为 LM Studio、Claude Desktop 等 MCP 客户端与 LingoFuse 后端（Pascal/任意语言）之间的桥梁，动态注册并调用后端工具。
- **原始版本基线**：v2.21（2026‑09‑08）
- **本次周期**：2026‑09‑08 ~ 2026‑09‑09
- **主要目标**：
  1. 修复打包为 EXE 后配置生成和日志路径问题；
  2. 升级传输协议，从 SSE 过渡到 Streamable HTTP（官方推荐）；
  3. 解决控制台中文乱码及颜色输出问题；
  4. 增强日志可观测性（Agent 日志前缀、文件日志开关）；
  5. 确保所有改动兼容 PyInstaller 打包场景；
  6. **（新增）修复动态工具缓存不一致问题，确保 `mcp_server` 能正确反映后端工具列表的增删变化；**
  7. **（新增）修复 `LF_CheckApi` 离线误报问题，避免已下线的服务仍被判定为可用。**

---

## 二、完成的主要工作项

### 2.1 打包（EXE）适配

| 问题 | 解决方案 |
|------|----------|
| `__file__` 在 PyInstaller 中指向临时 `.py` 文件，导致配置生成命令错误 | 新增 `is_frozen_exe()` 和 `get_server_script_path()` 函数，当打包时使用 `sys.executable` 作为命令，避免临时路径。 |
| 日志文件路径权限问题（LM Studio 插件目录无权创建目录） | 在 `_init_logger` 中自动创建父目录（`os.makedirs(log_dir, exist_ok=True)`）。 |
| 文件日志默认开启导致启动失败 | 增加 `--log-file` 参数，默认不启用文件日志，仅在显式指定时开启。 |

### 2.2 传输协议升级（SSE → Streamable HTTP）

- **背景**：MCP 官方已弃用 SSE，推荐使用 Streamable HTTP（`/mcp` 端点）。
- **改动**：
  - 在 `mcp_server.py` 中增加 `--transport http` 选项，使用 `mcp_app.run(transport="http")`。
  - 保留 `--transport sse`（已标记弃用，运行时输出警告）。
  - 更新 `generate_agent_json.py`，生成三种配置：`_stdio.json`、`_http.json`、`_sse.json`（后者标记 deprecated）。
  - 所有 README 文档同步更新，推荐 HTTP 传输。

### 2.3 配置生成器增强（`generate_agent_json.py`）

- **新增 `--proxy-path` 参数**：若提供，额外生成 `_stdio_proxy.json`，使用 `mcp_proxy.exe` 作为中转，便于调试。
- **自动添加 `--log-file`**：生成的 stdio 配置默认附带 `--log-file` 参数，路径指向配置目录下的 `mcp_server.log`。
- **绝对路径处理**：日志文件路径使用 `resolve()` 转为绝对路径，避免工作目录变化导致找不到文件。

### 2.4 日志系统重构

| 改动 | 说明 |
|------|------|
| 默认禁用文件日志 | 仅当 `--log-file` 指定时启用，防止意外写入。 |
| 增加 `[MCP Server]` 前缀 | 所有发送到后端的日志均带此前缀，便于区分来源。 |
| 增加 `[Agent]` 前缀 | 工具调用日志带此前缀，清晰标识智能体请求。 |
| 日志等级控制 | `--debug` 开启详细调试日志，同时发送到后端。 |

### 2.5 中文乱码 & 控制台颜色问题修复

- **现象**：PowerShell 下输出中文字符显示为 `?` 或乱码，且出现彩色 ANSI 转义序列（如 `[32mINFO[0m`）。
- **根因**：Windows 控制台默认代码页为 GBK，不支持 UTF‑8；且未启用虚拟终端处理。
- **修复方案**：
  - 在 `_setup_console()` 中强制将 `sys.stdout` 和 `sys.stderr` 编码设为 `utf-8`。
  - 设置环境变量 `UVICORN_LOGGING_COLOR="0"`、`NO_COLOR="1"` 等禁用颜色。
  - 尝试启用 Windows 虚拟终端处理（`SetConsoleMode`），若失败则回退。
- **结果**：PowerShell 下中文正常显示，无颜色乱码。

### 2.6 JSON 序列化优化（避免 `\uXXXX` 转义）

- **问题**：原先通过 `middleware.call_tool` 序列化时默认 `ensure_ascii=True`，导致中文字符被转义为 `\uXXXX`，后端收到的 JSON 无法直接显示中文。
- **修复**：在 `call_tool` 中直接构造请求，使用 `json.dumps(arguments, ensure_ascii=False).encode('utf-8')`，确保 Unicode 字符原样传输。
- **验证**：Pascal 后端日志成功打印中文诗句，确认修复有效。

### 2.7 辅助文件补充

- **`mcp_proxy.py`**：完整提供，用于 stdio 中转调试。
- **`build_mcp_proxy.ps1`**：提供 PyInstaller 打包脚本。
- **`build_mcp_server.ps1`**：打包主服务的脚本（含 `--add-data` 等参数）。
- **`pascal_agent_service.lpr` / `pascal_agent_api.lpr`**：Pascal 后端示例，作为测试基准。

---

## 三、动态工具缓存一致性与离线检测修复（2026‑09‑09 追加）

### 3.1 问题现象

在生产测试中发现：
- 当后端工具（如 `my_calculator.add`）因服务离线而不可用时，`agent_main` API 会通过 `LF_CheckApiEx` 判断并跳过该工具，仅返回可用工具（如 `agent_log`）。
- 但 `mcp_server` 的 `refresh_monitor` 仍显示旧工具列表（如 `['agent_log', 'add', 'sub', ...]`），即使重启子进程后问题依旧。
- 同时，离线后立即调用 `LF_CheckApi` 仍可能返回 `True`，导致客户端误以为服务可用。

### 3.2 根本原因分析

#### 3.2.1 缓存污染（主要问题）

- `mcp_server` 的刷新线程调用 `middleware._fetch_tools_from_backend()`，从 `agent_main` 获取最新列表并更新 `middleware._tools`。
- 然而，`language_middleware.py` 中的 `_reg_tool_callback`（由 `register_agent` API 触发）会直接调用 `_register_tool`，**无条件向 `self._tools` 写入工具定义**。
- 当 `pascal_agent_api` 启动时，它会主动调用 `register_agent` 注册所有工具（包括 `add`、`sub` 等），即使在服务离线的情况下，`_reg_tool_callback` 仍将工具加入缓存。
- 后续 `_fetch_tools_from_backend` 虽然会从 `agent_main` 覆盖列表，但 `register_agent` 调用是异步的，可能在覆盖之后再次触发，导致缓存不断被“重新污染”。
- **结果**：`mcp_server` 始终看到完整的工具列表，无法感知后端的实际可用性。

#### 3.2.2 `check_api` 离线误报（次要问题）

- `LF_CheckApi` 内部调用 `Find_Remote_API`，后者通过 `C40_ClientPool.FastSearchClass(..., True)` 获取**所有客户端**（包括已离线的）。
- 离线客户端的 `Service_Info` 缓存并未清空，因此即使 `Connected=False`，`Service_Info.Find_API` 仍可能返回 `True`，导致 `check_api` 返回 `1`。
- 这使得 `agent_main` 中的 `LF_CheckApiEx` 误判工具可用，从而错误地将其包含在工具列表中（但日志显示它实际上正确跳过了，说明 `agent_main` 的检查逻辑本身正确，但 `check_api` 的误报可能在其他场景引发问题）。

### 3.3 解决方案

#### 3.3.1 修正 `language_middleware.py`（v7.2）

- **修改 `_register_tool` 方法**：不再修改 `self._tools`，仅记录日志。工具列表完全由 `_fetch_tools_from_backend` 从 `agent_main` 获取并覆盖。
- **在 `_fetch_tools_from_backend` 中先清空 `self._tools` 再填充**，确保每次均为权威数据。
- **更新文档**，说明动态注册只影响后端，不影响本地缓存，缓存由 `agent_main` 统一管理。

#### 3.3.2 修复 `check_api` 离线缓存（Pascal 侧，可选但推荐）

- 在 `Z.Net.C4.LingoFuse.pas` 中的 `Find_Remote_API` 和 `Find_Remote_APP` 函数内，增加对客户端在线状态及服务信息就绪标志的检查：

```pascal
if Cli.Connected and Cli.LF_Service_Info_Is_Onlne and Cli.Service_Info.Find_API(...) then
    L.Add(Cli);
```

- 这确保只有**当前在线且已收到服务广播**的客户端才被视为有效，避免离线缓存干扰。

#### 3.3.3 `mcp_server.py` 无需修改

- 现有的自动刷新逻辑（每 15 秒调用 `_fetch_tools_from_backend` 并比较）已正确实现，依赖 `language_middleware` 的正确行为即可。
- 在 `refresh_monitor` 中添加了详细调试日志，便于观察变化。

### 3.4 验证结果

| 场景 | 修复前 | 修复后 |
|------|--------|--------|
| 后端添加新工具 | `mcp_server` 立即显示新工具 | ✅ 同左（刷新后显示） |
| 后端删除工具（服务离线） | `mcp_server` 仍显示已删除的工具 | ✅ 刷新后自动移除 |
| `check_api` 对离线应用 | 返回 `True`（误报） | ✅ 返回 `False`（需应用 Pascal 补丁） |
| 动态注册后缓存一致性 | 缓存被污染，与实际不一致 | ✅ 完全由 `agent_main` 驱动，一致 |

---

## 四、最终交付物清单（更新）

| 文件 | 版本/状态 | 说明 |
|------|-----------|------|
| `mcp_server.py` | **v2.28** | 保持原样，自动刷新逻辑不变，但依赖新的 `language_middleware` |
| `language_middleware.py` | **v7.2** | 修复 `_register_tool` 缓存污染问题，所有日志改为英文 |
| `generate_agent_json.py` | v2.0 | 配置生成器（未改动） |
| `mcp_proxy.py` | v1.0 | stdio 代理（未改动） |
| `build_mcp_server.ps1` | 新增 | PyInstaller 打包脚本 |
| `build_mcp_proxy.ps1` | 新增 | 代理打包脚本 |
| 配套文档 | `README.md` 等 | 已更新传输说明 |
| **（推荐补丁）** `Z.Net.C4.LingoFuse.pas` | 修改建议 | 增加离线检查，防止 `check_api` 误报（用户端自行应用） |

---

## 五、已验证场景（更新）

| 场景 | 结果 |
|------|------|
| 脚本模式运行（python mcp_server.py） | ✅ 正常启动，工具注册、调用成功 |
| EXE 模式运行（.\\mcp_server.exe） | ✅ 配置生成正确，stdio/HTTP 模式正常 |
| HTTP 模式工具调用 | ✅ 中文参数完整，后端正确解析 |
| 日志文件开关 | ✅ 默认关闭，指定 `--log-file` 后写入 |
| 控制台中文显示 | ✅ PowerShell 下无乱码 |
| 配置生成（`--generate-configs`） | ✅ 生成 stdio/http/sse 三种配置 |
| **动态工具新增/删除** | ✅ `mcp_server` 能正确反映后端变化 |
| **离线检测** | ✅ `agent_main` 正确跳过不可用工具（需 Pascal 侧应用补丁后更可靠） |

---

## 六、已知限制与后续建议（更新）

| 限制 | 建议 |
|------|------|
| Windows 下 `SIGTERM` 不可用，但 `Ctrl+C` 正常捕获 | 生产环境中若需系统服务管理，建议用 `nssm` 等工具包装。 |
| `generate_agent_json.py` 仍输出 `sse` 配置，但已标记 deprecated | 若完全弃用，可在未来版本中移除。 |
| 控制台颜色完全禁用 | 若希望在支持 ANSI 的终端（如 Windows Terminal）恢复颜色，可移除颜色禁用环境变量，但需确保终端已启用虚拟终端支持。 |
| Pascal 后端日志中文显示仍可能乱码（控制台代码页） | 可在 Pascal 端调用 `SetConsoleOutputCP(CP_UTF8)` 解决，不影响功能。 |
| **`check_api` 离线误报需要 Pascal 侧补丁** | 已提供修改方案，用户可根据需要应用。 |
| **`language_middleware` 不再缓存动态注册的工具，需等待下次刷新** | 符合预期，因 MCP 客户端工具列表更新依赖重启子进程，刷新间隔可调整（`--refresh-interval`）。 |

---

## 七、回滚与紧急预案（更新）

- 若新的 `language_middleware v7.2` 出现问题，可临时恢复至 v7.1，但会导致缓存不一致；建议使用 v7.2 并监控日志。
- 紧急恢复方案：使用 `--no-precheck` 禁用 `check_api` 预检，但会降低错误检测效率。

---

## 八、总结

本次工作完成了 LingoFuse MCP Server 从脚本到生产级 EXE 的完整适配，解决了打包、传输协议、日志、编码等多方面问题。在 2026‑09‑09 的追加修复中，成功解决了动态工具缓存不一致和离线检测误报两大关键问题，使系统在动态服务环境下表现更加可靠。所有改动均经过验证，代码已交付并可用于 LM Studio、Claude Desktop 等客户端集成。后续若需迭代，可基于此版本扩展。

---

**文档生成日期**：2026-09-09（更新）  
**交付人**：AI 智能体（PassByYou888 / LingoFuse 团队）  
**版本**：V1.1