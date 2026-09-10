# pascal_decl_to_mcp 使用手册

**版本**：V1.0  
**适用工具**：`pascal_decl_to_mcp.exe`（LingoFuse-pasAgent 工具链）  
**文档定位**：面向 Pascal 开发者的完整使用手册，覆盖运作思路、界面结构、工作流程、数据结构、LLM 助手用法、编译部署与常见问题。

---

## 目录

1. [工具定位](#1-工具定位)
2. [运作思路：5 层透明转换模型](#2-运作思路5-层透明转换模型)
3. [界面速览](#3-界面速览)
4. [完整工作流程](#4-完整工作流程)
5. [各层数据结构详解](#5-各层数据结构详解)
6. [LLM 助手的使用](#6-llm-助手的使用)
7. [生成代码的结构说明](#7-生成代码的结构说明)
8. [编译与部署](#8-编译与部署)
9. [常见问题](#9-常见问题)
10. [附录：支持的语法与限制](#10-附录支持的语法与限制)

---

## 1. 工具定位

`pascal_decl_to_mcp` 是 **LingoFuse-pasAgent 工具链的核心代码生成器**。

它的使命只有一句话：

> **把任意 Pascal 单元里手写的函数/过程声明，自动转换成一份可以直接编译的「LingoFuse 工具提供者单元」，让你的 Pascal 函数能被 AI 客户端（LM Studio / Claude Desktop / 豆包 / Jan / Continue.dev 等）通过 MCP 协议直接调用。**

它解决的痛点：

- 传统做法：手写 Call 回调、手写 JSON Schema、手写注册代码——重复劳动、容易出错。
- 用本工具：粘源码 → 点几下按钮 → 拿到一份高质量、结构完整、可直接编译的 `.pas` 文件。

**它不是"AI 帮你写代码"**——主链路是**确定性的**（解析 → 规范化 → 代码生成），LLM 只作为可选辅助。

---

## 2. 运作思路：5 层透明转换模型

工具采用 **"LLM + 结构体" 的确定性代码生成链**，把整个过程拆成 5 层，**每一层都是可独立查看、编辑、导出的中间态**：

```
Layer 0  原始代码（Pascal / C / Python / JavaScript 等）
            ↓ 「代码修饰器模型」统一转换为
Layer 1  Pascal 声明体（标准 Pascal 语法文本）
            ⇄ 可双向转换
Layer 2  底层数据结构（LV0）
            — 由 Z.Pascal_Func_Tool 解析生成
            — 包含 tfunc_decl 原始记录
            — 可导出为 LV0 JSON，供外部编辑修正解析错误
            ↓
Layer 3  中间数据结构（LV1）
            — 由 pascal_func_model 将 LV0 规范化：
              · 类型归一化（Integer→Int64，Single→Double，各种 string 别名→string）
              · 参数描述提取（从注释解析 @param、:、= 等格式）
              · 合并注释，生成结构化元数据（TFunctionStructure）
            — 可导出为 LV1 JSON，供外部调整参数描述、类型映射等
            ↓
Layer 4  目标代码生成器（pas_mcp_generator_tool）
            — 基于 LV1 结构体生成完整的 LingoFuse 工具提供者程序
            — 可扩展生成 Python、JavaScript 等其他语言的接口代码
```

**核心设计哲学**：

1. **透明**：每一层的 JSON 表示都能看、能改、能重新导入。
2. **确定**：层与层之间的转换是确定性的，不依赖 LLM 的随机性。
3. **可复现**：同样的输入永远得到同样的输出。
4. **可干预**：任意一层出问题，都能停下来用 LLM 辅助修正，然后继续走确定性链路。
5. **可扩展**：未来只要为其他语言写一个"代码修饰器"（把该语言的声明转成 Pascal 声明文本），就能复用后面所有流程。

---

## 3. 界面速览

主窗口顶部是 **5 个 Tab**，底部是**日志区**（黑底绿字，实时显示处理进度和被跳过的函数）。

| Tab 标签 | 作用 |
|---|---|
| **1-welcome** | 欢迎页，展示 5 层转换模型说明 |
| **2-source** | 编辑/粘贴 Pascal 源码 |
| **2.5-source <--> json** | 源码 ⇄ LV0 声明 JSON 的双向转换 |
| **3.0-Model-Json** | LV1 规范化模型 JSON（生成器的实际输入） |
| **4-Final source** | 最终生成的工具提供者单元源码 |

每个 Tab 右上角都有 `打开LLM模型` 按钮，把当前 Tab 的内容送到 LLM 助手窗口。

工具左下角还有一个 `sysTimer`，每 1 毫秒轮询一次 LingoFuse 状态队列，把内部日志刷到底部日志区。

---

## 4. 完整工作流程

### 第 1 步：欢迎页

打开工具，看到架构说明。阅读完 5 层模型后，点顶部左侧的：

> **下一步: 输入代码**

进入 `2-source`。

### 第 2 步：源码编辑（`2-source`）

把你要转成 MCP 工具的 Pascal 单元**声明部分**粘到编辑器里（`ctrl+v`）。

- 可以只粘 `interface` 段的函数声明。
- 也可以粘完整单元（含 `implementation`），工具会自己筛。

**界面按钮一览**：

| 按钮文字 | 作用 |
|---|---|
| `格式化` | 用 `tpascal_func_decl_tool` 重新解析当前源码，**只保留顶层函数声明**，丢掉实现、类定义、嵌套声明等噪声 |
| `下一步: pascal -> json结构体` | **核心动作**：调用 `CreateFromCode` → `SaveToJson`，把源码转成 LV0 JSON，跳到 `2.5-source <--> json` |
| `空单元` | 插入一个 `unit untitled; ... end.` 骨架 |
| `测试单元` | 插入一个包含各种复杂语法（泛型、类方法、运算符重载、外部声明、嵌套函数指针等）的测试单元，用来验证解析器鲁棒性 |
| `代码格式规则` | 打开 `pascal_code_rule.html`，查看官方推荐的编码规范 |

右上角 `打开LLM模型` 会把当前源码送到 LLM 助手。

### 第 3 步：声明 JSON 编辑（`2.5-source <--> json`）

这一步显示 **LV0 声明 JSON**（`tpascal_func_decl_tool.SaveToJson` 的输出），内容是解析器从源码中提取的**原始声明记录**。

**界面按钮**：

| 按钮文字 | 作用 |
|---|---|
| `上一步: pascal <- json 重建源码` | 反向：用当前 JSON 通过 `decl_to_pascal` 重建 Pascal 源码，跳回 `2-source` |
| `下一步: json <-> model` | **核心动作**：`LoadFromParser` → `TPascal_Func_Model.SaveToJson`，把 LV0 JSON 转成 LV1 模型 JSON，跳到 `3.0-Model-Json` |

**这一步的用途**：

- 可以在专业 JSON 编辑器里**手工修正解析错误**（比如某参数描述没解析对，或某个声明被漏掉了）。
- 修正后把 JSON 粘回来，继续往下走。

### 第 4 步：模型 JSON 编辑（`3.0-Model-Json`）

这一步是 **LV1 模型 JSON**，是 `pas_mcp_generator_tool` **真正要吃的数据**。

相比 LV0，它在生成时已经做过：

- **类型归一化**：`Integer` → `Int64`，`Single`/`Extended`/`Real` → `Double`，各种 string 别名 → `string`
- **参数描述提取**：从注释里解析 `@param`、`名字:`、`名字=` 等格式
- **自动剔除不规则函数**：`var`/`out` 参数、非 `Int64`/`Double`/`string` 类型、嵌套函数都会被过滤掉，并在日志区打印"跳过原因"

**界面按钮**：

| 按钮文字 | 作用 |
|---|---|
| `上一步: json <-> model` | 反向：从 LV1 重建 LV0 JSON，跳回 `2.5` |
| `下一步: 生成源码` | **核心动作**：`GenerateCode(func_model)` 产出完整的工具提供者单元，跳到 `4-Final source` |

**这一步最值得检查**——如果某个函数在最终代码里消失了，回来这里看是被过滤了还是怎么的。日志区会明确告诉你哪些函数被跳过、为什么。

### 第 5 步：最终源码（`4-Final source`）

这一步显示生成的 `<UnitName>_tool_provider_unit.pas`。

例如你贴的是 `frmNewRecord.pas`，生成的就是 `frmnewrecord_tool_provider_unit.pas`。

**界面按钮**：

| 按钮文字 | 作用 |
|---|---|
| `上一步: model-json` | 回到 `3.0-Model-Json` |

**从这个 Tab copy 出代码 → 存成 `.pas` 文件 → 编译进你的 Pascal 工程 → 你就有了一份工具提供者**。

---

## 5. 各层数据结构详解

### 5.1 Layer 0 — 原始代码

你粘贴进去的任何 Pascal 源（或未来支持的其他语言）。工具只关心**声明部分**。

### 5.2 Layer 1 — Pascal 声明体（文本）

这是"代码修饰器"的输出，实际上就是 **标准 Pascal 声明文本**。点 `格式化` 按钮得到的就是它。

示例：

```pascal
function FillRecord(AName, AAge, AGender, ...): string;
function NewRecord(): integer;
function SaveRecord(): string;
```

### 5.3 Layer 2 — LV0 声明 JSON

`tpascal_func_decl_tool.SaveToJson()` 的输出。结构大致是：

```json
{
  "unit_name": "frmNewRecord",
  "funcs": [
    {
      "name": "FillRecord",
      "is_function": true,
      "return_type": "string",
      "comment": "填充新建健康记录表单的所有字段...",
      "params": [
        { "name": "AName", "pascal_type": "string", "modifier": "" },
        { "name": "AAge",  "pascal_type": "string", "modifier": "" }
      ]
    }
  ]
}
```

（实际字段名以工具输出为准）

### 5.4 Layer 3 — LV1 模型 JSON

`TPascal_Func_Model.SaveToJson()` 的输出。相比 LV0：

- 每个函数的 `Params` 里已经带了**描述**（从注释解析出来）
- `PascalType` 已经**归一化**到 `Int64` / `Double` / `string` 三种
- 不支持的函数已被**过滤**（过滤原因记录在 `report` 里）

```json
{
  "unit_name": "frmNewRecord",
  "funcs": [
    {
      "name": "FillRecord",
      "is_function": true,
      "return_type": "string",
      "comment": "...",
      "params": [
        { "name": "AName", "pascal_type": "string", "description": "姓名" },
        { "name": "AAge",  "pascal_type": "string", "description": "年龄" }
      ]
    }
  ]
}
```

### 5.5 Layer 4 — 目标代码

`pas_mcp_generator_tool.GenerateCode()` 输出的完整 Pascal 单元。详见第 7 节。

---

## 6. LLM 助手的使用

从任意 Tab 点 `打开LLM模型` 会弹出 `llm_tool_form` 窗口。

### 6.1 窗口结构

| Tab | 作用 |
|---|---|
| `LLM参数` | 配置端点、APP、系统提示词 |
| `输入` | 显示从主窗口送过来的内容 + 你手写提示词 |
| `输出` | 流式显示 LLM 返回 |

### 6.2 LLM参数

- **端点**：默认 `ipc:llm_service`
- **APP**：默认 `LLM_Service`
- 点 `链接端点` 连接本地 LingoFuse LLM 服务
- **系统提示词**（预设）："你是一个代码声明转换助手，专注于在不同编程语言之间进行程序声明级别的转换"
  - 规则：只转声明，保留注释，禁 markdown，禁 emoji，单行不超 80 字符
- 点 `更新系统提示词` 生效

### 6.3 输入与生成

- `code_Edit` 上半部：显示从主窗口送来的内容（取决于你从哪个 Tab 打开）
- `prompt_edit` 下半部：手写提示词
- 点 `生成` 发送

### 6.4 输出

`sse_Edit` 流式显示 LLM 返回。

### 6.5 设计要点

> **LLM 输出不会自动回填到主窗口。**
>
> 这是刻意的设计——你看完自己决定要不要 copy 出去手动替换。避免 LLM 幻觉污染确定性的生成链路。

LLM 的典型用途：

1. **跨语言转换**：把 C#/Python/JS 的声明转成 Pascal 声明文本，粘回 `2-source`，走后续流程。
2. **修正注释**：把 `frmNewRecord.pas` 里不规范的注释喂给 LLM，让它补上 `@param` 格式的描述，提高 LV1 提取质量。
3. **审查生成结果**：把 `4-Final source` 送过去，让 AI 复查是否有明显问题。
4. **问答**：问"Pascal 里怎么声明函数指针"这类问题。

---

## 7. 生成代码的结构说明

生成的 `<UnitName>_tool_provider_unit.pas` 结构如下：

### 7.1 单元头 + 接口段

定义了一组全局常量，可以直接修改：

```pascal
var
  MY_APP_NAME : string = 'frmNewRecord';
  MY_APP_DESC : string = 'Tool provider for unit frmNewRecord';
  IPC_ENDPOINT : string = 'ipc:agent';
  BEACON_APP : string = 'agent_main_app';
  REGISTER_API : string = 'register_agent';
  AGENT_LOG_API : string = 'agent_log';
  DEBUG_LOG : boolean = True;
```

接口段导出三个函数：

```pascal
function RegisterAPIs: TAppHnd___;
function RegisterTools: Boolean;
function Execute_And_Reg_all: Boolean;
```

### 7.2 内部包装（`internal_` 区域）

每个函数生成一个内部包装：

```pascal
function internal_call_FillRecord_FillRecord(AName, AAge, ...): string;
begin
  Result := '';
  // call type: Result := internal_call_FillRecord_FillRecord(...);
  (*
  {$IFDEF FPC}
    TCompute.Sync(Do_Sync___);
  {$ELSE FPC}
    ...
  {$ENDIF FPC}
  *)
end;
```

> **重要提示**：`(* *)` 里的 `TCompute.Sync` 代码是**被注释掉的**。如果原函数需要操作 UI（VCL/LCL），请**取消注释启用主线程同步**。  
>
> 但如果你的原函数**内部已经用 `Main_Thread_Sync_Tool.Synchronize` 做了同步**（如 `frmNewRecord.pas` 里的 `FillRecord` / `NewRecord` / `SaveRecord`），那就**保持注释状态**即可。

### 7.3 异步日志（`internal_` 区域）

`Do_Th_Send` / `SendLogAsync`：把执行日志异步推给信标，用于调试。

### 7.4 回调（`callback_` 区域）

每个 API 生成一个 cdecl 回调：

```pascal
procedure Callback_FillRecord_FillRecord(_Trigger___: Pointer; _In___, _Out___: TDataHnd___); cdecl;
begin
  jo := TZ_JsonObject.Create;
  try
    jsonBytes := LF_ReadStringBytes(TDataHnd(_In___));
    if Length(jsonBytes) = 0 then ...; // 错误处理
    if not jo.Parae(jsonBytes) then ...; // JSON 解析错误处理
    AName := jo.S['AName'];
    AAge := jo.S['AAge'];
    // ... 提取所有参数
    ret := internal_call_FillRecord_FillRecord(...);
    jo.Clear;
    jo.S['result'] := ret; // 或 I64 / F，视返回类型
    LF_WriteStringBytes(TDataHnd(_Out___), jo.ToBytes);
  except
    on E: Exception do ...;
  end;
  jo.Free;
end;
```

### 7.5 `RegisterTool` 辅助函数

把单个工具定义（JSON）注册到信标：

```pascal
function RegisterTool(const ToolDef: TZ_JsonObject): boolean;
```

### 7.6 `RegisterTools` 实现

遍历所有支持函数，为每个构造 JSON Schema 并调用 `RegisterTool`：

```pascal
function RegisterTools: Boolean;
begin
  // 检查信标可用性
  if not LF_CheckApiEx(BEACON_APP, REGISTER_API) then exit;
  // 逐个注册
  ToolDef.S['name'] := 'FillRecord';
  ToolDef.S['target_app'] := MY_APP_NAME;
  ToolDef.S['target_api'] := 'FillRecord';
  // ... 构造 parameters schema
  Success := RegisterTool(ToolDef);
  // ...
end;
```

### 7.7 `RegisterAPIs` 实现

创建 App 并注册所有 Call API：

```pascal
function RegisterAPIs: TAppHnd___;
begin
  App := LF_CreateAppEx(MY_APP_NAME, MY_APP_DESC);
  LF_RegisterCallEx(App, 'FillRecord', '...', nil, @Callback_FillRecord_FillRecord);
  LF_RegisterCallEx(App, 'NewRecord', '...', nil, @Callback_NewRecord_NewRecord);
  LF_RegisterCallEx(App, 'SaveRecord', '...', nil, @Callback_SaveRecord_SaveRecord);
  Result := App;
end;
```

### 7.8 `Execute_And_Reg_all` 实现

一键启动：

```pascal
function Execute_And_Reg_all: Boolean;
begin
  App := RegisterAPIs();                       // 创建 App
  if App = nil then Exit;
  LF_ResetPrepare();                           // 清除旧准备
  LF_PrepareClientEx(IPC_ENDPOINT, App);       // 连接信标
  if LF_PrepareDone() > 0 then                 // 等待就绪
    Result := RegisterTools();                 // 注册工具
end;
```

调用 `Execute_And_Reg_all()` 即可完成"创建 App → 连接信标 → 注册工具"的整个启动链路。

---

## 8. 编译与部署

### 8.1 编译

生成的 `.pas` 单元必须放在一个 Lazarus 工程里编译。建议做法：

1. 新建一个 `*.lpr` 程序（比如 `my_tool_provider.lpr`），引用生成的单元和 `lingofuse_helper.pas`。
2. 用 Lazarus IDE 打开 `.lpi`，或直接用 `lazbuild`：

```cmd
lazbuild.exe -B .\my_tool_provider.lpi
```

> **不要直接使用 `fpc` 命令行**，因为工程依赖 Z 框架、LingoFuse 动态库等复杂搜索路径，`lazbuild` 能正确读取 `.lpi` 里的配置。

### 8.2 部署

编译出的 EXE 运行时需要：

- **LingoFuse 动态库**（`LingoFuse64.dll` / `liblingofuse.so`）
- **信标**（`pascal_agent_service.exe`）已启动

推荐把 LingoFuse 的 `Binary` 目录加入系统 `PATH`，让 EXE 自动找到动态库。

### 8.3 运行

1. 启动 `pascal_agent_service.exe`（信标）
2. 启动你的工具提供者 EXE
3. 启动 `mcp_server.exe`
4. AI 客户端通过 MCP 协议看到你的工具，就能调用了

---

## 9. 常见问题

**Q1：为什么我粘贴的单元里有 20 个函数，最后只生成了 3 个？**

A：查看 `3.0-Model-Json` 这一步的**日志区**，会明确告诉你哪些函数被跳过、原因是什么。常见原因：

- 参数类型不是 `Int64` / `Double` / `string`（比如 `Integer` 未归一化前是单独的，但现在应该会自动归一化）
- 有 `var` / `out` 参数
- 是嵌套函数（`NestLevel <> 0`）
- 返回值类型不支持

**Q2：生成的 `internal_call_*` 里的 `TCompute.Sync` 要不要启用？**

A：取决于你的原函数是否会操作 UI：

- 原函数**直接操作** LCL/VCL 组件 → **启用**（取消 `(* *)` 注释）
- 原函数**内部已用** `Main_Thread_Sync_Tool.Synchronize` 做了同步 → **保持注释状态**

**Q3：我可以直接改生成的代码吗？**

A：可以。生成的代码是标准的、可读的 Pascal 单元，你可以随意调整。但要注意：**下次重新生成时会覆盖**，所以建议在生成后固定下来，把它当成"业务单元"来用。

**Q4：为什么建议用 LLM 助手而不是直接让 AI 写代码？**

A：因为这套工具的核心是**确定性生成**——LLM 只做辅助（跨语言声明转换、注释补全、代码审查），主链路（解析 → 规范化 → 生成）完全不依赖 LLM 的随机性。这样**每次结果可复现、可审查、可回退**。

**Q5：支持 C#/Python/JS 的函数声明吗？**

A：目前只原生支持 Pascal。其他语言需要**先转成 Pascal 声明文本**（可以借助 LLM 助手），再走后续流程。这是"代码修饰器模型"的未来扩展方向。

**Q6：`RegisterTool` 提示 "Beacon not available"？**

A：确认 `pascal_agent_service.exe` 已经启动，且监听在 `ipc:agent`。可以先用 `LF_CheckApiEx(BEACON_APP, REGISTER_API)` 单独测试一下。

**Q7：生成代码里的 `Execute_And_Reg_all` 和手工调 `RegisterAPIs` + `RegisterTools` 有什么区别？**

A：`Execute_And_Reg_all` 是**一站式**封装，等于：

```
RegisterAPIs() → LF_ResetPrepare() → LF_PrepareClientEx() → LF_PrepareDone() → RegisterTools()
```

如果只需要注册 API（不连接信标），直接调 `RegisterAPIs()`；如果需要完整启动，用 `Execute_And_Reg_all()`。

**Q8：我可以只导出部分函数吗？**

A：可以。在 `2-source` 步骤只粘贴你想导出的函数声明即可，或者在 `3.0-Model-Json` 步骤手工删除不想导出的条目。

---

## 10. 附录：支持的语法与限制

### 10.1 支持的类型（归一化后）

| 原类型 | 归一化为 | JSON 输出类型 |
|---|---|---|
| `Integer` / `Int64` / `Cardinal` / 各种整数 | `Int64` | `integer` |
| `Double` / `Single` / `Extended` / `Real` | `Double` | `number` |
| `string` / `AnsiString` / `UnicodeString` / `PascalString` | `string` | `string` |

### 10.2 不支持的情况（会被跳过）

- `var` / `out` 参数
- 非上述类型的参数或返回值（如 `Boolean`、数组、记录、类、泛型）
- 嵌套函数（`NestLevel <> 0`）
- 类方法、静态方法、构造函数、析构函数、运算符重载

> 未来可能扩展支持，但当前版本请把业务函数写成**顶层、参数和返回值都在支持列表内**的形式。

### 10.3 命名规则

- API 名称从函数名生成，非标识符字符（空格、`.`、`/`、`\`、`@`）会替换成 `_`。
- 若重名会自动加数字后缀（如 `Foo_1`）。

### 10.4 注释解析

支持以下注释格式的参数描述：

- `// 参数名: 描述`
- `// 参数名=描述`
- Doxygen 风格 `@param 参数名 描述`

未提供描述的参数，生成时会给一个默认占位描述（如 `"AName parameter"`）。

---

**文档版本**：V1.0  
**维护者**：LingoFuse-pasAgent 团队  
**反馈**：问题提 Issue，急事加 Q（600585）