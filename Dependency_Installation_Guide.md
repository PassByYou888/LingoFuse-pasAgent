# Dependency_Installation_Guide.md

## LingoFuse 项目依赖包安装指南

本文档详细说明编译和运行 LingoFuse 各组件所需的依赖包安装步骤，涵盖 Python 环境、Pascal 编译环境以及运行时动态库。无论您是开发者准备从源码编译，还是最终用户准备运行已编译的 EXE，均可参考本指南。

---

## 1. 概述

LingoFuse 项目主要包含两类组件：

- **Python 组件**（如 `mcp_server.py`、`bridge.py`、`llm_service.py` 等），依赖 Python 第三方包。
- **Pascal 组件**（如 `pascal_agent_service.lpr`、`pascal_agent_api.lpr`），依赖 Free Pascal 编译器和外部单元库（ZCore、ZJson 等）。

所有组件均依赖 **LingoFuse 动态库**（`LingoFuse64.dll` 或 `liblingofuse.so`），该库由核心 C4 服务网格提供。

---

## 2. Python 依赖安装

### 2.1 环境要求
- Python 3.7 及以上版本（推荐 3.10 ~ 3.12）
- pip（Python 包管理工具）

### 2.2 快速安装（使用 requirements.txt）

若项目根目录包含 `requirements.txt`，可直接执行：

```bash
pip install -r requirements.txt
```

### 2.3 手动安装核心依赖

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

### 2.4 具体安装命令

```bash
# 基础 MCP Server 依赖
pip install fastmcp pydantic

# HTTP 网关（bridge）依赖
pip install flask

# LLM 服务（CPU 版，使用 llama.cpp）
pip install llama-cpp-python

# LLM 服务（使用 transformers + PyTorch，需 CUDA 支持时可安装 torch 的 CUDA 版本）
pip install transformers torch

# 打包工具（仅开发时）
pip install pyinstaller

# 测试工具（可选）
pip install requests
```

### 2.5 验证安装

运行以下命令检查核心包是否可导入：

```bash
python -c "import fastmcp; import pydantic; print('OK')"
```

若输出 `OK` 则基础环境准备就绪。

---

## 3. Pascal 编译环境依赖

### 3.1 Free Pascal 编译器

- **下载**：访问 [Free Pascal 官网](https://www.freepascal.org/download.html) 下载对应操作系统的安装包（Windows 推荐 64 位）。
- **安装**：默认安装即可，记下安装路径（如 `C:\fpc\3.2.2`）。
- **环境变量**：将 `fpc.exe` 所在目录（如 `C:\fpc\3.2.2\bin\x86_64-win64`）添加到系统 `PATH`。

验证安装：

```cmd
fpc -v
```

### 3.2 Lazarus IDE（可选但推荐）

若您使用 Lazarus 打开 `.lpi` 项目文件，需安装 Lazarus：

- **下载**：[Lazarus 官网](https://www.lazarus-ide.org/)
- **安装**：选择与 FPC 匹配的版本，安装时通常会自动配置 FPC 路径。

### 3.3 外部 Pascal 单元库（ZCore、ZJson 等）

Pascal 项目引用了以下单元库，需提前准备好并配置搜索路径：

- **Z.Core**：基础线程、容器、时间等核心库。
- **Z.PascalStrings** / **Z.UPascalStrings**：字符串处理。
- **Z.Json**：JSON 解析（`TZ_JsonObject` 等）。
- **Z.Status**：全局日志。
- **Z.UnicodeMixedLib**：Unicode 工具。
- **Z.HashList.Templet**：哈希表容器。
- **Z.MemoryStream**：内存流。
- 以及 **Z.Net.C4**、**Z.Net.DoubleTunnelIO.NoAuth** 等网络库。

这些库通常以源代码形式存在于 `..\ZCore`、`..\ZJson` 等上级目录中。如果您尚未下载，需从 LingoFuse 项目仓库中获取完整的 Z 框架源码，或将源码目录放在正确位置（通常与 `src` 同级）。

在 Lazarus 中，可通过“项目选项”→“编译器选项”→“其他单元文件”添加这些库的路径。在命令行编译时，使用 `-Fu` 参数指定路径（参见 `build_pascal_agent.bat`）。

### 3.4 编译命令示例（cmd）

```cmd
fpc -Mdelphi -O2 -Fu..\ZCore -Fu..\ZJson -Fu..\ZHashList -Fu..\ZMemoryStream -Fu..\ZNet -Fu..\ZNet.C4 -FE. pascal_agent_service.lpr
```

若您没有源码，可联系团队获取预编译的单元（.ppu 或 .o 文件），但推荐使用源码以确保版本匹配。

---

## 4. LingoFuse 动态库

所有组件运行时都需要 `LingoFuse64.dll`（Windows）或 `liblingofuse.so`（Linux）。该库由 LingoFuse 核心项目编译生成，不包含在 Python 或 Pascal 源码中。

- **获取**：从 LingoFuse 发布版本中下载，或自行编译 C4 服务网格。
- **放置**：将动态库放置在 EXE 同目录下，或系统 `PATH` 中。

验证动态库是否存在且可加载：运行任何 LingoFuse 程序（如 `HealthCheck.exe`）或 Python 脚本，若报“Failed to load”则说明动态库未找到。

---

## 5. LLM 服务额外依赖（可选）

若您使用 `llm_service_*.exe` 或对应的 Python 脚本，需额外安装：

- **llama-cpp-python**：用于本地 GGUF 模型推理。
- **transformers + torch**：若使用 Hugging Face 模型（性能较低，不推荐生产）。

安装命令：

```bash
# CPU 版本
pip install llama-cpp-python

# 带 GPU 加速（CUDA 11.8）
pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu118

# 或使用 transformers + torch（需 CUDA 支持）
pip install transformers torch --index-url https://download.pytorch.org/whl/cu118
```

确保您的系统有足够的显存（若使用 GPU）。

---

## 6. 验证全部依赖

### 6.1 Python 环境验证

创建测试文件 `test_imports.py`：

```python
import fastmcp
import pydantic
import flask   # 如果 bridge 需要
import llama_cpp  # 若使用 LLM
print("All imports OK")
```

运行：

```bash
python test_imports.py
```

### 6.2 Pascal 编译验证

尝试编译一个简单项目（如 `pascal_agent_service.lpr`），若成功生成 EXE，则环境配置正确。

### 6.3 运行时验证

运行 `mcp_server.exe --help` 或 `pascal_agent_service.exe` 检查是否能正常启动，确保动态库被正确加载。

---

## 7. 常见问题

### Q1: pip 安装失败（网络问题）
- 使用国内镜像：`pip install -i https://pypi.tuna.tsinghua.edu.cn/simple 包名`
- 或使用代理。

### Q2: fpc 找不到单元文件
- 检查 `-Fu` 路径是否正确，路径分隔符在 Windows 下可用 `\` 或 `/`。
- 确保单元文件（`.ppu`）与当前 FPC 版本兼容。

### Q3: 运行 EXE 提示“缺少 DLL”
- 将 `LingoFuse64.dll` 复制到 EXE 目录，或将其路径添加到系统 `PATH`。
- 可使用 `Dependency Walker` 检查缺失的依赖。

### Q4: 打包的 EXE 体积过大
- 使用 UPX 压缩（需下载 UPX 并配置 PyInstaller 的 `--upx-dir`）。
- 对于 Python EXE，可考虑使用 `--onefile` 虽会增大解压开销，但便于分发。

---

## 8. 总结

本指南涵盖了从零搭建 LingoFuse 开发/运行环境所需的所有依赖安装步骤。若您仅作为最终用户运行已编译的 EXE，通常只需关注 **LingoFuse 动态库** 的放置即可。若您需要修改或重新编译源码，请按照上述步骤安装完整的 Python 包和 Pascal 环境。

如有任何未覆盖的问题，请参考项目文档或联系开发团队。

---

**文档版本**：V1.0  
**最后更新**：2026-09-09  
**维护者**：LingoFuse 团队