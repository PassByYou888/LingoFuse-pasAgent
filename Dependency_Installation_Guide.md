# Dependency_Installation_Guide.md

## LingoFuse-pasAgent 项目依赖安装与编译指南

本文档详细说明编译和运行 **LingoFuse-pasAgent** 各组件所需的依赖包安装步骤，涵盖 Python 环境、Pascal 编译环境以及运行时动态库。无论您是开发者准备从源码编译，还是最终用户准备运行已编译的 EXE，均可参考本指南。

---

## 1. 概述

本项目包含两类主要组件：

- **Python 组件**（如 `mcp_server.py`、`bridge.py`、`llm_service.py` 等），依赖 Python 第三方包。
- **Pascal 组件**（如 `pascal_agent_service.lpr`、`pascal_agent_api.lpr`、`HealthCheck.lpr`），依赖 Free Pascal 编译器和 Lazarus IDE。

**所有组件均依赖 LingoFuse 动态库**（`LingoFuse64.dll` / `liblingofuse.so`），该库由 LingoFuse 核心项目提供，不包含在本仓库中。

---

## 2. 环境准备

### 2.1 Python 环境

- Python 3.7 及以上版本（推荐 3.10 ~ 3.12）
- pip（Python 包管理工具）

### 2.2 Pascal 编译环境

- **Free Pascal 3.2+**（必须）
- **Lazarus IDE**（推荐，用于编译 Pascal 项目，且项目依赖 Lazarus 的 `.lpi` 文件）

> **注意**：本项目中的 Pascal 项目使用 Lazarus 项目文件（`.lpi`），**强烈建议使用 `lazbuild` 或 Lazarus IDE 进行编译**，而不是直接调用 `fpc`。因为项目包含复杂的依赖路径和单元搜索路径，`lazbuild` 能自动读取并处理这些配置。

---

## 3. Python 依赖安装

### 3.1 快速安装（使用 `requirements.txt`）

在 `src/` 目录下执行：

```bash
cd src
pip install -r requirements.txt
```

`requirements.txt` 包含 MCP Server 和 HTTP 网关的基础依赖。

### 3.2 手动安装核心依赖

根据您要使用的组件，可能需要安装以下包：

| 包名 | 用途 | 是否必需 |
|------|------|----------|
| `fastmcp` | MCP 协议核心库（`mcp_server.py` 依赖） | **必需**（若使用 MCP Server） |
| `pydantic` | FastMCP 依赖的数据验证库 | **必需** |
| `flask` | HTTP 网关（`bridge.py`） | 若使用 bridge 则必需 |
| `requests` | HTTP 客户端（测试脚本用） | 可选 |
| `llama-cpp-python` | LLM 服务（`llm_service.py` CPU 版） | 若需本地 LLM 则必需 |
| `transformers` + `torch` | LLM 服务（替代后端） | 可选 |
| `pyinstaller` | 打包工具（仅开发者需要） | 编译时必需 |

### 3.3 安装命令示例

```bash
# 基础 MCP Server 依赖
pip install fastmcp pydantic

# HTTP 网关（bridge）依赖
pip install flask

# LLM 服务（CPU 版，使用 llama.cpp）
pip install llama-cpp-python

# LLM 服务（使用 transformers + PyTorch，需 CUDA 支持时可安装 torch 的 CUDA 版本）
pip install transformers torch

# 打包工具（仅编译 EXE 时）
pip install pyinstaller

# 测试工具（可选）
pip install requests
```

---

## 4. 获取 LingoFuse 动态库

所有 EXE 和 Python 脚本运行时都需要 **LingoFuse 动态库**。该库不包含在本仓库中，需从 [LingoFuse 仓库](https://github.com/PassByYou888/LingoFuse) 获取。

### 4.1 推荐部署方法：加入系统 PATH

1. 克隆 LingoFuse 仓库（需 `--recursive` 拉取子模块）：

```bash
git clone --recursive https://github.com/PassByYou888/LingoFuse.git
```

2. 将 LingoFuse 的 `Binary` 目录（或放置动态库的目录）加入系统 `PATH`。

   - **Windows**（PowerShell）：
     ```powershell
     $env:PATH = "D:\path\to\LingoFuse\Binary;$env:PATH"
     ```
     或者永久设置：系统属性 → 环境变量 → 编辑 `Path`。

   - **Linux / macOS**：
     ```bash
     export PATH=/path/to/LingoFuse/Binary:$PATH
     ```

   这样系统就能直接找到 `LingoFuse64.dll` / `liblingofuse.so`，无需复制到每个项目目录。

### 4.2 或者：将动态库复制到 EXE 同目录

如果不想修改 PATH，可以将动态库复制到每个 EXE 所在目录（例如 `src` 下编译出的 `mcp_server.exe`、`pascal_agent_service.exe` 等）。

---

## 5. 编译指南

### 5.1 Python 组件编译（生成 EXE）

在 `src` 目录下，提供了 PowerShell 脚本用于打包 Python 组件：

| 脚本 | 作用 | 说明 |
|------|------|------|
| `build_mcp_server.ps1` | 编译 `mcp_server.exe` | 打包 FastMCP、pydantic、lingofuse 等依赖 |
| `build_bridge.ps1` | 编译 `bridge.exe` | 打包 Flask 和 lingofuse |
| `build_llm_service.ps1` | 编译 `llm_service.exe` | 打包 llama_cpp / lingofuse（可针对不同后端生成多个版本） |

**使用方法**（在 `src` 目录打开 PowerShell）：

```powershell
.\build_mcp_server.ps1
```

脚本会调用 PyInstaller 生成 `.exe` 文件，输出位于 `dist` 目录。

> **注意**：编译前确保已安装 `pyinstaller` 和相应 Python 依赖（如 `fastmcp`、`pydantic`、`flask`、`llama-cpp-python` 等）。

### 5.2 Pascal 组件编译

**必须使用 Lazarus 或 `lazbuild`**，项目提供了一键脚本 `build_pascal_agent.bat`（在 `src` 目录）：

```bat
lazbuild.exe -B ./pascal_agent_service.lpi
lazbuild.exe -B ./pascal_agent_api.lpi
lazbuild.exe -B ./CreateHealthCheck/HealthCheck.lpi
echo 所有项目编译完成。
timeout /t 5 /nobreak >nul
```

运行方式（在 `src` 目录）：

```cmd
build_pascal_agent.bat
```

该脚本会编译：

- `pascal_agent_service.exe`
- `pascal_agent_api.exe`
- `HealthCheck.exe`

如果 Lazarus 未配置到 PATH，请用 Lazarus IDE 打开相应 `.lpi` 文件，点击“编译”即可。

**为什么不推荐直接 `fpc` 编译？**

- 项目依赖 Z 框架等大量外部单元，路径配置复杂，`lazbuild` 能正确读取 `.lpi` 中的搜索路径。
- 直接调用 `fpc` 需要手动指定大量 `-Fu` 参数，极易出错。
- 使用 `lazbuild` 可以确保与 Lazarus IDE 编译结果一致，减少兼容性问题。

---

## 6. 验证安装

### 6.1 验证 Python 环境

```bash
python -c "import fastmcp; import pydantic; print('OK')"
```

### 6.2 验证 Pascal 编译环境

编译成功 `pascal_agent_service.exe` 后，运行：

```bash
pascal_agent_service.exe
```

若能看到 `[MAIN] Service is running...` 则说明环境配置正确。

### 6.3 验证 LingoFuse 动态库

运行任何生成的 EXE 或 Python 脚本，若提示 `Failed to load LingoFuse64.dll`，则说明动态库未找到，请检查 PATH 或复制动态库。

---

## 7. 常见问题

### Q1: pip 安装失败（网络问题）

- 使用国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 包名`
- 或使用代理。

### Q2: 运行 EXE 提示“缺少 DLL”

- 将 `LingoFuse64.dll`（或 `liblingofuse.so`）复制到 EXE 目录，或将其所在目录添加到系统 `PATH`。
- 确保动态库与 EXE 架构一致（64 位 vs 32 位）。

### Q3: 编译 Pascal 项目时提示“找不到单元”

- 确保已正确配置 Lazarus 的项目搜索路径（`.lpi` 文件中已定义）。
- 若使用 `build_pascal_agent.bat`，请确认 `lazbuild.exe` 在 PATH 中，或使用绝对路径调用。

### Q4: PyInstaller 打包后运行报 `ModuleNotFoundError`

- 可能需要增加 `--hidden-import` 参数，例如 `--hidden-import language_middleware`。
- 确保 `lingofuse` 包被包含在 `--add-data` 中（参考脚本）。

---

## 8. 总结

- **依赖**：所有组件需 LingoFuse 动态库，推荐通过克隆 LingoFuse 仓库并添加 PATH 来部署。
- **Python 编译**：使用 `src` 下的 `*.ps1` 脚本（PyInstaller）。
- **Pascal 编译**：使用 `build_pascal_agent.bat`（基于 `lazbuild`），**不建议直接使用 `fpc`**。

如有任何未覆盖的问题，请参考项目文档或联系开发团队。

---

**文档版本**：V2.0  
**最后更新**：2026-09-10  
**维护者**：LingoFuse-pasAgent 团队