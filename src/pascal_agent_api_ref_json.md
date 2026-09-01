以下是一个**完整且独立**的 JSON 示范，它同时涵盖了 **`agent_main` 返回的完整工具列表结构** 和 **`register_agent` 注册时使用的单个工具结构**。我将两者结合在一个完整示例中，并逐字段给出详细说明。

---

### 完整 JSON 示范（包含两个工具的完整定义）

```json
{
  "tools": [
    {
      "name": "add",
      "description": "计算两个整数的和，返回 a + b 的结果",
      "target_app": "my_calculator",
      "target_api": "add",
      "parameters": {
        "type": "object",
        "properties": {
          "a": {
            "type": "integer",
            "description": "第一个加数，必须为整数"
          },
          "b": {
            "type": "integer",
            "description": "第二个加数，必须为整数"
          }
        },
        "required": [
          "a",
          "b"
        ]
      }
    },
    {
      "name": "echo",
      "description": "回显输入的消息，支持可选的大写转换",
      "target_app": "my_echo_service",
      "target_api": "echo",
      "parameters": {
        "type": "object",
        "properties": {
          "message": {
            "type": "string",
            "description": "要回显的消息内容"
          },
          "uppercase": {
            "type": "boolean",
            "description": "是否将消息转换为大写后返回",
            "default": false
          }
        },
        "required": [
          "message"
        ]
      }
    }
  ]
}
```

---

### 逐字段说明

| 路径 | 类型 | 是否必须 | 说明 |
|------|------|----------|------|
| **`tools`** | `array` | ✅ 必须 | 顶级字段，包含所有已注册工具的数组。每个数组元素是一个工具定义对象。 |
| **`tools[]`** | `object` | ✅ 必须 | 单个工具定义对象。 |
| `tools[].name` | `string` | ✅ 必须 | **工具名称**。MCP 客户端通过此名称调用工具（如 `tools/call` 中的 `name`）。在整个工具列表中必须唯一。 |
| `tools[].description` | `string` | ✅ 必须 | **工具描述**。AI 模型根据此描述判断是否调用该工具，应清晰说明功能和使用场景。 |
| `tools[].target_app` | `string` | ✅ 必须 | **LingoFuse 目标应用名称**。用于 `LF_Call` 路由，必须与后端 Pascal 服务中 `LF.TAppHandle.Create` 的第一个参数（`APP_NAME`）完全一致。 |
| `tools[].target_api` | `string` | ✅ 必须 | **LingoFuse 目标 API 名称**。用于 `LF_Call` 路由，必须与后端 Pascal 服务中 `App.RegisterCall` 的 API 名称完全一致。 |
| `tools[].parameters` | `object` | ✅ 必须 | **参数定义（JSON Schema 子集）**。描述该工具接受哪些参数及其类型。 |
| `parameters.type` | `string` | ✅ 必须 | 必须固定为 **`"object"`**，表示参数是一个 JSON 对象。 |
| `parameters.properties` | `object` | ✅ 必须 | **参数属性定义**。键为参数名，值为该参数的 Schema 定义。 |
| `properties.<key>.type` | `string` | ✅ 必须 | 参数的数据类型。支持：`string`、`integer`、`number`、`boolean`、`array`、`object`。 |
| `properties.<key>.description` | `string` | ❌ 强烈推荐 | 参数的说明文字，帮助 AI 理解该参数的含义和用法。 |
| `properties.<key>.default` | 任意 | ❌ 可选 | 参数的默认值。如果调用时未传递该参数，则使用此值。 |
| `parameters.required` | `array` | ❌ 可选 | **必填参数列表**。数组元素为 `properties` 中的键名。未列在此处的参数均为可选参数。 |

---

### 补充说明

- **`register_agent` 注册时**：请求体应为 **单个工具对象**（即去掉外层的 `"tools": [...]` 包装），例如 `{"name":"add","description":"...",...}`。
- **`agent_main` 返回时**：必须使用完整的 `{"tools": [...]}` 结构，因为 MCP 服务器期望一个数组列表。
- **`target_app` 和 `target_api` 的一致性**：信标服务（`pascal_agent_service`）在 `agent_main` 中会调用 `LF_CheckApiEx` 验证这两个字段对应的 API 是否真实可用，因此必须与已启动的后端服务完全匹配。