# Pascal 函数/过程声明规范  
（兼容 Z.Pascal_Func_Tool + pascal_func_model）

**版本**：3.0  
**最后更新**：2026-09-02  
**宗旨**：以大量实例驱动，让开发者能直接模仿，确保代码被正确解析。

---

## 1. 适用范围

- 编译器：Delphi / Free Pascal（FPC）
- 提取范围：`interface` 部分**顶层**（非类、非记录、非接口内部）的 `function` 和 `procedure`。
- 忽略：`implementation` 部分、嵌套方法、类成员。

---

## 2. 基本声明规则（速查）

```pascal
interface

// ✅ 顶层函数
function Add(a, b: Integer): Integer;

// ✅ 顶层过程
procedure Log(const Msg: string);

type
  TMyClass = class
    // ❌ 不会提取（类方法）
    function Multiply(x, y: Integer): Integer;
  end;

implementation
  // ❌ 不会提取（实现部分）
  function InternalHelper: Boolean;
```

---

## 3. 注释规范（核心示例库）

本章节提供**大量可直接模仿的注释写法**，覆盖常见场景。

### 3.1 前导注释（必须紧邻声明）

```pascal
// 单行注释，紧邻
function NoParam: Integer;

{ 花括号注释 }
procedure Proc1;

(* 圆括号星号注释 *)
procedure Proc2;

{
  多行花括号注释
  第二行
}
function MultiLine: Integer;

(*
  多行圆括号注释
  第二行
*)
procedure MultiLineProc;
```

**禁止**：注释与声明之间有空行（否则绑定失败）。

---

### 3.2 参数描述提取（完整写法示例）

#### 3.2.1 冒号分隔（Pascal 经典风格）

```pascal
{
  计算两个整数的和。
  a: 第一个加数
  b: 第二个加数
}
function Add(a, b: Integer): Integer;
```

#### 3.2.2 等号分隔

```pascal
{
  计算乘积。
  a = 乘数1
  b = 乘数2
}
function Mul(a, b: Integer): Integer;
```

#### 3.2.3 空格分隔（至少一个空格，无显式符号）

```pascal
{
  计算差值。
  a  被减数
  b  减数
}
function Sub(a, b: Integer): Integer;
```

#### 3.2.4 Doxygen `@param` 风格

```pascal
{
  计算两个整数的和。
  @param a 第一个加数
  @param b 第二个加数
  @return 两数之和（忽略，因为无此参数）
}
function Add(a, b: Integer): Integer;
```

#### 3.2.5 简化 `@` 前缀（`@` 与参数名间可有空格）

```pascal
{
  计算商。
  @ a 被除数
  @ b 除数
}
function DivInt(a, b: Integer): Integer;
```

#### 3.2.6 反斜杠风格（`\param` 或 `\`）

```pascal
{
  计算余数。
  \param a 被除数
  \param b 除数
}
function ModInt(a, b: Integer): Integer;

{
  简化反斜杠。
  \ a 被除数
  \ b 除数
}
function ModInt2(a, b: Integer): Integer;
```

#### 3.2.7 混合风格（同一注释内可混用）

```pascal
{
  @param x 横坐标
  y: 纵坐标
  z = 深度
}
function Point3D(x, y, z: Integer): Integer;
```

#### 3.2.8 参数名大小写混用（不区分大小写）

```pascal
{
  A: 第一个数
  B: 第二个数
}
function Sum(a, b: Integer): Integer;   // 声明中使用小写，注释中用大写，仍能匹配
```

#### 3.2.9 跨行描述（同一参数的多行描述会合并）

```pascal
{
  a: 第一个加数
     这是第二行描述
  b: 第二个加数
}
function Add(a, b: Integer): Integer;
```
结果：`a` → `"第一个加数 这是第二行描述"`（用空格合并）。

#### 3.2.10 参数组（同类型参数）的注释写法

```pascal
{
  const a, b, c: 三个整数
  a: 第一个数
  b: 第二个数
  c: 第三个数
}
function GroupConst(const a, b, c: Integer): Integer;
```

#### 3.2.11 带修饰符（var / const / out）的参数注释

```pascal
{
  修改变量。
  const Input: 只读输入
  var Output: 可修改输出
  out Error: 错误码
}
procedure Modify(const Input: string; var Output: Integer; out Error: Integer);
```

#### 3.2.12 带默认值的参数注释

```pascal
{
  带默认值的函数。
  a: 第一个数（默认42）
  b: 第二个数（默认0）
}
function WithDefault(a: Integer = 42; b: Integer = 0): Integer;
```

#### 3.2.13 无参数但带注释（仅提取 Comment 字段，无参数描述）

```pascal
{
  这是一个无参数函数，仅用于演示。
}
function NoParamFunc: Integer;
```

#### 3.2.14 复杂注释（含非参数行，如分隔线、说明文字）

```pascal
{
  --------------------------------------------------------------------------
  高级计算函数。
  本函数执行复杂运算。
  @param a 第一个操作数
  @param b 第二个操作数
  @return 计算结果（忽略）
  --------------------------------------------------------------------------
}
function ComplexCalc(a, b: Double): Double;
```

---

## 4. 支持的类型（白名单）

| 原始类型 | 规范化类型 |
|----------|-----------|
| `Integer`, `Int64`, `Cardinal`, `Longint`, `DWord`, `Word`, `SmallInt`, `Byte`, `UInt64`, `LongWord` | `Int64` |
| `Double`, `Single`, `Extended`, `Real` | `Double` |
| `String`, `AnsiString`, `UnicodeString` | `string` |

**其他类型（如 `Boolean`, `Variant`, 数组, 记录, 类, 泛型, 函数指针）会导致整个声明被跳过**。

---

## 5. 调用约定与外部声明

### 5.1 调用约定
```pascal
function CdeclFunc(a: Integer): Integer; cdecl;
procedure StdcallProc(a: Integer; var b: Double); stdcall;
function RegisterFunc(a, b: Integer): Integer; register;
```

### 5.2 外部声明
```pascal
function ExternalLib(const Name: PChar): Boolean; cdecl; external 'my.dll';
procedure ExternalAlias; stdcall; external 'kernel32' name 'GetCurrentProcess';
procedure ExternalIndex; stdcall; external 'user32' index 10;
```

---

## 6. 默认参数值

```pascal
function WithDefaultInt(a: Integer = 42): Integer;
function WithDefaultString(s: string = 'default'): string;
```

---

## 7. 参数组与修饰符（完整示例）

```pascal
// 同类型参数组
function GroupConst(const a, b, c: Integer): Integer;

// var 组
procedure GroupVar(var x, y, z: Double);

// 混合组
function ComplexGroups(var a, b: Integer; const c: string; out d: Double): Integer;
```

---

## 8. 完整可解析单元示例

```pascal
unit SampleUnit;

interface

{ ---------------------------------------------------------------------------
  计算两个整数的和。
  @param a 第一个加数
  @param b 第二个加数
  @return 两数之和（忽略）
--------------------------------------------------------------------------- }
function Add(a, b: Integer): Integer;

{ 示例过程，无参数，带调用约定 }
procedure DoNothing; cdecl;

{ 带默认值和 var 参数的过程
  const Input: 只读输入
  var Output: 可修改的输出
  out Error: 错误码（Double类型）
}
procedure Process(const Input: string; var Output: Integer; out Error: Double = 0.0);

implementation

function Add(a, b: Integer): Integer;
begin
  Result := a + b;
end;

// 其他实现...
end.
```

---

## 9. 验证与调试

- 开启 `PascalFuncModel_LogEnabled := True;` 查看详细日志。
- 使用 `tpascal_func_decl_tool` 的 `ParseSuccess` 属性判断解析是否成功。
- 检查 `TFunctionStructure` 中的 `Params` 和 `Description` 字段。

---

## 10. 常见问题（FAQ）

| 问题 | 解决方法 |
|------|----------|
| 参数描述未提取 | 检查注释是否紧邻声明，参数名是否拼写正确，格式是否属于支持列表。 |
| 整个函数被跳过 | 检查参数或返回值类型是否在白名单内，若包含不支持类型（如 `Boolean`），则整个跳过。 |
| 注释绑定错误 | 确保注释与声明之间无空行。 |
| Doxygen 风格无效 | 确保 `@param` 和参数名之间允许有空格，但 `@` 和 `param` 必须相邻（或直接 `@a`）。 |
| 描述包含多余符号 | 避免在描述开头使用 `:` 或 `=`，解析器会尝试去除，但最好避免。 |

---

## 11. 扩展性说明

若需支持更多类型（如 `Boolean`）或自定义注释格式，可修改 `pascal_func_model` 中的 `NormalizeType` 和 `ExtractParamDescriptions`，但建议保持基础规范以保证工具链兼容。

---

**修订历史**：
- v3.0（2026-09-02）：以实例驱动，新增大量可直接模仿的注释写法，完善常见问题说明。