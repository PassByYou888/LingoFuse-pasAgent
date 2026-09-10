# Build_Guide.md

## LingoFuse-pasAgent 组件编译指南（Windows）

本文档介绍如何将 LingoFuse-pasAgent 中的 Python 脚本和 Pascal 源代码编译为可执行文件（EXE）。所有编译均在 Windows 环境下完成，使用的工具包括 **PyInstaller**（Python → EXE）和 **Lazarus / Free Pascal**（Pascal → EXE）。

---

## 目录

1. [前置准备](#1-前置准备)
2. [Python 组件编译](#2-python-组件编译)
   - 2.1 环境准备
   - 2.2 使用脚本编译 mcp_server.exe（含 mcp_proxy.exe）
   - 2.3 使用脚本编译 bridge.exe
   - 2.4 使用脚本编译 llm_service_*.exe
3. [Pascal 组件编译](#3-pascal-组件编译)
   - 3.1 环境准备
   - 3.2 使用 build_pascal_agent.bat 一键编译
   - 3.3 单独编译某个 Pascal 项目（使用 lazbuild）
4. [LingoFuse 动态库部署](#4-lingofuse-动态库部署)
5. [常见问题](#5-常见问题)
6. [附录：编译产物目录](#6-附录编译产物目录)

---

## 1. 前置准备

### 1.1 操作系统
- Windows 10/11（64 位推荐）

### 1.2 必需软件

| 软件 | 用途 | 获取方式 |
|------|------|----------|
| **Python 3.7+**（64 位） | 运行 PyInstaller 及 Python 脚本 | [python.org](https://python.org) |
| **PyInstaller** | 将 Python 脚本打包为 EXE | `pip install pyinstaller` |
| **Lazarus**（含 Free Pascal 3.2+） | 编译 Pascal 项目（必须使用 lazbuild 或 IDE） | [Lazarus IDE](https://lazarus-ide.org) |
| **LingoFuse 动态库** | 所有 EXE 的运行时依赖 | 由 LingoFuse 项目提供（`LingoFuse64.dll`） |

> **注意**：Pascal 项目的编译**不要直接使用 `fpc` 命令行**，因为项目依赖复杂的单元搜索路径（Z 框架、LingoFuse 等）。必须使用 `lazbuild` 或 Lazarus IDE，它们能正确读取 `.lpi` 文件中的配置。

### 1.3 源代码目录结构

本项目根目录（假设为 `D:\git\LingoFuse-pasAgent\src`）包含以下关键脚本和文件：

```
src/
├── build_mcp_server.ps1          # 编译 mcp_server.exe 和 mcp_proxy.exe
├── build_bridge.ps1              # 编译 bridge.exe
├── build_llm_service.ps1         # 编译 llm_service.exe（CPU / CUDA / Vulkan 等版本）
├── build_pascal_agent.bat        # 一键编译所有 Pascal 项目
├── generate_agent_json.py        # 配置生成器
├── language_middleware.py        # MCP 依赖
├── mcp_server.py                 # MCP 服务器源码
├── mcp_proxy.py                  # 代理源码
├── pascal_agent_service.lpi      # Lazarus 项目文件
├── pascal_agent_api.lpi
├── lingofuse/                    # Python 核心包（编译时会打包）
├── llm-service/                  # LLM 服务源码
│   ├── llm_service.py
│   └── ...
├── CreateHealthCheck/            # 健康检查 Pascal 项目
│   ├── HealthCheck.lpi
│   └── ...
└── tools/                        # 开发工具（pascal_decl_to_mcp 等）
```

---

## 2. Python 组件编译

所有 Python 脚本均可通过 PyInstaller 打包为独立的 EXE。项目已在 `src` 目录提供了 PowerShell 脚本，**强烈建议使用这些脚本**，它们已配置好必要的参数（依赖收集、数据文件等）。

### 2.1 环境准备

打开 PowerShell，进入 `src` 目录，执行以下命令安装依赖：

```powershell
cd D:\git\LingoFuse-pasAgent\src
pip install -r requirements.txt
pip install pyinstaller
```

### 2.2 编译 mcp_server.exe（含 mcp_proxy.exe）

运行脚本：

```powershell
.\build_mcp_server.ps1
```

脚本内容大致如下（供参考）：

```powershell
pyinstaller --onefile `
    --collect-all fastmcp `
    --collect-all pydantic `
    --collect-all tzdata `
    --hidden-import language_middleware `
    --paths . `
    --add-data "lingofuse;lingofuse" `
    mcp_server.py

pyinstaller --onefile `
    --name mcp_proxy `
    --clean `
    --noconfirm `
    mcp_proxy.py
```

编译完成后，在 `dist\` 目录下将生成：

- `mcp_server.exe`
- `mcp_proxy.exe`

### 2.3 编译 bridge.exe

运行脚本：

```powershell
.\build_bridge.ps1
```

脚本内容大致如下：

```powershell
pyinstaller --onefile `
    --collect-all flask `
    --paths . `
    --hidden-import lingofuse `
    lingofuse\bridge.py
```

编译完成后，生成 `bridge.exe`。

### 2.4 编译 llm_service_*.exe

`llm_service.py` 位于 `llm-service\` 目录，可生成多个版本（CPU、CUDA、Vulkan 等）。运行脚本：

```powershell
.\build_llm_service.ps1
```

脚本内容大致如下：

```powershell
pyinstaller --onefile `
    --paths . `
    --collect-all llama_cpp `
    --collect-all lingofuse `
    --hidden-import llama_cpp `
    --hidden-import lingofuse `
    llm-service\llm_service.py
```

编译完成后，在 `dist\` 目录下生成 `llm_service_cpu.exe` 等（具体命名取决于脚本）。

> 如需支持 CUDA 或 Vulkan，请确保已安装对应的 Python 包（`llama-cpp-python` 的 GPU 版本），并修改脚本中的 `--name`。

---

## 3. Pascal 组件编译

Pascal 项目必须使用 **Lazarus**（或 `lazbuild`）编译，**不要直接调用 `fpc`**。

### 3.1 环境准备

- 安装 Lazarus IDE（包含 Free Pascal 编译器）。
- 确保 `lazbuild.exe` 位于系统 PATH 中，或使用绝对路径。

### 3.2 使用 build_pascal_agent.bat 一键编译

在项目根目录（`src`）双击或命令行执行：

```bat
build_pascal_agent.bat
```

该脚本内容如下：

```bat
lazbuild.exe -B ./pascal_agent_service.lpi
lazbuild.exe -B ./pascal_agent_api.lpi
lazbuild.exe -B ./CreateHealthCheck/HealthCheck.lpi
echo 所有项目编译完成。
timeout /t 5 /nobreak >nul
```

执行后，将编译并生成：

- `pascal_agent_service.exe`
- `pascal_agent_api.exe`
- `HealthCheck.exe`（在 `CreateHealthCheck\` 目录下）

### 3.3 单独编译某个 Pascal 项目（使用 lazbuild）

如果只想编译某个项目，可以在命令行使用 `lazbuild`：

```cmd
lazbuild.exe -B .\pascal_agent_service.lpi
```

或者使用 Lazarus IDE：打开 `.lpi` 文件，按 `Ctrl+F9` 编译。

---

## 4. LingoFuse 动态库部署

所有编译出的 EXE 运行时都需要 `LingoFuse64.dll`（Windows）或 `liblingofuse.so`（Linux）。该库由 LingoFuse 核心项目提供，不包含在本仓库中。

**推荐部署方式：将动态库目录加入系统 PATH。**

1. 克隆 LingoFuse 仓库（需 `--recursive` 拉取子模块）：
   ```bash
   git clone --recursive https://github.com/PassByYou888/LingoFuse.git
   ```
2. 将 LingoFuse 的 `Binary` 目录（或包含 `LingoFuse64.dll` 的目录）加入系统 `PATH`：
   - **Windows（永久）**：系统属性 → 环境变量 → 编辑 `Path`，添加该目录。
   - **Windows（临时）**：在 PowerShell 中执行 `$env:PATH = "D:\LingoFuse\Binary;$env:PATH"`。
   - **Linux/macOS**：`export PATH=/path/to/LingoFuse/Binary:$PATH`。

这样系统就能自动找到动态库，无需将 DLL 复制到每个 EXE 目录。

**备选方案**：将动态库复制到每个 EXE 所在目录（例如 `dist\`）。

---

## 5. 常见问题

### Q1: 运行 EXE 时提示 “Failed to load LingoFuse64.dll”
- 确保 `LingoFuse64.dll` 与 EXE 在同一目录，或已在系统 `PATH` 中。
- 检查动态库位数是否与 EXE 一致（64 位 vs 32 位）。

### Q2: PyInstaller 打包后运行报 “ModuleNotFoundError”
- 可尝试增加 `--hidden-import` 参数，或检查 `--add-data` 是否正确包含 `lingofuse` 包。
- 参考项目提供的脚本，它们已配置好所需参数。

### Q3: Pascal 编译报 “Can't find unit Z.Core”
- 确保使用 `lazbuild` 编译，因为 `.lpi` 中已配置单元搜索路径。
- 若手动调用 `fpc`，需手动指定 `-Fu` 路径，极易出错，请改用 `lazbuild`。

### Q4: 编译的 EXE 体积过大
- 使用 `--upx-dir` 参数启用 UPX 压缩（需先下载 UPX），可显著减小体积。
- 但 `--onefile` 模式本身会增大启动解压开销，若体积敏感，可改用 `--onedir` 模式。

### Q5: 使用 `--generate-configs` 时找不到 `generate_agent_json` 模块
- 确保 `generate_agent_json.py` 在相同目录，且打包时已包含（`--add-data` 或 `--hidden-import`）。

---

## 6. 附录：编译产物目录

最终编译后，建议将所有 EXE 和依赖动态库放在同一目录，以便分发：

```
C:\temp2\dist\
├── LingoFuse64.dll                    # 从 LingoFuse 仓库复制或通过 PATH 提供
├── mcp_server.exe
├── mcp_proxy.exe
├── bridge.exe
├── llm_service_cpu.exe                # 或 llm_service_cu124.exe / vulkan 等
├── pascal_agent_service.exe
├── pascal_agent_api.exe
├── HealthCheck.exe                    # 来自 CreateHealthCheck 目录
├── pascal_decl_to_mcp.exe             # 若使用 tools 项目编译
├── qwen2.5-7b-instruct-q4_k_m.gguf    # 可选，用于 LLM 服务
└── (配置文件、文档等)
```

---

**文档版本**：V2.0  
**最后更新**：2026-09-10  
**维护者**：LingoFuse-pasAgent 团队