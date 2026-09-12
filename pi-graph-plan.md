# Pi 生态知识图谱 → 可交互控制面板（Plan）

> 2026-09-12。目标：右键节点 → 详情 / 更新 / 重装 / 卸载 / 打开目录，**复用已有三条管线，不重写**。

## 0. 现状（已存在，别重造）

| 件 | 位置 | 作用 |
| --- | --- | --- |
| 提取器 | `~/.pi/scripts/pi-graph.py` (317行) | 扫 settings/npm/扩展源码/skills/mcp/fabric/telegram → `~/.pi/agent/pi-graph.json`；带 CLI 查询 `stats/find/show/--selftest` |
| 渲染器 | `~/.pi/scripts/pi-graph-render.py` (187行) | 内嵌数据 → d3-force 自包含 HTML；点击=高亮邻居（**无右键**） |
| MCP | `~/.pi/scripts/pi-graph-mcp.mjs` (147行) | 图谱包 4 个只读工具（stdio） |
| 数据 | `~/.pi/agent/pi-graph.json` | 378 节点 / 410 边，`kind` ∈ package/sdk/tool/command/hook/skill/mcp/config；边 kind ∈ depends-on/provides/hooks/declares/configures/contains |
| 运行期注册表 | `~/.pi/agent/pi-registry.json` | 262 工具权威快照（fabric tools.list 导出） |

缺口 = **动作层**（只读 → 可写）+ **右键菜单/详情面板** + 少量字段（原始 spec、安装路径、版本、是否可写）。

## 1. 架构（3 层，文件数最少）

```text
pi-graph.py  ──► pi-graph.json ──► pi-graph-render.py ──► graph.html
   (提取+增强)        数据              (右键UI)              │
      ▲                                                     │ POST /api/action {action,id}
      │  refresh 后重跑                                     ▼
      └──────────────── pi-graph-serve.mjs (127.0.0.1, token, 白名单 argv)
```

- **不新增可视化代码**：沿用现有 HTML/CSS/d3 结构，只加 `contextmenu` + 抽屉 + 操作面板。
- **不让 MCP 带动作**：MCP 保持只读（不给 LLM 一个删除按钮）。
- **不重写 `pi config` 的启用/禁用**：菜单里「启用/禁用资源…」= 起一个终端跑 `pi config`（TUI 已有，Tab 切全局/项目）。

## 2. 动作矩阵（按节点 kind）

| kind | 右键项 | 落地命令 |
| --- | --- | --- |
| package | 详情 / 打开目录 / 打开仓库 / **更新** / **重装** / **卸载** / 启用禁用资源… | `pi update <spec>` · `pi remove <spec> && pi install <spec>` · `pi remove <spec>` |
| skill | 详情(预览 SKILL.md) / Finder 打开 / 启用禁用… / 删除（仅本机 `~/.pi/agent/skills/*`，包内 skill 只读） | `pi config` · `rm -rf`(二次确认) |
| mcp | 详情 / 编辑 mcp.json 条目 / 禁用 | 编辑器打开 `~/.pi/agent/mcp.json` |
| tool / hook / command | 只读详情 + 来源文件「在 Finder 显示」+ 归属包跳转 | `open -R` |
| provider | 详情（模型数、`pi auth` 就绪态）/ 打开 models.json | `pi auth print-...`（只读） |
| config | 详情 / 打开文件 | `open` |

规则：

- **command 只由服务端从图谱节点派生**，客户端只发 `{action, id}`；不接任何自由字符串、不走 shell 拼接（`spawn(argv)` 而非 `exec(str)`）。
- 破坏性动作（卸载/重装/删除 skill）先弹**预览行**（实际 argv）+ 二次确认；执行前自动备份 `settings.json` → `settings.json.bak-ui-<ts>`，详情抽屉里给「回滚」直接恢复对应 .bak。
- 所有 npm/git 变更**只在新会话生效** → 结果面板固定提示「已排队，重启 pi 会话生效」。
- git 包 ref 被 pin：更新项灰掉，显示「ref 已固定，无自动更新；改 ref 用 `pi install git:…@newref`」。

## 3. 分阶段

**P0 · 数据增强（`pi-graph.py`，~60 行改动）**
package 节点补 `spec`(settings 原始串，动作唯一依据) / `path` / `version`(读 package.json) / `gitRef` / `writable`；skill 补 `path` / `source`(local|package:X)；mcp 补 `configKey` / `file`。保持 `--selftest` 通过。

**P1 · 本地服务（新 `pi-graph-serve.mjs`，~120 行，Bun/Node 原生 http，无依赖）**
`GET /` → graph.html；`GET /graph.json`；`POST /api/action {action,id,confirm}` → 白名单执行 + SSE 流式日志；`POST /api/refresh` → 重跑 `pi-graph.py` 与 render，前端热替换数据。绑定 `127.0.0.1`，启动时随机 token 写进 URL（防同机浏览器跨站打到接口）。

**P2 · UI（`pi-graph-render.py`，~150 行改动）**
右键菜单（按 kind 生成，`contextmenu` → preventDefault）；详情抽屉（字段 / 邻居分组 / 来源路径 / 关联工具与 skill）；操作面板（命令预览 + 二次确认 + 流式输出 + 失败高亮）；顶部搜索框（378 节点必需）+ 按 kind 过滤；刷新时**沿用旧坐标**（同 id 保持 x/y，避免重排跳动）。

**P3 · 收口**
`pi-graph.py serve` 子命令（`--open` 直接开浏览器）；`--selftest` 断言 HTML 含 `contextmenu` 且内嵌脚本能被 `new Function()` 解析；README 三行写进脚本头注释。

**P4 · 之后（YAGNI，先不做）**
健康信号（包目录缺失 / 重复 spec / 依赖破损）、npm 最新版本对比、会话使用频次热力。

## 4. 验收（最小可失败检查，按序跑）

```bash
python3 ~/.pi/scripts/pi-graph.py --selftest                  # 1 提取器自检仍绿
jq -e '[.nodes[]|select(.kind=="package")|select(.spec and .path)]|length == 15' ~/.pi/agent/pi-graph.json
python3 ~/.pi/scripts/pi-graph.py show npm:pi-lens            # 2 查询仍可用且带新字段
python3 ~/.pi/scripts/pi-graph-render.py -o /tmp/g.html && grep -c contextmenu /tmp/g.html   # 3 UI 有右键
node ~/.pi/scripts/pi-graph-serve.mjs --port 8787 &           # 4 服务起来
curl -s localhost:8787/api/action -H 'x-token: …' -d '{"action":"preview","id":"npm:pi-lens"}'  # 4 只回显 argv，不执行
curl -s -X POST localhost:8787/api/refresh | jq .nodes         # 4 热刷新通路
```

端到端演练（安全动作）：对 `npm:pi-markdown-preview` 执行「重装」（remove+install 同 spec）→ 面板输出 ok → `pi list` 里仍在 → settings.json 多出一个 .bak-ui-*。

## 5. 已否掉的方案

- **重写为 TUI 面板（pi 扩展）**：d3 力导向图在 TUI 里没有等价物，且 `pi config` 已覆盖启用/禁用；图适合网页。
- **Electron / 打包桌面应用**：为一个本地图起壳，收益为零；`open graph.html` 足够。
- **让 MCP 暴露 action 工具**：等于给模型一个可删包的按钮，风险 > 便利。
- **纯静态版（右键只复制命令）**：零服务、零权限面，但用户明确要「更新/重装」一键 —— 保底降级方案，服务端可加 `--readonly` 开关一键退回。

---

## 已实现（2026-09-12）

| 文件 | 状态 |
| --- | --- |
| `~/.pi/scripts/pi-graph.py` | P0 完成：package 补 `spec/path/version/ref/pinned/installed/repo`，skill 补 `source/writable`，mcp 补 `file/configKey`；新增 `serve`；自检加了 spec/路径/右键 3 项断言 |
| `~/.pi/scripts/pi-graph-serve.mjs` | P1 完成：127.0.0.1 + token，动作全部由服务端从图谱派生，`--dry` 演练模式，破坏性动作自动备份 `settings.json.bak-ui-*` |
| `~/.pi/scripts/pi-graph-render.py` | P2 完成：右键菜单、详情抽屉、流式输出面板、搜索、图例筛选、刷新保持坐标（localStorage） |
| `~/.pi/scripts/pi-graph-serve.selftest.sh` | P3 完成：15 项 dry 检查 + `--drill` 真实重装演练，全绿 |
| `~/.pi/scripts/pi-config.sh` | 右键「pi config」的 Terminal 入口 |

用法：`python3 ~/.pi/scripts/pi-graph.py serve --open`（默认 8787，`--dry` 只看不跑）。

### 实现中修掉的 4 个真 bug

1. 运行期注册表先把扩展建成 `provider`，导致 `pi-lens` 等包节点拿不到 `spec` → 右键动作全部失效。改为 settings/npm 身份优先，强制 `kind='package'`。
2. SKILL.md 的 `name: "pdf"` 带引号 → 节点 id 变 `"pdf"`，抽屉与删除都定位不到。已 strip 引号。
3. 渲染模板是 Python 三引号串，JS 里的 `\n` 被 Python 提前消化，内联模块语法错误 → 模板改 raw string。
4. `/api/preview` 硬编码 action 名与 reveal 撞车，所有 preview 都返回 `open -R`。

### 教训（已修）

自检脚本第一版把 dry 断言写在 drill 模式也执行的位置，结果**真的卸载了 pi-lens**（已用 `pi install npm:pi-lens` 装回，4.1.5 → 4.1.6）。现在 dry 断言被 `if [ $DRILL -eq 0 ]` 圈起来了。

---

## 像素风 + 上线版（2026-09-12 第二轮）

### 视觉

- 主题换 **像素 / CRT**：调色板取自 commandcode.ai 实际站点色（`#7B5BFF` / `#A48CFF` / `#A7EADC` / `#F3B5D2` / `#e06c75`），全套写在 `pi-graph-render.py` 顶部的 `PALETTE`，换皮肤只改这一处。
- 字体 VT323（正文）+ Press Start 2P（标题），**base64 内联**；d3 7.9 内联（`vendor/`）→ 整页 450KB 自包含，断网可用。
- CRT 扫描线 + 暗角覆盖层；节点改成像素符号（tool 方块 / skill 菱形 / hook 十字 / command 三角 / mcp 叉）。
- 标签按缩放分层出现（tool 要 k≥1.1，hook k≥0.8），避免 379 节点糊成一团。
- 按 kind 做了方位锚定（技能左下 / SDK 上方 / 配置右上…），布局不再一坨。

### P4 健康信号（全部本地、零网络）

`missing`（声明了但目录不在）/ `broken-deps`（依赖残缺）/ `duplicate`（重复声明）/ `inactive`（MCP 声明了没加载）。当前 6 条：5 个 MCP inactive + pi-browser-harness 缺 `tsx`。

### P4 使用热度

扫 `~/.pi/agent/sessions/*.jsonl`（201 文件 / 130MB，**0.7s**），统计 `toolCall` 名 + fabric 里的 `pi.xxx` 引用 + skill 被读次数；页面上热度高的节点带发光方框，抽屉里显示「调用 N 次」。
ponytail: 目前全量扫；涨到 GB 级再加 mtime 缓存。

### P4 检查更新 / MCP 自检

- `POST /api/updates` 查 npm registry，6 小时文件缓存 → 按钮一键标记可升级节点（本次实测 5 个可升级），右键「更新」自动解除禁用。
- `POST /api/mcptest` 真起 MCP 进程走 `initialize` + `tools/list`。实测 context7：`Context7 4.1.0 · 2 个工具`。

### 验收（四套，全绿）

```bash
python3 ~/.pi/scripts/pi-graph.py --selftest      # 378 节点 / 6 健康
python3 ~/.pi/scripts/pg-selftest.py             # 页面结构 + 内联模块语法 + 数据一致
~/.pi/scripts/pi-graph-serve.selftest.sh         # 17 项 dry（含 updates/mcptest 不联网）
~/.pi/scripts/pi-graph-serve.selftest.sh --drill # 真实重装 + 回滚
~/.pi/scripts/pg-snap.sh <url> out.png           # 无头 Chrome 截图（UI 回归）
```

## 列表视图方案（不是图谱的那种）

### 要解决什么

图谱擅长「看关系」，不擅长「找坏的 / 比版本 / 批量操作」。379 个节点里想找「哪个包缺依赖」「谁好久没更新」「把所有能更的一次更完」—— 在力导向图里就是大海捞针。列表视图 = 同一份数据、同一套动作，换个更适合筛选和批量操作的皮。

### 核心思路：一个数据源，两种渲染，零后端改动

前端已经有 `actionsOf(n)` / `show(id)` / `openMenu(ev,d)` / `runAction()` / `applyFilters()`，列表只是把同一批函数换个 DOM 容器调一遍。右侧详情抽屉、右键菜单、底部输出面板**全部原样复用**，不重复实现。

```text
DATA.nodes ──┬── render()      力导向图（d3 + canvas-less SVG）
             └── renderList()  表格（纯 DOM <table>，无依赖）
                   ↑ 共用：hiddenKinds / healthOnly / 搜索词 / 动作 / 抽屉
```

### 视图切换

- Header 加一个按钮：`✦ 图谱 ⇄ ▤ 列表`，状态写进 URL hash（`#list` / `#graph`），刷新不丢。
- 键盘：`v` 切换视图，`/` 聚焦搜索，`↑↓` 选行，`Enter` 开抽屉，`Esc` 关（现有 keydown 处理器已经处理了 `/` 和 `Esc`，加两个分支）。
- 列表模式下 `svg` 隐藏、不跑 d3 模拟（省电，也避免后台力导向白烧 CPU）；切回图谱时复用缓存的坐标。
- 只读模式（file:// 直开）列表照样可用 —— 纯 DOM，不需要服务端。

### 表格长什么样

列：`名称 | 类型 | 版本 | 来源(spec) | 健康 | 热度 | 连接 | 操作`

- 名称前放对应 kind 的色块，跟图谱颜色一致；点表头排序（名称/版本/热度/连接），默认「热度降序」。
- 健康列把 `missing / broken-deps / duplicate / inactive` 显示成像素徽章，颜色复用 `HEALTH_COLOR`。
- 热度列画一条微型条形（`width: log(usage)`），比数字更容易一眼扫出冷热。
- 操作列直接放 `更新 / 重装 / 卸载` 小按钮，跟右键菜单**同一套函数**；右键行也弹同一个菜单。
- 顶栏一行筛选 chip：`全部 / 仅包 / 仅技能 / 有问题的 / 可升级`，跟图谱的图例筛选共享同一份状态（`hiddenKinds` / `healthOnly`），切视图不丢筛选。
- 379 行不需要虚拟滚动，直接全量渲染，CSS `position:sticky` 固定表头。

### 顺带把「批量更新」补上

列表天然适合多选：行首复选框 + 表头全选，选中后出现「批量更新 (N)」。

- 服务端加 `POST /api/bulk {action, ids[]}`：把每个 id 的 argv 依次算出来，**先整段回显让你确认**，再顺序执行（一个失败就停，不并发，避免 npm 打架）。
- 依然走原有白名单派生逻辑，不引入任何来自请求体的字符串。
- 批量卸载/重装同样只对这些 id 生效，执行前备份一次 settings.json。

### 分步实现（都在现有文件里，不新增文件）

1. `pi-graph-render.py`：加 `let view = location.hash === '#list' ? 'list' : 'graph'`、`setView()`、header 按钮、hash 监听。约 30 行。
2. 加 `renderList()`：构建 `<tbody>`，套用现有筛选状态；行点击 → `show(id)`，右键 → `openMenu(e, node)`。约 110 行。
3. 加列表 CSS（像素风表格、zebra、hover、选中态、sticky thead、健康徽章、热度条）。约 70 行。
4. `applyFilters()` 里加一行：列表模式下重绘表格。约 3 行。
5. 服务端 `/api/bulk` + 前端多选栏。约 60 行。
6. 测试：`pg-selftest.py` 加断言（有 `renderList`、有视图切换按钮、`#list` 时表格行数 == 节点数）；`pg-snap.sh` 各截一张图谱/列表图做视觉回归。

合计约 270 行，1 个前端文件 + 服务端一个小接口，无新依赖。

### 验收

```bash
python3 ~/.pi/scripts/pg-selftest.py                     # 加视图断言后仍全绿
~/.pi/scripts/pg-snap.sh "file://$HOME/.pi/agent/pi-graph.html#list" /tmp/list.png   # 列表能出图
~/.pi/scripts/pi-graph-serve.selftest.sh                 # 原有 17 项不受影响
# 交互一致性：列表里点「更新」与图谱里点「更新」派生出完全相同的 argv（共用 runAction → /api/preview）
```

### 不做

- 不做第二套独立的列表页 / 第二个 HTML 文件（同一页面切视图，状态、筛选、抽屉全共享）。
- 不引表格库（ag-grid / tanstack-table）：379 行、固定列，原生 `<table>` 够用。
- 不做虚拟滚动（真要上万节点再说）。
- 不做列拖拽/自定义列（YAGNI）。

### 已知取舍

- 浏览器 harness 连不上（`/browser-setup` 起不了 daemon），视觉迭代改用无头 Chrome 截图；已封装成 `pg-snap.sh`。
- 页面里 `pi.bash` 这类节点显示为 tool 节点（id 带 `pi.` 前缀），值来自 fabric 引用计数。
- 健康信号只覆盖本地可判定项；`inactive` 可能只是这个会话没用到该 MCP，不等于配置坏了。

---

## 三视图 + 开箱即用（2026-09-12 第三轮）

### 新增：流程视图（n8n / Dify 那种节点画布）

用户给了张参考图（VipSkill 的 AI Agent 工作流截图），要求照那个路子做。实现的对应关系：

| 参考图元素 | 实现 |
| --- | --- |
| 点阵网格背景 | `<pattern id="dots">` 平铺，24px 间距 |
| 圆角卡片 + 彩色描边 | `.fcard` rx=10，描边色 = kind 色 |
| 卡片里的图标 | `GLYPH` 表：9 种 kind 各画一条纯 path 矢量图标（无字体依赖） |
| 卡片底部灰色菱形端口 | `.fport` 菱形 path |
| 虚线贝塞尔连线 | `flowCurve()`，按边 kind 上色（声明/提供/钩子/依赖） |
| 圆形叶子节点 + ✓ | `.fleaf`，健康且已安装才画 ✓ |
| 「1 item」小标签 | 卡片副标题：版本 · 使用次数 · 出边数 |
| 「+N」折叠 | 每卡最多展开 5 个子节点，其余折成 +N |

布局是分层的：配置在最上（settings.json / mcp.json），包/扩展居中按热度排，能力（工具/钩子/技能/子包）以圆节点挂在各自卡下。

**迭代中修掉的真 bug**

1. 流程图层建出来时带 `display:none`，而 `setView` 早就跑过了 → 图层永远不显示、`getBBox()` 返回空。
2. `fitFlow()` 把平铺整个屏幕的背景网格算进包围盒 → 缩到只剩 3% 大。改成只量内容层，并加 `.72` 缩放下限（宁可让用户往下拖，也别把字缩到看不清）。
3. 我一次编辑里写出了重复的 `const bb` → SyntaxError，页面全白。自检（`pg-selftest.py` 的内联模块语法检查）当场抓到。

### 开箱即用（重点）

原先要手工跑 `pi-graph.py serve --open` 并带 `?token=`，现在：

- **常驻后端**：`pi-graph-agent.sh install` 装 launchd（`com.cx.pi-graph`，`KeepAlive`）→ 登录自启、崩了自动拉起。
- **固定 token**：存在 `~/.pi/agent/pi-graph.token`（0600），由 `pi-graph.py token` 单一来源生成，渲染时内联进 HTML，后端读同一份 → **双击 HTML 就能直接改**，不用带参数。
- **CORS + `/api/ping`**：`file://` 页面能调 127.0.0.1；ping 免 token 可探活，带对 token 返回 `tokenOk`，页面据此显示「动作已连接 / 后端未连」。
- 顶部按钮列：`PI GRAPH` · 搜索 · 重新扫描 · 检查更新 · 视图切换 · 状态徽章 · 统计。

### 迭代中另外修掉的 3 个真 bug

1. `ping()` 没带 token 头 → `tokenOk` 永远是 false，页面永远显示只读（功能性 bug，靠浏览器测试抓到）。
2. `window.piGraph = {... api ...}` 写在 `const api` **之前** → TDZ 报错，整个模块挂掉，页面全白。
3. 列表行 `contextmenu` 没 `stopPropagation` → document 上的「点空白关菜单」在同一个事件里把菜单立刻关掉。
4. `renderList()` 重绘后没重画选中态 → 勾选完一重排，行高亮就没了。

### 验收（5 套）

```bash
python3 ~/.pi/scripts/pi-graph.py --selftest          # 提取器
python3 ~/.pi/scripts/pg-selftest.py                  # 页面结构 + 内联模块语法 + 数据一致性
node ~/.pi/scripts/pg-ui-test.mjs                     # 24 项浏览器真实交互（CDP，含 file:// 可写性）
~/.pi/scripts/pi-graph-serve.selftest.sh              # 24 项动作/批量/安全边界
~/.pi/scripts/pi-graph-serve.selftest.sh --drill      # 真实重装 + 回滚
~/.pi/scripts/pg-snap.sh <url> out.png                # 三视图截图回归
```

`pg-ui-test.mjs` 覆盖：默认进列表、默认筛包、file:// 连上后端、搜索收敛、多选批量、表头排序、拿到真实 argv、行右键菜单、抽屉让位、三视图循环、流程卡片/圆节点/连线/点阵/可见图层/缩放、流程节点右键。

### 已知边界

- 流程视图一屏放不下 379 个节点：节点数是固定的 47 张卡 + 110 个圆节点，其余折成 +N。想全展开得先删节点或换大屏。
- 浏览器 harness 仍连不上（daemon 起不来），视觉迭代继续走无头 Chrome 截图。
- `pg-ui-test.mjs` 依赖 Chrome 路径，换机器要改 `CHROME` 常量。

---

## 网页终端 + 卸载残留清理（2026-09-12 第四轮）

### 网页终端（点一下就跑）

底部终端面板，`▮ 终端` 按钮或 `Ctrl+\`` 开关。

- **执行**：`POST /api/shell {cmd}` → `$SHELL -lc <cmd>`，stdout/stderr 流式回传，结束打 `[exit N]`
- **停止**：`AbortController` 中断 fetch，服务端 `res.on('close')` 收掉子进程（SIGTERM → 1.5s 后 SIGKILL），不留孤儿
- **预设**：`pi list` / `pi --version` / 图谱统计 / 自检 / 后端状态 / 磁盘占用，点一下直接跑；「更新全部扩展」带 ⚠ 会先确认
- **历史**：↑↓ 翻，存 localStorage（上限 200 条）
- **右键联动**：节点菜单多一条「在终端运行… <猜测命令>」—— 包给 `npm view X version`，残留给 `du -sh <path>`，skill 给 `cat SKILL.md`。**只预填不自动执行**

**安全边界（这是新增的信任面，刻意与白名单动作分开）**

| 措施 | 实现 |
| --- | --- |
| 独立端点 | `/api/shell` 不与 `/api/action` 共用任何代码；action 依旧永不含请求体字符串 |
| 开关 | `--no-shell` 完全关闭（前端仍显示按钮但后端 403） |
| 鉴权 | x-token，未带/带错 → 403 |
| 入参 | 空命令 400、超 4000 字符 400、非 JSON 400 |
| 监听 | 仅 127.0.0.1 |
| 提示 | 面板常驻黄字「在本机执行任意命令」 |

**PATH 修复**：登录 shell 的 PATH 里没有 `~/.local/share/node/bin`，网页终端输 `pi list` 会 command not found。现在把 `dirname(process.execPath)`、`~/.local/share/node/bin`、`~/.pi/agent/bin`、homebrew 目录显式前置。

**顺带修的真 bug**：5 处流式 `writeHead` 只写了 `content-type`，**漏了 CORS** —— `file://` 页面调 `/api/shell`、`/api/action`、`/api/refresh` 全被浏览器拦掉（之前只有 `json()` 带了 CORS，那次修的是 JSON 端点）。

### 卸载残留清理

用户报「我卸载 hermes 结果没动静」——根因是 **`pi remove` 只改 settings.json，不删目录**，删完包就没有 `spec`，界面上连动作都不显示，看着像没生效。

- 提取器新增 `leftover` 健康标记：npm 与 agent 顶层里 `pi-*` 目录，既不在 settings、也不被其他包依赖的，标出来并算体积
- 当前 5 个残留 / 14.8 MB（hermes 14.5 MB 是大头）
- 新增 `rmLeftover` 动作：`mv <dir> ~/.Trash/<name>-<ts>` —— **移到废纸篓而非 rm**；边界卡死 `health==leftover` 且路径在 `~/.pi/agent/` 下

### 陈旧页面提醒

`file://` 标签页永不自动刷新 —— 我重建 HTML 十几次，用户那个标签页还停在最早版本。现在 `/api/ping` 返回 `htmlMtime`，页面每 9 秒（含切回标签页时）比对，过期就弹「页面已更新（当前是旧副本）· 点此重新载入」。

### 测试基建修的两个 bug

1. `pg-ui-test.mjs` 的 URL 默认值是个坏三元：默认串含 `#` 时返回 `process.argv[2]`（无参时 = undefined）→ 不传参必崩。
2. Chrome 常同时开着 `about:blank`，`firstPage()` 挑目标页时可能挑到空页 → 满屏假失败。改为按 URL 匹配。
3. 另：清理了 10 个崩溃残留的无头 Chrome 僵尸进程与泄漏的 profile 目录。

### 六套验收

```bash
python3 pi-graph.py --selftest      # 提取器 381 节点 / 健康 11
python3 pg-selftest.py              # 页面结构 + 内联语法
./pi-graph-serve.selftest.sh        # 动作白名单 + 批量 + 安全边界
node pg-fail-test.mjs               # 失败必须提醒
node pg-term-test.mjs               # 终端：开关/执行/退出码/预设/历史（新增）
node pg-ui-test.mjs                 # 三视图真实交互 24 项
```

---

## 实时同步（2026-09-12 第五轮）

**要解决**：改个包 / 装个扩展之后，页面还停在旧数据上，得手点「重新扫描」。

### 做法：SSE 推送 + 原地换数据

- 服务端 `GET /api/events`（EventSource）：`graph` 事件 = 图谱变了，`html` 事件 = 页面本身要重载
- 检测用**轮询 mtime**（1.5s 一次，只在有人连着时才 stat）而不是 `fs.watch` —— macOS 上 rename-替换式写入会丢事件
- 前端收到 `graph` → 拉一次 `/graph.json` → **原地替换 nodes/links**，按当前视图重渲染，**不整页刷新**
  （整页刷新会把终端输出、滚动位置、筛选、选中全丢掉）
- 350ms 抖动合并：一次保存可能触发多次 mtime 变化
- 25s 心跳注释帧，防中间层掐长连接
- 断线指数退避重连（1–6s），ping 也兜底触发重连
- 顶部 `#live` 徽章：`● 实时` / `◌ 实时…` / `○ 实时关`
- `--no-live` 完全关闭

### 迭代中修的真 bug

**`byId` 只在 `render()` 里重建** —— 列表视图和流程视图不走 `render()`，实时同步后新节点查不到（行数变了但 `node('pi-livetest')` 是 undefined）。把索引领取抽成 `indexGraph()`，`applyGraph()` 里先重建索引再渲染。顺手给增量数据加了「对端还没到的边」防御。

### 测试：`pg-live-test.mjs`（新增）

真造一个假包 `pi-livetest` → 重扫 → 断言：

- SSE 点亮、**页面没被整页刷新**（打 `window.__noReload` 标记）
- 行数变了、新节点能在页面里查到、实时 toast 弹出过
- 删掉假包再重扫 → 节点自动消失

**测试自身的两个坑（已修）**：

1. 实时 toast 2.2 秒就消失，等 6 秒再查必然查不到 → 改用 `MutationObserver` **累计**弹出次数，而不是看那一刻还在不在。
2. `execSync` 拼 shell 字符串 → 改 `execFileSync` 固定 argv（本仓库对命令拼接有静态检查，这是对的）。

### 七套验收

```bash
python3 pi-graph.py --selftest      # 提取器 376 节点 / 健康 6
python3 pg-selftest.py              # 页面结构 + 内联语法
./pi-graph-serve.selftest.sh        # 动作白名单 + 批量 + 安全边界
node pg-fail-test.mjs               # 失败必须提醒
node pg-term-test.mjs               # 网页终端
node pg-ui-test.mjs                 # 三视图真实交互
node pg-live-test.mjs               # 实时同步（新增）
```

---

## spawn pi ENOENT（2026-09-12 第六轮）

**现象**：在页面上点「更新 pi-web-access」，日志只有 `!! spawn pi ENOENT`，界面上像是「点了没反应」。

**根因**：launchd 拉起的进程只拿到 `PATH=/usr/bin:/bin:/usr/sbin:/sbin`，而 `pi` 装在 `~/.local/share/node/bin`。
上一轮我只给**网页终端**加了 PATH（`SHELL_ENV`），白名单动作 `run()`、MCP 自检 `mcpTest()`、重扫 `refreshSoon()` 还在用裸 `process.env.PATH` —— 正好是用户最常用的那条路径。

**修复**：

- `SHELL_ENV` → `EXEC_ENV`，**所有子进程共用**（8 处），不再各写一份
- 新增 `which()` 工具 + **启动自检**：PATH 里找不到 `pi` 就打警告，别等用户点了才发现
- ENOENT 不再把 errno 甩给用户：`找不到命令「pi」。服务是由 launchd 拉起来的，PATH 可能不含它所在目录。`

**回归测试**（`pi-graph-serve.selftest.sh` 新增 3 项）：用 `env PATH=/usr/bin:/bin:/usr/sbin:/sbin` 启动服务复现真实环境。
注意要用 **node 的绝对路径**启动 —— node 自己也在 homebrew 目录里，直接写 `node` 会因为找不到 node 而测不到目标。
这个坑原来的套件测不出来：直接跑服务会继承 shell 的完整 PATH，永远绿。

**教训**：同一个进程里有两套环境（终端 / 动作），只修一套等于没修。
