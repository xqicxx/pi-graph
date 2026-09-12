# pi-graph

把本机的 **Pi 生态**变成一张可查、可点、可操作的图 —— 提取器 + 自包含 HTML 控制面板 + 只读 MCP 服务。

## 它回答什么问题

- 哪个扩展提供了某个工具？这个包依赖谁、被谁依赖？
- skill / hook / command / MCP / provider 分别从哪来，装在哪，健康吗？
- **某个会话的每一轮花了多久、思考了多少字、调了哪些工具？**（会话层）

## 架构

```text
pi-graph.py ──► pi-graph.json ──► pi-graph-render.py ──► pi-graph.html
  (提取+增强)       数据              (右键UI/抽屉)            │
     ▲                                                       │ POST /api/action {action,id}
     │  refresh 后重跑                                       ▼
     └────────────────── pi-graph-serve.mjs (127.0.0.1 + token + 白名单 argv)

会话层：pi-graph.py sessions | session <id>   ← 直接读 ~/.pi/agent/sessions/**/*.jsonl
```

- **提取器** `pi-graph.py`：扫 settings / npm 包 / 扩展源码 / skills / MCP 配置 / 运行期工具注册表 → `~/.pi/agent/pi-graph.json`
- **渲染器** `pi-graph-render.py`：把数据内嵌进 d3-force 自包含 HTML（双击即可看）
- **服务** `pi-graph-serve.mjs`：给 HTML 提供动作接口（更新 / 重装 / 卸载 / 打开目录…）
- **MCP** `pi-graph-mcp.mjs`：把图和会话暴露成 6 个**只读**工具

## 快速开始

```bash
python3 pi-graph.py            # 提取 → ~/.pi/agent/pi-graph.json
python3 pi-graph-render.py     # 渲染 → ~/.pi/agent/pi-graph.html
python3 pi-graph.py serve      # 起本地动作服务（127.0.0.1，带 token）
python3 pi-graph.py --selftest # 自检
```

## 查询

```bash
pi-graph.py stats                # 节点/关系/健康/热度概览
pi-graph.py find <词>            # 按 id 或描述搜索
pi-graph.py show <节点id>        # 节点详情 + 全部相邻关系
pi-graph.py sessions [N]         # 最近 N 个会话（轮数/工具数/体积）
pi-graph.py session <id前缀>     # 单会话轮次链：每轮耗时、思考字数、工具调用
```

## MCP

stdio 传输，只读：

| 工具 | 作用 |
| --- | --- |
| `graph_stats` | 图概览 |
| `graph_find` | 搜索节点 |
| `graph_show` | 单节点详情与关系 |
| `graph_render` | 重新提取并重建 HTML |
| `session_list` | 最近会话清单 |
| `session_tree` | 单会话轮次链（每轮的上下文） |

挂载（mcp.json）：

```json
{ "mcpServers": { "pi-graph": { "command": "node", "args": ["/path/to/pi-graph-mcp.mjs"] } } }
```

## 安全边界

- **MCP 只读** —— 不给模型一个删除按钮
- 动作服务**只绑 127.0.0.1**，带 token；动作由服务端从图节点派生，客户端只发 `{action, id}`
- 执行用 `spawn(argv)`，**不做 shell 字符串拼接**，不接自由输入
- 破坏性动作：预览实际 argv + 二次确认 + 自动备份 `settings.json`，详情面板里可回滚
- **网页终端 `/api/shell` = 真正执行任意命令**，默认开启；不需要就用 `--no-shell` 起服务。
  它和 `/api/action` 的白名单是两回事：action 永远不执行请求体里的字符串，shell 就是干这个的
- 路径访问（`/api/file`）与删除（skill / 卸载残留）都做**真包含检查**（解析后必须在目标目录内）
- 请求体上限 1 MB；任何未捕获异常都变成 500，**单个坏请求不会带走服务**
- npm/git 变更**只在新会话生效**，面板固定提示

## 要求

- macOS / Linux，Python 3.11+
- Node 20+（只有服务与 MCP 需要）
- 默认路径 `~/.pi/`（Pi 的 agent 目录）

## 许可

未定（尚未添加 LICENSE）。
