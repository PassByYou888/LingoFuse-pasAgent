# Build_Guide.md

## LingoFuse 组件编译指南（Windows）

本文档介绍如何将 LingoFuse 项目中的 Python 脚本和 Pascal 源代码编译为可执行文件（EXE）。所有编译均在 Windows 环境下完成，使用的工具包括 **PyInstaller**（Python → EXE）和 **Free Pascal / Lazarus**（Pascal → EXE）。

---

## 目录

1. [前置准备](#1-前置准备)
2. [Python 组件编译](#2-python-组件编译)
   - 2.1 环境准备
   - 2.2 编译 mcp_server.exe
   - 2.3 编译 mcp_proxy.exe
   - 2.4 编译 bridge.exe
   - 2.5 编译 llm_service_*.exe
3. [Pascal 组件编译](#3-pascal-组件编译)
   - 3.1 环境准备
   - 3.2 编译 pascal_agent_service.exe
   - 3.3 编译 pascal_agent_api.exe
   - 3.4 编译 HealthCheck.exe
   - 3.5 编译 pascal_decl_to_mcp.exe（如果有）
4. [打包脚本说明](#4-打包脚本说明)
5. [常见问题](#5-常见问题)
6. [附录：目录结构](#6-附录目录结构)

---

## 1. 前置准备

### 1.1 操作系统
- Windows 10/11（64 位推荐）

### 1.2 必需软件
| 软件 | 用途 | 获取方式 |
|------|------|----------|
| **Python 3.7+**（64 位） | 运行 PyInstaller 及 Python 脚本 | [python.org](https://python.org) |
| **PyInstaller** | 将 Python 脚本打包为 EXE | `pip install pyinstaller` |
| **Free Pascal 3.2+**（或 Lazarus） | 编译 Pascal 源文件 | [freepascal.org](https://freepascal.org) 或 [Lazarus IDE](https://lazarus-ide.org) |
| **LingoFuse 动态库** | 所有 EXE 的运行时依赖 | 由 LingoFuse 项目提供（`LingoFuse64.dll`） |

### 1.3 目录结构（关键）
```
D:\LingoFuse-pasAgent\src\
├── build_mcp_server.ps1          # PyInstaller 打包脚本（Python→EXE）
├── build_pascal_agent.bat        # Pascal 编译批处理（可选）
├── generate_agent_json.py        # 配置生成器
├── language_middleware.py        # 依赖库
├── mcp_proxy.py                  # 代理源码
├── mcp_server.py                 # MCP 服务器源码
├── pascal_agent_api.lpi          # Lazarus 项目文件
├── pascal_agent_api.lpr          # 主程序源码
├── pascal_agent_service.lpi
├── pascal_agent_service.lpr
├── lingofuse\                    # Python 核心包（编译时会打包）
│   ├── bridge.py
│   ├── client.py
│   ├── core.py
│   ├── ...
├── CreateHealthCheck\            # 健康检查 Pascal 项目
│   ├── HealthCheck.lpi
│   ├── HealthCheck.lpr
│   └── ...
└── (其他文件)
```

---

## 2. Python 组件编译

所有 Python 脚本均可通过 PyInstaller 打包为独立的 EXE。以下步骤假设您已在项目根目录（`D:\LingoFuse-pasAgent\src`）打开 PowerShell 或命令提示符。

### 2.1 环境准备

```powershell
# 安装 PyInstaller（如果尚未安装）
pip install pyinstaller

# 确保依赖库已安装（见 requirements.txt）
pip install -r requirements.txt   # 若存在
# 或手动安装：pip install fastmcp pydantic flask requests ...
```

### 2.2 编译 mcp_server.exe

使用提供的 `build_mcp_server.ps1` 脚本（若不存在，可按以下命令手动执行）：

```powershell
# 单文件模式，将所有依赖打包进一个 EXE
pyinstaller --onefile --name mcp_server --console `
  --add-data "lingofuse;lingofuse" `
  --hidden-import fastmcp `
  --hidden-import pydantic `
  --hidden-import language_middleware `
  mcp_server.py
```

**参数说明**：
- `--onefile`：生成单个 EXE。
- `--add-data "lingofuse;lingofuse"`：将 `lingofuse` 包作为数据目录打包，使 EXE 能找到该模块。
- `--hidden-import`：显式导入一些动态加载的模块，防止 PyInstaller 遗漏。

编译完成后，`mcp_server.exe` 将出现在 `dist\` 目录下。

### 2.3 编译 mcp_proxy.exe

```powershell
pyinstaller --onefile --name mcp_proxy --console mcp_proxy.py
```

### 2.4 编译 bridge.exe

`bridge.py` 依赖 Flask，需包含整个 `lingofuse` 包：

```powershell
pyinstaller --onefile --name bridge --console `
  --add-data "lingofuse;lingofuse" `
  --hidden-import flask `
  lingofuse\bridge.py
```

### 2.5 编译 llm_service_*.exe

`llm_service.py` 通常有多个版本（CPU、CUDA、Vulkan），编译时需指定不同后端依赖（如 `llama-cpp-python` 或 `transformers`）。以 CPU 版本为例：

```powershell
pyinstaller --onefile --name llm_service_cpu --console `
  --add-data "lingofuse;lingofuse" `
  --hidden-import llama_cpp `
  --hidden-import transformers `
  llm_service.py
```

若需 CUDA 或 Vulkan 版本，确保已安装对应的 Python 包，并调整名称。

---

## 3. Pascal 组件编译

Pascal 源码使用 Free Pascal 或 Lazarus IDE 编译。推荐使用 Lazarus（提供图形界面）或直接调用 `fpc` 命令行。

### 3.1 环境准备

- 安装 Free Pascal（或 Lazarus）。
- 确保编译器 `fpc.exe` 在 PATH 中，或使用 Lazarus 的 `lazbuild.exe`。

### 3.2 编译 pascal_agent_service.exe

**命令行方式**（在项目根目录执行）：

```cmd
fpc -Mdelphi -O2 -vw -Fu..\ZCore -Fu..\ZJson -Fu..\LingoFuse-Export -Fl..\Binary -FE. pascal_agent_service.lpr
```

但由于该项目引用了多个外部单元（Z.Core, Z.Json, lingofuse_import 等），推荐使用 **Lazarus IDE** 打开 `pascal_agent_service.lpi`，然后点击“编译”（Ctrl+F9）。编译后的 EXE 将生成在项目输出目录（默认为 `lib\` 或 `.\`）。

若使用 `build_pascal_agent.bat`，可直接双击执行（需确保已配置好路径）。

### 3.3 编译 pascal_agent_api.exe

类似，打开 `pascal_agent_api.lpi` 并编译。

### 3.4 编译 HealthCheck.exe

进入 `CreateHealthCheck\` 子目录，打开 `HealthCheck.lpi` 并编译。

### 3.5 编译 pascal_decl_to_mcp.exe

（如果有对应 `.lpr` 或 `.lpi`）同样方法编译。

---

## 4. 打包脚本说明

项目中提供的 `build_mcp_server.ps1` 是一个 PowerShell 脚本，用于自动化编译 `mcp_server.exe`。其内容可参考：

```powershell
# build_mcp_server.ps1
pyinstaller --onefile --name mcp_server --console `
  --add-data "lingofuse;lingofuse" `
  --hidden-import fastmcp `
  --hidden-import pydantic `
  --hidden-import language_middleware `
  --hidden-import generate_agent_json `
  mcp_server.py
```

**注意**：如果编译后运行 EXE 出现“找不到模块”错误，可能需要调整 `--add-data` 或 `--hidden-import`。可参考 `pyi-makespec` 生成 spec 文件进行精细控制。

---

## 5. 常见问题

### Q1: 运行 EXE 时提示 “Failed to load LingoFuse64.dll”
- 确保 `LingoFuse64.dll` 与 EXE 在同一目录，或在系统 PATH 中。
- 检查动态库是否与 EXE 架构一致（64 位 vs 32 位）。

### Q2: PyInstaller 打包后运行报 “ModuleNotFoundError”
- 添加 `--hidden-import` 显式导入缺失的模块。
- 若需包含整个包，使用 `--add-data "package;package"`。

### Q3: Pascal 编译报 “Can't find unit Z.Core”
- 检查项目文件的搜索路径（`-Fu` 参数），确保引用的单元路径正确。
- 在 Lazarus 中，需将 ZCore 等包的源码目录添加到“项目选项”→“编译器选项”→“其他单元文件”中。

### Q4: 编译的 EXE 体积过大
- 使用 `--upx-dir` 参数启用 UPX 压缩（需先下载 UPX），可显著减小体积。
- 也可使用 `--onefile` 虽会增大解压开销，但便于分发。

### Q5: 使用 `--generate-configs` 时找不到 `generate_agent_json` 模块
- 确保 `generate_agent_json.py` 在相同目录，且打包时已包含（`--add-data` 或 `--hidden-import`）。

---

## 6. 附录：目录结构

最终编译后，建议将所有 EXE 和依赖动态库放在同一目录，以便分发：

```
C:\Temp\temp2\
├── LingoFuse64.dll
├── mcp_server.exe
├── mcp_proxy.exe
├── bridge.exe
├── llm_service_cpu.exe
├── llm_service_cu124.exe
├── llm_service_vulkan.exe
├── pascal_agent_service.exe
├── pascal_agent_api.exe
├── HealthCheck.exe
├── pascal_decl_to_mcp.exe
├── qwen2.5-7b-instruct-q4_k_m.gguf   (可选，用于 LLM 服务)
└── (配置文件、文档等)
```

---

## 7. 补充说明

- **Python 版本**：建议使用与 PyInstaller 兼容的 Python 版本（3.7~3.12 均可）。
- **Pascal 版本**：Free Pascal 3.2.2 以上。
- **多平台支持**：若需 Linux/macOS EXE，请在对应平台上执行 PyInstaller，并调整 `--add-data` 路径分隔符（Linux/macOS 使用 `:` 而非 `;`）。

---

**文档版本**：V1.0  
**最后更新**：2026-09-09  
**维护者**：LingoFuse 团队