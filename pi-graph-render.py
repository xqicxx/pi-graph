#!/usr/bin/env python3
"""把 pi-graph.json 渲染成自包含的交互式力导向图（d3-force）。

用法:  python3 pi-graph-render.py [-o 输出.html] [--open]
输入:  ~/.pi/agent/pi-graph.json（由 pi-graph.py 生成）

右键 = 动作菜单（详情 / 更新 / 重装 / 卸载 / 删除 / 连接测试…）。
动作要连到 pi-graph-serve.mjs 才有后端；直接 file:// 打开是只读模式。
d3 与像素字体都内联（vendor/），断网也能看。
"""

import argparse
import base64
import json
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
AGENT = HOME / ".pi" / "agent"
SRC = AGENT / "pi-graph.json"
VENDOR = Path(__file__).resolve().parent / "vendor"

# 调色板（取自 commandcode.ai 实际站点色 + 终端像素风）。想换皮肤只改这里。
PALETTE = {
  "bg": "#0c0c0c",
  "panel": "#121018",
  "line": "#241f33",
  "ink": "#e0e0e0",
  "dim": "#8a86a0",
  "accent": "#7B5BFF",
  "accent2": "#A48CFF",
  "good": "#A7EADC",
  "warn": "#F3B5D2",
  "bad": "#e06c75",
  "info": "#AFCDF6",
}

COLORS = {
  "package": "#7B5BFF",
  "sdk": "#A48CFF",
  "tool": "#A7EADC",
  "command": "#F3B5D2",
  "hook": "#e06c75",
  "skill": "#AFCDF6",
  "mcp": "#C7B8F5",
  "config": "#6f6a86",
  "group": "#3a3448",
}

HEALTH_COLOR = {
  "missing": "#e06c75",
  "broken-deps": "#e06c75",
  "duplicate": "#F3B5D2",
  "inactive": "#6f6a86",
  "leftover": "#F3B5D2",
}
HEALTH_LABEL = {
  "missing": "目录不在",
  "broken-deps": "依赖残缺",
  "duplicate": "重复声明",
  "inactive": "未加载",
  "leftover": "卸载残留",
}

HTML = r"""<!doctype html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PI GRAPH // 生态知识图谱</title>
<style>
@font-face{font-family:'PixelBody';src:url(data:font/woff2;base64,__FONT_VT__) format('woff2');font-display:swap}
@font-face{font-family:'PixelHead';src:url(data:font/woff2;base64,__FONT_P2P__) format('woff2');font-display:swap}
:root{
  --bg:__P_BG__; --panel:__P_PANEL__; --line:__P_LINE__; --ink:__P_INK__;
  --dim:__P_DIM__; --accent:__P_ACCENT__; --accent2:__P_ACCENT2__; --good:__P_GOOD__;
  --warn:__P_WARN__; --bad:__P_BAD__; --info:__P_INFO__;
}
*{box-sizing:border-box}
html,body{margin:0;height:100%;background:var(--bg);color:var(--ink);overflow:hidden;
  font:15px/1.35 PixelBody,ui-monospace,Menlo,monospace;-webkit-font-smoothing:none}
body::after{ /* CRT 扫描线 + 暗角 */
  content:'';position:fixed;inset:0;pointer-events:none;z-index:99;
  background:repeating-linear-gradient(to bottom,rgba(0,0,0,.16) 0 1px,transparent 1px 3px),
             radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.45));
  mix-blend-mode:multiply}
header{position:fixed;inset:0 0 auto 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap;
  padding:8px 14px;background:linear-gradient(var(--bg) 78%,transparent);z-index:5;
  border-bottom:2px solid var(--line)}
h1{font:13px PixelHead,ui-monospace,monospace;margin:0;color:var(--accent2);
  text-shadow:2px 2px 0 #000;letter-spacing:.06em}
.stat{color:var(--dim);font-size:13px}
.stat b{color:var(--good);font-weight:400}
.stat i{color:var(--bad);font-style:normal}
button,#q{font:inherit;color:var(--ink);background:var(--panel);border:2px solid var(--line);
  padding:3px 9px;cursor:pointer;border-radius:0}
button:hover{border-color:var(--accent);color:#fff;background:#1b1630}
button:active{transform:translate(1px,1px)}
#q{min-width:210px;outline:none;color:var(--good)}
#q::placeholder{color:#5b5670}
#q:focus{border-color:var(--accent2)}
#mode{font-size:12px;padding:3px 8px;border:2px solid var(--line);color:var(--dim)}
#mode.on{color:var(--good);border-color:var(--good)}
#mode.off{color:var(--warn);border-color:var(--warn)}
#live{font-size:12px;padding:3px 8px;border:2px solid var(--line);color:var(--dim);cursor:default}
#live.on{color:var(--good);border-color:var(--good)}
#live.wait{color:var(--info);border-color:var(--info)}
#live.off{color:var(--dim)}
main{position:fixed;inset:0}
svg{display:block;width:100vw;height:100vh;cursor:crosshair}
.lbl{font:12px PixelBody,monospace;fill:#d8d3ea;pointer-events:none;user-select:none;
  paint-order:stroke;stroke:#08070c;stroke-width:3px;stroke-linejoin:round}
.link{stroke:var(--line)}
#legend{position:fixed;left:12px;bottom:12px;display:flex;flex-direction:column;gap:2px;z-index:5;
  max-height:44vh;overflow:auto;opacity:.62;transition:opacity .12s;
  padding:5px 6px;background:#0c0c0ccc;border:2px solid var(--line)}
#legend:hover{opacity:1}
.li{display:flex;align-items:center;gap:7px;font-size:13px;color:var(--dim);cursor:pointer;
  user-select:none;padding:1px 6px;border:2px solid transparent}
.li:hover{border-color:var(--line)}
.li.off{opacity:.35;text-decoration:line-through}
.dot{width:10px;height:10px;flex:none}
#thr{position:fixed;right:14px;bottom:12px;color:var(--dim);font-size:12px;z-index:5;text-align:right;
  background:#0c0c0ccc;border:2px solid var(--line);padding:5px 8px}
#tip{position:fixed;pointer-events:none;padding:6px 8px;background:#0d0b14f2;border:2px solid var(--accent);
  font-size:13px;max-width:340px;opacity:0;transition:opacity .1s;z-index:20;color:var(--ink)}
#tip b{color:var(--good)}
#tip .k{color:var(--accent2)}
#menu{position:fixed;z-index:30;min-width:264px;padding:4px;background:#0d0b14f8;
  border:2px solid var(--accent);box-shadow:6px 6px 0 #000a;display:none;font-size:13px}
#menu .mi{padding:4px 8px;display:flex;gap:14px;justify-content:space-between;cursor:pointer;
  white-space:nowrap;border:2px solid transparent}
#menu .mi:hover{background:#241b45;border-color:var(--accent2)}
#menu .mi.danger{color:#ffc9d4}
#menu .mi.danger:hover{background:#3d1b22;border-color:var(--bad)}
#menu .mi.off{color:#57516b;cursor:default}
#menu .mi.off:hover{background:none;border-color:transparent}
#menu .k{color:#6b6483;font-size:12px}
#menu hr{border:0;border-top:2px solid var(--line);margin:3px 0}
#drawer{position:fixed;top:0;right:0;bottom:0;width:392px;background:var(--panel);
  border-left:2px solid var(--accent);transform:translateX(102%);transition:transform .14s steps(4,end);
  overflow:auto;z-index:25;padding:14px 16px 90px}
#drawer.open{transform:none}
#drawer h2{font:13px PixelHead,monospace;margin:0 0 6px;color:var(--accent2);word-break:break-all}
#drawer .kind{font-size:12px;color:var(--dim);margin-bottom:10px}
.badge{display:inline-block;padding:1px 6px;margin-right:5px;border:2px solid;font-size:12px}
.f{display:flex;gap:8px;font-size:13px;padding:3px 0;border-bottom:2px solid #1a1726}
.f b{color:var(--dim);font-weight:400;min-width:72px;flex:none}
.f span{color:#d6d0ea;word-break:break-all}
.sec{margin-top:14px;font-size:12px;color:var(--accent2);letter-spacing:.04em}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}
.chip{background:#161326;border:2px solid var(--line);padding:1px 7px;font-size:12px;color:#b6afd0;
  cursor:pointer}
.chip:hover{border-color:var(--accent2);color:#fff}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.acts button{font-size:13px}
.acts button.danger{color:#ffc9d4;border-color:#4a2231}
.acts button.danger:hover{background:#3d1b22;border-color:var(--bad)}
.x{position:absolute;top:10px;right:14px;cursor:pointer;color:var(--dim);font:13px PixelHead,monospace}
.x:hover{color:var(--bad)}
#panel{position:fixed;right:0;bottom:0;width:min(600px,54vw);height:0;display:flex;flex-direction:column;
  background:#0d0b14f7;border-left:2px solid var(--accent);border-top:2px solid var(--accent);
  z-index:28;transition:height .14s steps(4,end)}
#panel.open{height:46vh}
#panel .bar{display:flex;justify-content:space-between;padding:5px 10px;border-bottom:2px solid var(--line);
  font-size:12px;color:var(--accent2)}
#panel .bar .s{cursor:pointer;color:var(--dim)}
#panel .bar .s:hover{color:var(--bad)}
#panel pre{margin:0;padding:9px 11px;overflow:auto;flex:1;font:13px/1.45 PixelBody,monospace;
  white-space:pre-wrap;word-break:break-word;color:#bdb6d8}
#panel pre .err{color:var(--bad)}
#panel pre .ok{color:var(--good)}
.heat{display:inline-block;height:9px;width:9px;background:var(--good);box-shadow:0 0 6px var(--good)}
/* ---------- 流程图视图（n8n / Dify 那一路）---------- */
body.flow #legend,body.flow #thr,body.flow #tip{display:none}
body.flow #flthr{display:block}
#flthr{position:fixed;right:14px;bottom:12px;color:var(--dim);font-size:12px;z-index:5;
  text-align:right;display:none}
#flthr .k{display:inline-flex;align-items:center;gap:5px;margin-left:10px}
#flthr .k i{width:14px;height:0;border-top:2px dashed;display:inline-block}
/* ---------- 网页终端 ---------- */
#term{position:fixed;left:0;right:0;bottom:0;height:46vh;min-height:220px;background:#05070a;
  z-index:44;display:flex;flex-direction:column;border-top:2px solid var(--good);
  box-shadow:0 -6px 24px #000a;transform:translateY(101%);transition:transform .14s steps(4,end)}
#term.open{transform:none}
#term .bar{display:flex;align-items:center;gap:9px;padding:5px 10px;flex:none;
  border-bottom:2px solid #14202b;font-size:12px;color:var(--good)}
#term .bar .warn{color:var(--warn)}
#term .bar .gap{flex:1}
#term .bar button{font-size:12px;padding:1px 7px}
#term .bar button.stop{border-color:#4a2231;color:#ffc9d4}
#tout{flex:1;overflow:auto;margin:0;padding:9px 11px;white-space:pre-wrap;word-break:break-word;
  font:13px/1.42 PixelBody,ui-monospace,Menlo,monospace;color:#9fe8c8}
#tout .cmd{color:#e6e8ee}
#tout .err{color:#ff8fa3}
#tout .ok{color:#7de2b0}
#tout .dim{color:#5b6b78}
#presets{display:flex;flex-wrap:wrap;gap:5px;padding:0 11px 8px;flex:none}
#presets button{font-size:12px;padding:1px 7px;border-color:#1d3a30;color:#8fd8ba}
#presets button:hover{border-color:var(--good);color:#fff;background:#0d1a16}
#presets button.careful{border-color:#4a3a1d;color:var(--warn)}
#tin{display:flex;gap:8px;align-items:center;padding:7px 11px;flex:none;
  border-top:2px solid #14202b}
#tin .p{color:var(--good);font-size:14px}
#tin input{flex:1;background:transparent;border:0;outline:none;color:#e8f6ef;
  font:inherit;font-size:14px;caret-color:var(--good)}
#tin input::placeholder{color:#3d5058}
#toasts{position:fixed;right:14px;top:52px;z-index:60;display:flex;flex-direction:column;gap:7px;
  max-width:min(430px,42vw)}
.toast{display:flex;gap:9px;align-items:flex-start;padding:8px 11px;background:#12101cf2;
  border:2px solid var(--accent);box-shadow:4px 4px 0 #000a;font-size:13px;line-height:1.3;
  cursor:pointer;animation:tin .16s steps(3,end)}
.toast b{flex:none;width:16px;height:16px;display:grid;place-items:center;font-size:11px;
  border:2px solid currentColor}
.toast.ok{border-color:var(--good);color:var(--good)}
.toast.err{border-color:var(--bad);color:#ffc9d4}
.toast.warn{border-color:var(--warn);color:var(--warn)}
.toast.info{border-color:var(--accent2);color:var(--accent2)}
.toast span{color:var(--ink)}
.toast.out{opacity:0;transition:opacity .3s}
@keyframes tin{from{transform:translateX(14px);opacity:0}to{transform:none;opacity:1}}
.fnode{cursor:pointer}
.fcard{fill:#151222;stroke-width:2}
.fnode:hover .fcard{stroke:#fff;filter:drop-shadow(0 0 10px #7B5BFF88)}
.fnm{fill:#e8e3f7;font:13px PixelBody,monospace}
.fver{fill:#8a86a0;font:11px PixelBody,monospace}
.fport{fill:#3a3455}
.fedge{fill:none;stroke-width:1.7;stroke-dasharray:6,5;stroke-opacity:.75}
.fedge.declares{stroke:#AFCDF6}
.fedge.configures{stroke:#C7B8F5}
.fedge.provides{stroke:#A7EADC}
.fedge.hooks{stroke:#e06c75}
.fedge.contains{stroke:#AFCDF6}
.fedge.depends-on{stroke:#8b7dff}
.ftag{fill:#0d0b14cc;stroke:#2f2a44;stroke-width:1}
.ftagT{fill:#9d96b8;font:10.5px PixelBody,monospace}
.fleaf circle{fill:#151222;stroke-width:2}
.fleaf:hover circle{stroke:#fff}
.fleaf .gl{fill:#cfc8e8}
.fleaf .tick{fill:var(--good);font:13px PixelBody,monospace}
.flnm{fill:#b6afd0;font:11.5px PixelBody,monospace}
.fmore{fill:#6f6a86;font:11.5px PixelBody,monospace}
/* ---------- 列表视图 ---------- */
body.list svg,body.list #legend,body.list #thr{display:none}
#list{position:fixed;inset:47px 0 0 0;display:none;flex-direction:column;z-index:4;
  transition:right .14s steps(4,end)}
body.list #list{display:flex}
body.list.dw #list{right:392px}
#lbar{flex:none;display:flex;gap:6px;align-items:center;flex-wrap:wrap;padding:7px 13px 8px;
  border-bottom:2px solid var(--line)}
.fchip{font:inherit;font-size:13px;color:var(--dim);background:transparent;border:2px solid var(--line);
  padding:1px 9px;cursor:pointer}
.fchip:hover{color:#fff;border-color:var(--accent)}
.fchip.on{color:#0b0a10;background:var(--accent2);border-color:var(--accent2)}
.fchip.w.on{background:var(--warn);border-color:var(--warn)}
#lbar .gap{flex:1}
#lbar .cnt{color:var(--dim);font-size:13px;white-space:nowrap}
#lbulk{display:flex;gap:6px}
#lbulk button{font-size:13px;padding:1px 8px}
#lbulk button.danger{color:#ffc9d4;border-color:#4a2231}
#lbulk button.danger:hover{background:#3d1b22;border-color:var(--bad)}
#lwrap{flex:1;overflow:auto;padding:0 13px 96px}
#ltable{border-collapse:separate;border-spacing:0;width:100%;font-size:13.5px}
#ltable thead th{position:sticky;top:0;z-index:2;background:#0e0c14;text-align:left;font-weight:400;
  color:var(--dim);padding:7px 7px 6px;border-bottom:2px solid var(--accent);white-space:nowrap;
  cursor:pointer;user-select:none;font-size:12.5px}
#ltable thead th:hover{color:#fff}
#ltable thead th.sorted{color:var(--accent2)}
#ltable thead th.nosort{cursor:default}
#ltable .ck{width:26px;padding-left:2px}
#ltable .ck input{accent-color:var(--accent);width:13px;height:13px;cursor:pointer}
#ltable tbody tr{cursor:pointer}
#ltable tbody tr:hover>td{background:#181330 !important}
#ltable tbody tr.sel>td{background:#1e1846 !important}
#ltable tbody tr.cur{box-shadow:inset 3px 0 0 var(--accent2)}
#ltable td{padding:7px 7px 8px;border-bottom:2px solid #15121f;vertical-align:middle}
#ltable tbody tr:nth-child(4n+1)>td,#ltable tbody tr:nth-child(4n+2)>td{background:#0f0d16}
.nm{display:flex;align-items:center;gap:8px}
.nm .sw{width:10px;height:10px;flex:none;box-shadow:0 0 0 1px #0008}
.nm .id{color:#efeafb;word-break:break-all;font-size:14.5px}
.dimc{color:var(--dim)}
#ltable .desc{color:#7d7692;font-size:12.5px;display:block;margin:1px 0 0 18px;
  max-width:430px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.spc{color:#8f88a8;max-width:230px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;display:block}
.hb{display:inline-block;padding:0 6px;border:2px solid;font-size:12px;white-space:nowrap}
.ubar{display:inline-block;width:64px;height:9px;background:#191524;border:1px solid #241f33;
  vertical-align:middle;margin-right:5px}
.ubar i{display:block;height:100%;background:var(--good);opacity:.85}
.ra{display:flex;gap:4px;opacity:.34;transition:opacity .07s}
#ltable tbody tr:hover .ra,#ltable tbody tr.sel .ra,#ltable tbody tr.cur .ra{opacity:1}
.ra button{font-size:12px;padding:0 6px}
.ra button.danger{color:#ffc9d4;border-color:#4a2231}
.ra button.danger:hover{background:#3d1b22;border-color:var(--bad)}
#ltable td.empty{color:var(--dim);text-align:center;padding:44px 0;border:0}
</style></head>
<body>
<header>
  <h1>PI GRAPH</h1>
  <input id="q" placeholder="搜索节点… (回车定位)">
  <button id="refresh">⟳ 重新扫描</button>
  <button id="updates">⤓ 检查更新</button>
  <button id="view">▤ 列表视图</button>
  <button id="termbtn">▮ 终端</button>
  <span id="mode">…</span>
  <span id="live" class="off">○ 实时关</span>
  <span class="stat">__STAT__</span>
</header>
<main><svg></svg>
<div id="list">
  <div id="lbar">
    <button class="fchip" data-f="all">全部</button>
    <button class="fchip on" data-f="package">包</button>
    <button class="fchip" data-f="skill">技能</button>
    <button class="fchip" data-f="tool">工具</button>
    <button class="fchip w" data-f="health">有问题的</button>
    <span class="cnt" id="lcount"></span>
    <span class="gap"></span>
    <span id="lbulk"></span>
  </div>
  <div id="lwrap">
    <table id="ltable">
      <thead><tr>
        <th class="nosort ck"><input type="checkbox" id="ckall" title="全选当前行"></th>
        <th data-sort="name">名称</th>
        <th data-sort="kind">类型</th>
        <th data-sort="version">版本</th>
        <th data-sort="spec">来源</th>
        <th data-sort="health">健康</th>
        <th data-sort="usage">热度</th>
        <th data-sort="deg">连接</th>
        <th class="nosort">操作</th>
      </tr></thead>
      <tbody id="ltbody"></tbody>
    </table>
  </div>
</div>
</main>
<div id="legend"></div>
<div id="thr">右键节点 → 更新 / 重装 / 卸载<br>滚轮缩放 · 拖拽平移 · 点图例筛选<br>
  <span class="dimc">tool 默认折叠，点图例「tool」展开</span></div>
<div id="flthr">拖拽平移 · 滚轮缩放 · 右键节点出菜单<br>
  <span class="k"><i style="border-color:#AFCDF6"></i>声明/包含</span>
  <span class="k"><i style="border-color:#A7EADC"></i>提供</span>
  <span class="k"><i style="border-color:#e06c75"></i>钩子</span>
  <span class="k"><i style="border-color:#8b7dff"></i>依赖</span>
</div>
<div id="tip"></div>
<div id="toasts"></div>
<div id="menu"></div>
<div id="drawer"></div>
<div id="panel"><div class="bar"><span class="t"></span><span class="s">✕ 关闭</span></div><pre></pre></div>
<div id="term">
  <div class="bar">
    <span>▮ 终端</span>
    <span class="warn">在本机执行任意命令（与右侧白名单动作是两套，--no-shell 可关）</span>
    <span class="gap"></span>
    <button id="tstop" class="stop">■ 停止</button>
    <button id="tclear">清空</button>
    <button id="tclose">✕ 关闭</button>
  </div>
  <pre id="tout"></pre>
  <div id="presets"></div>
  <div id="tin"><span class="p">$</span><input id="tcmd" placeholder="输命令回车运行 · ↑↓ 翻历史 · Ctrl+` 开关终端" autocomplete="off" spellcheck="false"></div>
</div>
<script type="module">
__D3__
const DATA = __DATA__;
const COLORS = __COLORS__;
const HEALTH_COLOR = __HCOLOR__;
const HEALTH_LABEL = __HLABEL__;
// 分层显示：包/技能这类骨架一直带标签，tool/hook 缩放到位了再出现，否则糊成一团
function labelVisible(n, k) {
  if (n.kind === 'tool') return k >= 1.1 || (n.usage || 0) >= 300;
  if (n.kind === 'hook') return k >= .8;
  return true;
}
// token 固定写在 HTML 里（后端用同一份 ~/.pi/agent/pi-graph.token），
// 所以双击打开也能直接操作；URL 上的 ?t= 仍然优先，方便临时换端口。
const TOKEN = new URLSearchParams(location.search).get('t') || '__TOKEN__';
const PORT = new URLSearchParams(location.search).get('port') || '8787';
// file:// 打开时后端在 127.0.0.1，得走绝对地址；由服务端托管时同源相对即可
const BASE = location.protocol === 'file:' ? 'http://127.0.0.1:' + PORT : '';
let OFFLINE = true;   // 启动时探一次 /api/ping
const POSKEY = 'pi-graph-pos';
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

// 调试/测试用的把手：控制台里 piGraph.token() 看令牌，piGraph.api() 直接打接口
// 测试/调试用的把手。模块作用域里的函数不会挂到 window 上，
// 所以自动化测试要么走这里，要么就得复制一份逻辑（不行）
window.piGraph = {
  token: () => TOKEN,
  base: () => BASE,
  api: (...a) => api(...a),
  node: (id) => byId.get(id),        // 按 id 取节点
  nodes: () => nodes,
  zoomK: () => d3.zoomTransform(svg.node()).k,
  runAction, readFile, mcpTest, openMenu, show, setView, renderList,
  highlight, toast, stream, actionsOf,
  termRun: (cmd) => runShell(cmd), termOpen: (pre) => openTerm(pre, true),
  termToggle: () => toggleTerm(),
  view: () => view,
  offline: () => OFFLINE,
  clearPanel() { panePre.textContent = ''; $('#toasts').innerHTML = ''; },
};
const api = (route, body) => fetch(BASE + route, {
  method: body ? 'POST' : 'GET',
  headers: body ? {'content-type':'application/json','x-token':TOKEN} : {'x-token':TOKEN},
  body: body ? JSON.stringify(body) : undefined,
});

const svg = d3.select('svg');
const layer = svg.append('g');
let fLayer = null;   // 流程图图层（和力导向图共用一套缩放/平移）
let zoomT = 0;
const zoom = d3.zoom().scaleExtent([.15, 8]).on('zoom', e => {
  layer.attr('transform', e.transform);
  if (fLayer) fLayer.attr('transform', e.transform);
  // 缩小到看不见细节时，把 tool 的标签收起来，否则中间糊成一团
  if (tsel) {
    tsel.attr('display', n => labelVisible(n, e.transform.k) ? null : 'none');
    clearTimeout(zoomT);
    zoomT = setTimeout(() => declutter(), 140);
  }
  if (fLayer && view === 'flow') fLayer.attr('opacity', e.transform.k < .3 ? .9 : 1);
});
svg.call(zoom);

let nodes = DATA.nodes, links = DATA.links;
let sim = null, sel = null, lsel = null, tsel = null, halo = null;
// 262 个 tool 是最大的噪音源：图谱默认只画骨架（包/技能/钩子/配置…），
// 想全看就点图例里的 tool —— 一屏塞 379 个节点谁也读不出来
let pinned = null, hiddenKinds = new Set(['tool']), healthOnly = false;
const pos = new Map();
try { for (const [k, v] of Object.entries(JSON.parse(localStorage.getItem(POSKEY) || '{}'))) pos.set(k, v); } catch {}
let byId = new Map(), adj = new Map(), adjRel = new Map();
const UP = {};   // id → {current, latest, outdated}

// ================= 视图状态 =================
let view = ['graph', 'flow', 'list'].includes(location.hash.slice(1)) ? location.hash.slice(1) : 'graph';
// 列表默认只看「包」：进来就是能操作的那 29 个，而不是被 262 个 tool 淹没
let filter = 'package';        // all | package | skill | tool | health
let sortKey = 'usage', sortDir = -1;
let selected = new Set();      // 批量操作用

// ================= 面板 =================
const panel = $('#panel'), panePre = $('#panel pre');
function showPanel(title, text) { $('.t', panel).textContent = title; panePre.textContent = text; panel.classList.add('open'); }
function append(text, cls) {
  const s = document.createElement('span');
  if (cls) s.className = cls;
  s.textContent = text; panePre.appendChild(s); panePre.scrollTop = panePre.scrollHeight;
}
$('#panel .s').onclick = () => panel.classList.remove('open');
// 边流边渲染，同时把退出码收回来 —— 不判断成败就报「完成」是骗人
async function stream(res) {
  const rd = res.body.getReader(), dec = new TextDecoder();
  let text = '';
  for (;;) { const {done, value} = await rd.read(); if (done) break;
    const t = dec.decode(value, {stream:true});
    text += t;
    append(t, /!!|error|Error|npm error|ERR!/.test(t) ? 'err' : null); }
  const codes = [...text.matchAll(/\[exit (\d+)\]/g)].map(m => Number(m[1]));
  const failed = codes.filter(c => c !== 0).length;
  return { text, codes, failed, ok: codes.length > 0 && failed === 0 && !/!!/.test(text) };
}
// ms = 0 表示不自动消失（等用户点掉），onClick 可选
function toast(kind, msg, ms, onClick) {
  const t = document.createElement('div');
  t.className = 'toast ' + kind;
  t.innerHTML = '<b>' + ({ok: '✓', err: '✗', warn: '!', info: 'i'}[kind] || 'i') + '</b><span>' + esc(msg) + '</span>';
  t.onclick = () => { t.remove(); if (onClick) onClick(); };
  $('#toasts').appendChild(t);
  const life = ms === undefined ? (kind === 'err' ? 14000 : 6500) : ms;
  if (life > 0) {
    setTimeout(() => t.classList.add('out'), life);
    setTimeout(() => t.remove(), life + 400);
  }
  return t;
}
const NEED_SERVER = '当前是直接打开的 HTML（只读模式）。\n\n启动后端：\n\n  python3 ~/.pi/scripts/pi-graph.py serve --open\n\n再在打开的那个页面里操作。';

// ================= 网页终端 =================
// 与右侧「白名单动作」刻意分开：那边 argv 全部由服务端派生，这边就是人在敲命令。
// 唯一进入命令行的外部字符串只有输入框内容，服务端另开 /api/shell 端点，可 --no-shell 关闭。
const termEl = $('#term'), tout = $('#tout'), tcmd = $('#tcmd');
let termHist = [];
let termIdx = 0;
let termBusy = false;

try { termHist = JSON.parse(localStorage.getItem('pi-graph-hist') || '[]'); } catch { termHist = []; }
termIdx = termHist.length;

function toggleTerm(force) { openTerm(null, force); }
function openTerm(prefill, force) {
  const want = force === undefined ? !termEl.classList.contains('open') : !!force;
  termEl.classList.toggle('open', want);
  if (want) {
    if (typeof prefill === 'string' && prefill) { tcmd.value = prefill; }
    tcmd.focus();
    tcmd.setSelectionRange(tcmd.value.length, tcmd.value.length);
  }
}
$('#termbtn').onclick = () => toggleTerm();
$('#tclose').onclick = () => openTerm(null, false);
$('#tclear').onclick = () => { tout.textContent = ''; tcmd.focus(); };
$('#tstop').onclick = () => { if (termCtl) termCtl.abort(); };

let termCtl = null;
function termLine(s, cls) {
  const d = document.createElement('span');
  d.className = cls || '';
  d.textContent = s;
  tout.appendChild(d);
  tout.scrollTop = tout.scrollHeight;
}
async function runShell(cmd) {
  if (OFFLINE) return termLine('✗ 后端未连。先跑 pi-graph-agent.sh install\n', 'err');
  if (termBusy) return termLine('✗ 上一条还在跑，点「停止」或等它结束\n', 'err');
  termLine('$ ' + cmd + '\n', 'cmd');
  termBusy = true;
  termCtl = new AbortController();
  let text = '';
  try {
    const res = await fetch(BASE + '/api/shell', {
      method: 'POST',
      headers: {'content-type': 'application/json', 'x-token': TOKEN},
      body: JSON.stringify({cmd}),
      signal: termCtl.signal,
    });
    if (!res.ok) {
      const j = await res.json().catch(() => ({}));
      termLine('✗ ' + (j.error || res.status) + '\n', 'err');
    } else {
      const rd = res.body.getReader(), dec = new TextDecoder();
      for (;;) {
        const {done, value} = await rd.read();
        if (done) break;
        const t = dec.decode(value, {stream:true});
        text += t;
        termLine(t, /!!|[Ee]rror|not found|ERR!/.test(t) ? 'err' : null);
      }
    }
  } catch (e) {
    termLine('\n■ 已中断\n', 'dim');
  } finally {
    termBusy = false;
    termCtl = null;
  }
  const m = [...text.matchAll(/\[exit (\d+)\]/g)].pop();
  const code = m ? Number(m[1]) : null;
  if (code === 0) termLine('', 'ok');
  if (code !== null && code !== 0) termLine('', 'err');
  return code;
}
async function termSubmit() {
  const cmd = tcmd.value.trim();
  if (!cmd) return;
  tcmd.value = '';
  if (termHist[termHist.length - 1] !== cmd) {
    termHist.push(cmd);
    if (termHist.length > 200) termHist.shift();
    try { localStorage.setItem('pi-graph-hist', JSON.stringify(termHist)); } catch {}
  }
  termIdx = termHist.length;
  await runShell(cmd);
}
tcmd.onkeydown = e => {
  if (e.key === 'Enter') { e.preventDefault(); termSubmit(); return; }
  if (e.key === 'ArrowUp') {
    e.preventDefault();
    if (termIdx > 0) tcmd.value = termHist[--termIdx] || '';
    tcmd.setSelectionRange(tcmd.value.length, tcmd.value.length);
    return;
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    if (termIdx < termHist.length - 1) tcmd.value = termHist[++termIdx] || '';
    else { termIdx = termHist.length; tcmd.value = ''; }
    return;
  }
  if (e.key === 'l' && e.ctrlKey) { e.preventDefault(); tout.textContent = ''; }
};

// 常用命令：点一下就跑。带 careful 标记的会先问一句
const PRESETS = [
  ['pi list', 'pi list'],
  ['pi --version', 'pi --version'],
  ['图谱统计', 'python3 ~/.pi/scripts/pi-graph.py stats'],
  ['自检', 'python3 ~/.pi/scripts/pi-graph.py --selftest'],
  ['后端状态', '~/.pi/scripts/pi-graph-agent.sh status | head -3'],
  ['磁盘占用', 'du -sh ~/.pi/agent ~/.pi/agent/npm 2>/dev/null'],
  ['有更新的包', 'pi list 2>/dev/null | head -5'],
  ['更新全部扩展', 'pi update --extensions', true],
];
$('#presets').innerHTML = PRESETS.map(([label, , careful], i) =>
  '<button data-p="' + i + '"' + (careful ? ' class="careful"' : '') + '>' + esc(label) +
  (careful ? ' ⚠' : '') + '</button>').join('');
$('#presets').onclick = e => {
  const b = e.target.closest('[data-p]');
  if (!b) return;
  const [label, cmd, careful] = PRESETS[+b.dataset.p];
  openTerm(null, true);
  if (careful && !confirm(label + '\n\n$ ' + cmd + '\n\n确认执行？')) return;
  runShell(cmd);
};

// 右键菜单里那条「在终端运行…」用的：按节点类型猜一条最可能的命令
function termCommandFor(n) {
  if (n.health === 'leftover' && n.path) return 'du -sh ' + n.path;
  if (n.spec && n.npmName) return 'npm view ' + n.npmName + ' version';
  if (n.kind === 'mcp' && n.file) return 'cat ' + n.file;
  if (n.kind === 'skill' && n.path) return 'cat ' + n.path + '/SKILL.md';
  if (n.path) return 'ls -la ' + n.path;
  return null;
}

// ================= 动作 =================
async function runAction(action, id, danger, label, extra) {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  const body = Object.assign({action, id}, extra || {});
  const pv = await (await api('/api/preview', body)).json();
  if (pv.error) return showPanel(label, '✗ ' + pv.error);
  const cmds = pv.steps.map(s => '$ ' + s.join(' ')).join('\n');
  if (danger && !confirm(label + '  ' + id + '\n\n' + cmds + '\n\n确认执行？')) return;
  showPanel(label + ' — ' + id, cmds + '\n\n');
  toast('info', label + ' ' + id + ' …');
  const res = await stream(await api('/api/action', Object.assign({}, body, {confirm:true})));
  if (res.ok) {
    append('\n—— 成功。\n', 'ok');
    toast('ok', label + '成功：' + id + '（npm/git 变更要重开 pi 会话生效）');
    // 凡是改动磁盘/安装状态的动作都要重扫：否则节点还挂在图上，用户会再点一次
    if (['uninstall', 'reinstall', 'update', 'rmLeftover', 'rmSkill'].includes(action)) await refreshGraph();
  } else {
    // 失败必须显式说出来：哪一步、退出码多少、日志在哪看
    const line = res.codes.findIndex(c => c !== 0);
    const why = line >= 0 ? '第 ' + (line + 1) + ' 步失败（exit ' + res.codes[line] + '）' : '执行出错';
    // 只有真的动过 settings.json 的动作才提备份，别乱许诺一个不存在的回滚点
    const backed = ['uninstall', 'reinstall'].includes(action);
    const hint = /No such file or directory|not found/.test(res.text)
      ? '目标已经不在了 —— 可能已经清理过。点「重新扫描」刷新图谱。'
      : backed
        ? '完整日志见上方，settings.json 有 .bak-ui-* 备份可回滚。'
        : '完整日志见上方。';
    append('\n—— ✗ ' + label + '失败：' + why + '。' + hint + '\n', 'err');
    toast('err', label + '失败：' + id + ' · ' + why + '（详情见底部面板）');
    toast('err', label + '失败：' + id + ' · ' + why + '（详情见底部面板）');
  }
}
// 改过包之后图谱就过期了：重新扫一遍，别让界面停留在旧状态
async function refreshGraph() {
  try {
    const res = await api('/api/refresh', {});
    if (!res.ok) return toast('warn', '图谱已重新扫描失败，点顶部「重新扫描」重试');
    await res.text();
    // 不自动 reload：日志还在面板里，冲掉了就没法回头看
    toast('info', '图谱已重扫 · 点此重新载入新数据', 0, () => location.reload());
  } catch (e) {
    toast('warn', '图谱重扫失败：' + e.message);
  }
}
async function readFile(id) {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  const r = await (await api('/api/file', {id})).json();
  if (r.error) return showPanel(id, '✗ ' + r.error);
  showPanel(r.path, r.text);
}
async function mcpTest(id) {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  showPanel('MCP 连接测试 — ' + id, '正在起进程握手…\n\n');
  await stream(await api('/api/mcptest', {id}));
}

function actionsOf(n) {
  const a = [['详情 / 关系', () => show(n.id)]];
  if (n.path) a.push(['Finder 显示', () => runAction('reveal', n.id, 0, '显示位置')]);
  if (n.repo) a.push(['打开仓库', () => runAction('openRepo', n.id, 0, '打开仓库')]);
  if (n.kind === 'skill') a.push(['预览 SKILL.md', () => readFile(n.id)]);
  if (n.file) a.push(['查看配置条目', () => readFile(n.id)]);
  if (n.kind === 'mcp') a.push(['连接测试 (initialize + tools/list)', () => mcpTest(n.id)]);
  if (n.spec) {
    if (!n.pinned) a.push(['更新  pi update', () => runAction('update', n.id, 0, '更新')]);
    a.push(['重装  remove + install', () => runAction('reinstall', n.id, 1, '重装')]);
    a.push(['卸载  pi remove', () => runAction('uninstall', n.id, 1, '卸载')]);
  } else if (n.health === 'leftover') {
    // 已经没有 spec 了，卸载动作不存在 —— 但目录还在，给一条清理路径
    a.push([`清理残留（移到废纸篓） ${n.sizeMB ? n.sizeMB + ' MB' : ''}`, () => runAction('rmLeftover', n.id, 1, '清理残留')]);
  }
  if (n.kind === 'skill' && n.writable) a.push(['删除本机 skill', () => runAction('rmSkill', n.id, 1, '删除 skill')]);
  a.push(['pi config（启用/禁用）', () => runAction('config', n.id, 0, 'pi config')]);
  // 白名单动作覆盖不到的事，就交给人：预填命令到终端，按回车才跑
  const guess = termCommandFor(n);
  if (guess) a.push(['在终端运行…  ' + guess, () => openTerm(guess)]);
  return a;
}

// ================= 右键菜单 =================
function closeMenu() { $('#menu').style.display = 'none'; }
function menuK(n) { return n.spec ? n.spec : (n.kind === 'skill' && n.writable ? 'rm -rf' : ''); }
function openMenu(ev, d) {
  const m = $('#menu'); m.innerHTML = '';
  const groups = [];
  let cur = [];
  for (const it of actionsOf(d)) {
    const danger = /卸载|删除/.test(it[0]);
    // 已知没有新版就把「更新」灰掉，免得白点
    const disabled = it[0].startsWith('更新') &&
                     (d.pinned || (UP[d.id] && UP[d.id].outdated === false));
    cur.push({label: it[0], fn: disabled ? null : it[1], danger,
              k: it[0].startsWith('更新') ? (d.pinned ? 'ref 固定' : (UP[d.id] ? (UP[d.id].latest || '') : '')) : (danger ? menuK(d) : '')});
  }
  groups.push(cur);
  for (const g of groups) {
    for (const it of g) {
      const el = document.createElement('div');
      el.className = 'mi' + (it.fn ? '' : ' off') + (it.danger ? ' danger' : '');
      el.innerHTML = '<span>' + esc(it.label) + '</span><span class="k">' + esc(it.k || '') + '</span>';
      if (it.fn) el.onclick = () => { closeMenu(); it.fn(); };
      m.appendChild(el);
    }
    m.appendChild(document.createElement('hr'));
  }
  m.lastChild.remove();
  m.style.display = 'block';
  m.style.left = Math.min(ev.clientX, innerWidth - 280) + 'px';
  m.style.top = Math.min(ev.clientY, innerHeight - m.offsetHeight - 8) + 'px';
}
document.addEventListener('click', () => closeMenu());
document.addEventListener('contextmenu', e => { if (!e.target.closest('#menu')) closeMenu(); });
addEventListener('keydown', e => {
  if (e.key === 'Escape') { closeMenu(); closeDrawer(); }
  if (e.key === '/' && document.activeElement !== $('#q')) { e.preventDefault(); $('#q').focus(); }
});

// ================= 详情抽屉 =================
function show(id) {
  const n = byId.get(id) || {id};
  const d = $('#drawer');
  const badges = [];
  if (n.health) badges.push(`<span class="badge" style="border-color:${HEALTH_COLOR[n.health] || '#888'};color:${HEALTH_COLOR[n.health] || '#888'}">${esc(HEALTH_LABEL[n.health] || n.health)}</span>`);
  if (n.usage) badges.push(`<span class="badge" style="border-color:var(--good);color:var(--good)">调用 ${n.usage} 次</span>`);
  if (n.pinned) badges.push('<span class="badge" style="border-color:var(--info);color:var(--info)">版本已固定</span>');
  if (UP[id] && UP[id].outdated) badges.push(`<span class="badge" style="border-color:var(--warn);color:var(--warn)">可升级 ${esc(UP[id].current||'?')} → ${esc(UP[id].latest)}</span>`);
  if (UP[id] && UP[id].error) badges.push('<span class="badge" style="border-color:#6f6a86;color:#6f6a86">查更新失败</span>');
  const rows = [];
  for (const k of ['description','version','ref','risk','spec','path','file','repo','source']) {
    if (n[k]) rows.push(`<div class="f"><b>${k}</b><span>${esc(n[k])}</span></div>`);
  }
  if (n.healthDetail) rows.push(`<div class="f"><b>问题</b><span>${esc(n.healthDetail)}</span></div>`);
  if (n.installed === false) rows.push('<div class="f"><b>installed</b><span>目录不存在（settings 声明了但没装）</span></div>');
  const rel = adjRel.get(id) || [];
  const byKind = {};
  for (const [dir, kind, other] of rel) {
    const key = (dir === 'out' ? '→ ' : '← ') + kind;
    (byKind[key] = byKind[key] || []).push(other);
  }
  let relHtml = '';
  for (const key of Object.keys(byKind).sort()) {
    const list = byKind[key].sort();
    relHtml += `<div class="sec">${esc(key)} (${list.length})</div><div class="chips">` +
      list.slice(0, 80).map(o => `<span class="chip" data-go="${esc(o)}">${esc(o)}</span>`).join('') +
      (list.length > 80 ? '<span class="chip">…</span>' : '') + '</div>';
  }
  d.innerHTML = `<span class="x">✕</span><h2>${esc(n.id)}</h2><div class="kind">${esc(n.kind)} · 连接 ${rel.length}</div>` +
    badges.join('') +
    `<div class="acts">${actionsOf(n).filter(a => !/详情/.test(a[0])).map((a, i) =>
        `<button data-act="${i}" class="${/卸载|删除/.test(a[0]) ? 'danger' : ''}">${esc(a[0].split('  ')[0])}</button>`).join('')}</div>` +
    rows.join('') + (relHtml || '<div class="sec">（没有关系边）</div>');
  d.querySelector('.x').onclick = () => closeDrawer();
  for (const c of d.querySelectorAll('[data-go]')) c.onclick = () => { const t = byId.get(c.dataset.go); if (t) { show(t.id); focusNode(t); } };
  const acts = actionsOf(n).filter(a => !/详情/.test(a[0]));
  for (const b of d.querySelectorAll('[data-act]')) b.onclick = () => acts[+b.dataset.act][1]();
  d.classList.add('open');
  document.body.classList.add('dw');
}
function closeDrawer() {
  $('#drawer').classList.remove('open');
  document.body.classList.remove('dw');
}
function focusNode(d) {
  if (d.x == null) return;
  svg.transition().duration(350).call(zoom.transform,
    d3.zoomIdentity.translate(innerWidth / 2, innerHeight / 2).scale(1.6).translate(-d.x, -d.y));
}
// 力导向图里标签必然打架，d3 不管这个。贪心法：按重要度排序，
// 放不下就藏，重要节点优先占位。缩放不改变相对重叠关系，所以一次计算通吃。
const labelBoxes = [];
function labelRank(n) {
  const deg = (adj.get(n.id) || new Set()).size;
  return (n.usage || 0) * 4 + deg * 10 + (n.kind === 'package' ? 900 : 0) + (n.health ? 500 : 0);
}
function declutter() {
  if (!sel || !tsel) return;
  labelBoxes.length = 0;
  const zk = d3.zoomTransform(svg.node()).k || 1;
  const cands = nodes.filter(n => labelVisible(n, zk)).sort((a, b) => labelRank(b) - labelRank(a));
  const seen = new Set();
  for (const n of cands) {
    const w = n.id.length * 6.4 + 10, h = 15;
    const x = n.x + n._r + 4, y = n.y - h / 2;
    let clash = false;
    for (const b of labelBoxes) {
      if (x < b.x + b.w && x + w > b.x && y < b.y + b.h && y + h > b.y) { clash = true; break; }
    }
    n._hideLbl = clash;
    if (!clash && !seen.has(n.id)) { labelBoxes.push({x, y, w, h}); seen.add(n.id); }
  }
  tsel.attr('display', n => n._hideLbl ? 'none' : null);
}

function highlight(id) {
  pinned = id;
  const near = id ? adj.get(id) : null;
  const base = n => (n.kind === 'tool' && !pinned ? .42 : 1);
  sel.attr('opacity', n => !near || near.has(n.id) ? base(n) : .1);
  halo.attr('opacity', n => !near || near.has(n.id) ? (n._halo || 0) : 0);
  lsel.attr('opacity', l => !near || (l.source.id || l.source) === id || (l.target.id || l.target) === id ? .75 : .04);
  tsel.attr('opacity', n => !near || near.has(n.id) ? base(n) : .08);
  $('#drawer').classList.toggle('open', !!id);
  document.body.classList.toggle('dw', !!id);
  if (view === 'list') renderList();
}

// ================= 渲染 =================
// 按 kind 给个大致方位：技能去左下、SDK 去上方、配置去右上…稀疏处留白，密集处分开
const ANCHOR = {
  skill: [.17, .76], group: [.17, .76], sdk: [.52, .16], config: [.86, .14],
  mcp: [.14, .2], command: [.86, .55], package: [.45, .46], provider: [.62, .6],
  hook: [.78, .3],
};

// 索引单独抽出来：实时同步换数据后，列表/流程视图也要用到最新的 byId/adj
function indexGraph() {
  byId = new Map(nodes.map(n => [n.id, n]));
  adj = new Map(nodes.map(n => [n.id, new Set([n.id])]));
  adjRel = new Map(nodes.map(n => [n.id, []]));
  for (const l of links) {
    const s = l.source.id || l.source, t = l.target.id || l.target;
    if (!adj.has(s) || !adj.has(t)) continue;   // 增量数据里可能有对端还没到的边
    adj.get(s).add(t); adj.get(t).add(s);
    adjRel.get(s).push(['out', l.kind, t]);
    adjRel.get(t).push(['in', l.kind, s]);
  }
}

function render() {
  if (sim) sim.stop();
  layer.selectAll('*').remove();
  indexGraph();
  const W = innerWidth, H = innerHeight;
  const deg = new Map(nodes.map(n => [n.id, 0]));
  for (const l of links) { const s = l.source.id || l.source, t = l.target.id || l.target;
    deg.set(s, (deg.get(s) || 0) + 1); deg.set(t, (deg.get(t) || 0) + 1); }
  const R = n => {
    const d = deg.get(n.id) || 0;
    if (n.kind === 'tool') return 2.6 + Math.sqrt(d) * 1.0;
    if (n.kind === 'group') return 13 + Math.sqrt(d) * 1.8;
    return 4 + Math.sqrt(d) * 3.6;
  };
  // 包/扩展本身没有"调用次数"，但它提供的工具被调用的次数就是它的热度
  const useOf = new Map(nodes.map(n => [n.id, n.usage || 0]));
  for (const l of links) {
    if (l.kind !== 'provides' && l.kind !== 'hooks') continue;
    const s = l.source.id || l.source, t = l.target.id || l.target;
    useOf.set(s, (useOf.get(s) || 0) + (useOf.get(t) || 0));
  }
  const maxUse = Math.max(1, ...useOf.values());
  for (const n of nodes) {
    n._use = useOf.get(n.id) || 0;
    n._r = R(n);
    n._halo = n._use ? .25 + .75 * Math.sqrt(n._use / maxUse) : 0;
    n._bad = n.health || (UP[n.id] && UP[n.id].outdated ? 'outdated' : null);
    const p = pos.get(n.id); if (p) { n.x = p.x; n.y = p.y; }
  }
  sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(l =>
      l.kind === 'depends-on' ? 140 : l.kind === 'provides' ? 40 : l.kind === 'hooks' ? 105 : 70).strength(.5))
    .force('charge', d3.forceManyBody().strength(n => n.kind === 'tool' ? -30 : -480))
    .force('center', d3.forceCenter(W / 2, H / 2))
    // 半径要给标签留位置，但必须封顶：长包名（33 字符）不封顶会把图撑成空心环
    .force('collide', d3.forceCollide().radius(n => n._r + Math.min(n.id.length * 1.7, 26)))
    .force('x', d3.forceX(n => (ANCHOR[n.kind] || [.5, .5])[0] * W).strength(n => n.kind === 'tool' ? .045 : .075))
    .force('y', d3.forceY(n => (ANCHOR[n.kind] || [.5, .5])[1] * H).strength(n => n.kind === 'tool' ? .045 : .075));

  lsel = layer.append('g').selectAll('line').data(links).join('line')
    .attr('class', 'link').attr('stroke-width', l => l.kind === 'depends-on' ? 1.6 : 1)
    .attr('stroke-dasharray', l => ['provides','hooks'].includes(l.kind) ? '4,3' : null);

  // 使用热度：外发光方块（越大越常用）
  halo = layer.append('g').selectAll('rect').data(nodes.filter(n => n.usage))
    .join('rect')
    .attr('x', d => -d._r * 2.2).attr('y', d => -d._r * 2.2)
    .attr('width', d => d._r * 4.4).attr('height', d => d._r * 4.4)
    .attr('fill', 'none').attr('stroke', '#A7EADC').attr('stroke-width', 2)
    .attr('opacity', d => d._halo * .9).attr('pointer-events', 'none');

  // 不同 kind 用不同像素符号，光靠颜色在密集区域分不出来
  const SYM = { tool: d3.symbolSquare, package: d3.symbolSquare, provider: d3.symbolSquare,
                group: d3.symbolSquare, skill: d3.symbolDiamond, sdk: d3.symbolDiamond,
                hook: d3.symbolCross, command: d3.symbolTriangle, mcp: d3.symbolWye,
                config: d3.symbolCircle };
  const symSize = d => Math.pow(d._r * 2, 2) * (['hook', 'mcp'].includes(d.kind) ? 1.6 : 1.05);
  sel = layer.append('g').selectAll('path').data(nodes).join('path')
    .attr('d', d => d3.symbol().type(SYM[d.kind] || d3.symbolCircle).size(symSize(d))())
    .attr('fill', d => COLORS[d.kind] || '#888')
    .attr('stroke', d => d._bad ? (HEALTH_COLOR[d._bad] || '#F3B5D2') : '#0c0c0c')
    .attr('stroke-width', d => d._bad ? 2.4 : 1.4)
    .attr('shape-rendering', 'crispEdges')
    .call(d3.drag().on('start', (e, d) => { if (!e.active) sim.alphaTarget(.25).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end', (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = d.fy = null; }));

  // 工具节点太多，只给「用过的」加标签；其余靠 hover
  tsel = layer.append('g').selectAll('text').data(nodes.filter(n => labelVisible(n, d3.zoomTransform(svg.node()).k)))
    .join('text').attr('class', 'lbl').text(d => d.id).attr('dx', d => d._r + 4).attr('dy', 4);
  // 262 个 tool 小方块是最大的视觉噪音：默认压暗，骨架（包/技能/钩子）先读出来
  sel.filter(n => n.kind === 'tool').attr('opacity', .42);
  tsel.filter(n => n.kind === 'tool').attr('opacity', .5);

  // 连着 tool 的边也淡掉：骨架关系先读出来（变量名是 lsel，不是 link）
  lsel.attr('opacity', l => {
    const s = byId.get(l.source.id || l.source), t = byId.get(l.target.id || l.target);
    const noisy = (s && s.kind === 'tool') || (t && t.kind === 'tool');
    return noisy ? .16 : .5;
  });
  sel.on('click', (e, d) => { e.stopPropagation();
      if (pinned === d.id) { highlight(null); } else { highlight(d.id); show(d.id); } });
  sel.on('contextmenu', (e, d) => { e.preventDefault(); e.stopPropagation(); highlight(d.id); show(d.id); openMenu(e, d); });
  svg.on('click', () => { highlight(null); closeDrawer(); });

  const tip = $('#tip');
  sel.on('mouseover', (e, d) => {
    const ns = [...(adj.get(d.id) || [])].filter(x => x !== d.id);
    tip.innerHTML = `<b>${esc(d.id)}</b> <span class="k">${esc(d.kind)}</span>` +
      (d.version ? ` <span class="k">v${esc(d.version)}</span>` : '') +
      (d.usage ? ` <span class="k">·${d.usage}次</span>` : '') +
      (d._bad ? `<br><span style="color:${HEALTH_COLOR[d._bad] || '#F3B5D2'}">${esc(HEALTH_LABEL[d._bad] || '可升级')}</span>` : '') +
      (d.description ? `<br>${esc(d.description)}` : '') +
      (d.spec ? `<br><span class="k">${esc(d.spec)}</span>` : '') +
      (ns.length ? `<br><span class="k">${esc(ns.slice(0, 8).join(', '))}${ns.length > 8 ? ' …' : ''}</span>` : '');
    tip.style.opacity = 1;
  }).on('mousemove', e => {
    tip.style.left = Math.min(e.clientX + 14, innerWidth - 360) + 'px';
    tip.style.top = Math.min(e.clientY + 14, innerHeight - 120) + 'px';
  }).on('mouseout', () => tip.style.opacity = 0);

  sim.on('tick', () => {
    lsel.attr('x1', d => d.source.x).attr('y1', d => d.source.y)
        .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    sel.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
    halo.attr('transform', d => 'translate(' + d.x + ',' + d.y + ')');
    tsel.attr('x', d => d.x).attr('y', d => d.y);
    // 拖动/收敛时节点会挪，标签得跟着重排；节流到每 4 帧，别把主线程吃光
    // （必须写在这里：sim.on('tick') 是覆盖式的，再注册一次会顶掉上面这段布局更新）
    if (++tickN % 4 === 0) declutter();
  });
  let tickN = 0;
  sim.on('end', () => {
    declutter();
    const o = {};
    for (const n of nodes) if (n.x != null) o[n.id] = {x: Math.round(n.x), y: Math.round(n.y)};
    try { localStorage.setItem(POSKEY, JSON.stringify(o)); } catch {}
  });

  buildLegend();
  applyFilters();
  headerStat();
}

function buildLegend() {
  const kinds = [...new Set(nodes.map(n => n.kind))];
  const hs = {};
  for (const n of nodes) if (n.health) hs[n.health] = (hs[n.health] || 0) + 1;
  $('#legend').innerHTML =
    kinds.map(k => `<span class="li${hiddenKinds.has(k) ? ' off' : ''}" data-kind="${esc(k)}">` +
      `<span class="dot" style="background:${COLORS[k] || '#888'}"></span>${esc(k)} ${nodes.filter(n => n.kind === k).length}</span>`).join('') +
    (Object.keys(hs).length ? '<div class="sec" style="margin:6px 0 0 2px">健康</div>' +
      Object.entries(hs).map(([h, c]) => `<span class="li" data-health="${esc(h)}">` +
        `<span class="dot" style="background:${HEALTH_COLOR[h] || '#888'}"></span>${esc(HEALTH_LABEL[h] || h)} ${c}</span>`).join('') : '');
  for (const el of document.querySelectorAll('#legend .li')) {
    el.onclick = () => {
      if (el.dataset.kind) { const k = el.dataset.kind;
        hiddenKinds.has(k) ? hiddenKinds.delete(k) : hiddenKinds.add(k); el.classList.toggle('off'); }
      else { healthOnly = !healthOnly; }
      applyFilters();
    };
  }
}
function applyFilters() {
  if (view === 'list') return renderList();
  if (view === 'flow') return applyFlowFilter();
  if (!sel) return;
  const near = pinned ? adj.get(pinned) : null;
  const vis = n => (!hiddenKinds.has(n.kind) || n.kind === pinned) && (!healthOnly || n.health || (UP[n.id] && UP[n.id].outdated));
  const base = n => (n.kind === 'tool' && !pinned ? .42 : 1);
  sel.attr('opacity', n => !vis(n) ? 0 : (!near || near.has(n.id) ? base(n) : .1));
  halo.attr('opacity', n => !vis(n) ? 0 : (!near || near.has(n.id) ? n._halo : 0));
  tsel.attr('opacity', n => !vis(n) ? 0 : (!near || near.has(n.id) ? base(n) : .08));
}
function headerStat() {
  const bad = nodes.filter(n => n.health).length;
  const out = Object.values(UP).filter(u => u.outdated).length;
  const pk = nodes.filter(n => n.kind === 'package');
  $('.stat').innerHTML = `nodes <b>${nodes.length}</b> · edges <b>${links.length}</b> · pkgs <b>${pk.length}</b>` +
    (bad ? ` · <i>健康 ${bad}</i>` : '') + (out ? ` · <i>可升级 ${out}</i>` : '');
}

// ================= 列表视图 =================
const ROWS = () => {
  const t = ($('#q').value || '').trim().toLowerCase();
  return nodes.filter(n => {
    // 列表有自己的筛选 chip，不跟着图谱图例走 —— 否则图谱里折叠 tool 会把
    // 列表的「全部」也变成 117 行，看着像丢了数据
    if (n.kind === 'group') return false;                     // 力导向图专用的虚拟聚合节点
    if (filter === 'health' && !n.health && !(UP[n.id] && UP[n.id].outdated)) return false;
    if (['package','skill','tool'].includes(filter) && n.kind !== filter) return false;
    if (t && !(n.id + ' ' + (n.description || '') + ' ' + (n.spec || '')).toLowerCase().includes(t)) return false;
    return true;
  });
};
function sortRows(rows) {
  const val = n => {
    if (sortKey === 'deg') return (adj.get(n.id) || new Set()).size - 1;
    if (sortKey === 'health') return n.health ? 1 : (UP[n.id] && UP[n.id].outdated ? .5 : 0);
    if (sortKey === 'version') return n.version || '';
    if (sortKey === 'kind') return n.kind;
    if (sortKey === 'spec') return n.spec || '';
    if (sortKey === 'usage') return n._use || 0;
    return n.id.toLowerCase();
  };
  return rows.slice().sort((a, b) => {
    const x = val(a), y = val(b);
    const c = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return (c || a.id.localeCompare(b.id)) * sortDir;
  });
}
function rowActions(n) {
  const a = [];
  if (n.spec) {
    if (!n.pinned && !(UP[n.id] && UP[n.id].outdated === false)) a.push(['更新', () => runAction('update', n.id, 0, '更新'), 0]);
    a.push(['重装', () => runAction('reinstall', n.id, 1, '重装'), 0]);
    a.push(['卸载', () => runAction('uninstall', n.id, 1, '卸载'), 1]);
  } else if (n.health === 'leftover') {
    a.push(['清理', () => runAction('rmLeftover', n.id, 1, '清理残留'), 1]);
  } else if (n.kind === 'mcp') {
    a.push(['连接测试', () => mcpTest(n.id), 0]);
  }
  return a;
}
function renderList() {
  const rows = sortRows(ROWS());
  const maxUse = Math.max(1, ...nodes.map(n => n._use || 0));
  const tb = $('#ltbody');
  tb.innerHTML = rows.map(n => {
    const deg = (adj.get(n.id) || new Set()).size - 1;
    const h = n.health ? `<span class="hb" style="border-color:${HEALTH_COLOR[n.health]};color:${HEALTH_COLOR[n.health]}">${esc(HEALTH_LABEL[n.health] || n.health)}</span>`
      : (UP[n.id] && UP[n.id].outdated ? `<span class="hb" style="border-color:var(--warn);color:var(--warn)">可升级</span>` : '<span class="dimc">—</span>');
    const acts = rowActions(n);
    const use = n._use || 0;
    // 每次重绘都要把选中态画回来（否则勾选后一重排，行高亮就没了）
    const cls = [selected.has(n.id) ? 'sel' : '', pinned === n.id ? 'cur' : ''].filter(Boolean).join(' ');
    return `<tr data-id="${esc(n.id)}"${cls ? ` class="${cls}"` : ''}>
      <td class="ck"><input type="checkbox" data-ck="${esc(n.id)}"${selected.has(n.id) ? ' checked' : ''}></td>
      <td><span class="nm"><span class="sw" style="background:${COLORS[n.kind] || '#888'}"></span><span class="id">${esc(n.id)}</span></span>${n.description ? `<span class="desc">${esc(n.description.slice(0, 96))}</span>` : ''}</td>
      <td class="dimc">${esc(n.kind)}</td>
      <td>${n.version ? esc(n.version) : '<span class="dimc">—</span>'}${UP[n.id] && UP[n.id].latest && UP[n.id].outdated ? ` <span style="color:var(--warn)">→${esc(UP[n.id].latest)}</span>` : ''}</td>
      <td><span class="spc">${esc(n.spec || '—')}</span></td>
      <td>${h}</td>
      <td>${use ? `<span class="ubar" title="${n.usage ? '自身 ' + n.usage + ' 次' : ''}${n.usage && use !== n.usage ? ' · 含所属工具 ' + use + ' 次' : ''}"><i style="width:${Math.round(Math.sqrt(use / maxUse) * 100)}%"></i></span>${use}` : '<span class="dimc">—</span>'}</td>
      <td class="dimc">${deg}</td>
      <td><span class="ra">${acts.map((a, i) => `<button data-ra="${i}"${a[2] ? ' class="danger"' : ''}>${a[0]}</button>`).join('')}</span></td>
    </tr>`;
  }).join('') || '<tr><td class="empty" colspan="9">没有匹配的节点 —— 清掉筛选或换个搜索词</td></tr>';

  $('#lcount').textContent = `${rows.length} / ${nodes.length} 行`;
  const bulk = [...selected];
  $('#lbulk').innerHTML = bulk.length
    ? `<button data-bulk="update">批量更新 (${bulk.filter(id => { const n = byId.get(id); return n && n.spec && !n.pinned; }).length})</button>
       <button data-bulk="reinstall">批量重装</button>
       <button class="danger" data-bulk="uninstall">批量卸载</button>
       <button data-bulk="clear">清空选择</button>`
    : '';
  markSort();
  const all = $('#ckall');
  all.checked = rows.length > 0 && rows.every(n => selected.has(n.id));
  all.indeterminate = !all.checked && rows.some(n => selected.has(n.id));
}
function markSort() {
  for (const th of document.querySelectorAll('#ltable thead th[data-sort]')) {
    if (th.dataset.sort === sortKey) {
      th.classList.add('sorted');
      th.textContent = th.dataset.label + (sortDir < 0 ? ' ▾' : ' ▴');
    } else if (th.dataset.label) {
      th.textContent = th.dataset.label;
    }
  }
}
function bindList() {
  for (const th of document.querySelectorAll('#ltable thead th[data-sort]')) th.dataset.label = th.textContent;
  const tb = $('#ltbody');
  tb.onclick = e => {
    const ck = e.target.closest('[data-ck]');
    if (ck) { ck.checked ? selected.add(ck.dataset.ck) : selected.delete(ck.dataset.ck);
      ck.closest('tr').classList.toggle('sel', ck.checked); renderList(); return; }
    const ra = e.target.closest('[data-ra]');
    const tr = e.target.closest('tr');
    if (!tr) return;
    const n = byId.get(tr.dataset.id);
    if (!n) return;
    if (ra) { e.stopPropagation(); rowActions(n)[+ra.dataset.ra][1](); return; }
    highlight(n.id); show(n.id);
  };
  tb.oncontextmenu = e => {
    const tr = e.target.closest('tr'); if (!tr) return;
    const n = byId.get(tr.dataset.id); if (!n) return;
    // stopPropagation 必须有：document 上还挂着「点空白处关菜单」，
    // 不拦住的话菜单会在同一个事件里被立刻关掉
    e.preventDefault(); e.stopPropagation();
    highlight(n.id); show(n.id); openMenu(e, n);
  };
  tb.ondblclick = e => { if (e.target.closest('[data-ck],[data-ra]')) return;
    const tr = e.target.closest('tr'); if (tr) { const n = byId.get(tr.dataset.id);
      if (n && n.kind === 'skill') readFile(n.id); } };
  for (const th of document.querySelectorAll('#ltable thead th[data-sort]')) {
    th.onclick = () => {
      const k = th.dataset.sort;
      if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = k === 'usage' || k === 'deg' || k === 'health' ? -1 : 1; }
      for (const o of document.querySelectorAll('#ltable thead th')) o.classList.remove('sorted');
      markSort();
      renderList();
    };
  }
  $('#ckall').onclick = e => {
    const rows = ROWS();
    rows.forEach(n => e.target.checked ? selected.add(n.id) : selected.delete(n.id));
    renderList();
  };
  for (const c of document.querySelectorAll('.fchip')) {
    c.onclick = () => { filter = c.dataset.f;
      for (const o of document.querySelectorAll('.fchip')) o.classList.toggle('on', o === c);
      renderList(); };
  }
  $('#lbulk').onclick = e => {
    const b = e.target.closest('[data-bulk]'); if (!b) return;
    const act = b.dataset.bulk;
    if (act === 'clear') { selected.clear(); return renderList(); }
    const ids = [...selected].filter(id => { const n = byId.get(id); return n && n.spec; });
    if (!ids.length) return showPanel('批量操作', '选中的节点里没有可操作的包。');
    runBulk(act, ids);
  };
}
async function runBulk(action, ids) {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  const label = { update: '批量更新', reinstall: '批量重装', uninstall: '批量卸载' }[action];
  const pv = await (await api('/api/preview', {action, ids})).json();
  if (pv.error) return showPanel(label, '✗ ' + pv.error);
  const plan = pv.plans.map(p => p.error ? `  ✗ ${p.id}: ${p.error}` : `  $ ${p.steps.map(s => s.join(' ')).join('\n    $ ')}`).join('\n');
  if (!confirm(`${label}（${pv.plans.filter(p => !p.error).length} 个）\n\n${plan}\n\n确认执行？`)) return;
  showPanel(label, plan + '\n\n');
  await stream(await api('/api/bulk', {action, ids, confirm: true}));
  selected.clear(); renderList();
  append('\n—— 完成。重开 pi 会话生效。\n', 'ok');
}
function setView(v) {
  view = v;
  document.body.classList.toggle('list', v === 'list');
  document.body.classList.toggle('graph', v === 'graph');
  document.body.classList.toggle('flow', v === 'flow');
  $('#view').textContent = {graph: '◈ 流程视图', flow: '▤ 列表视图', list: '✦ 图谱视图'}[v];
  if (location.hash.slice(1) !== v) history.replaceState(null, '', '#' + v);
  layer.attr('display', v === 'graph' ? null : 'none');
  if (fLayer) fLayer.attr('display', v === 'flow' ? null : 'none');
  if (v === 'list') { renderList(); if (sim) sim.stop(); }
  else if (v === 'flow') { if (sim) sim.stop(); buildFlow(); fitFlow(); }
  else { if (sim) sim.alpha(.3).restart(); applyFilters(); }
}

// ================= 流程图视图（n8n / Dify 那种节点画布）=================
// 结构：配置在最上、包/扩展居中、能力（工具/钩子/技能）以圆节点挂在各自卡下。
// 一屏放不下 379 个节点，所以每张卡最多展开 6 个子节点，其余折成 +N。
// cellW 必须 >= maxLeaf * leafGap，否则相邻卡片的圆会横向咬在一起
const F = { cardW: 216, cardH: 68, cellW: 330, cellH: 250, pad: 80, top0: 60, top1: 220,
            leafR: 21, leafGap: 58, maxLeaf: 5 };
const GLYPH = {
  package: g => g.append('path').attr('d', 'M-9-7h18v14h-18z M-9-2h18 M-3.5-7v5 M3.5-7v5'),
  tool: g => { g.append('circle').attr('r', 3.2);
    g.append('path').attr('d', 'M0-9.5v3.4 M0 6.1v3.4 M-9.5 0h3.4 M6.1 0h3.4 M-6.7-6.7l2.4 2.4 M4.3 4.3l2.4 2.4 M6.7-6.7l-2.4 2.4 M-4.3 4.3l-2.4 2.4'); },
  hook: g => g.append('path').attr('d', 'M2.5-9.5L-6.5 2h6l-2 7.5L7.5-2h-6z'),
  skill: g => g.append('path').attr('d', 'M0-9.5L2.3-2.3 9.5 0 2.3 2.3 0 9.5-2.3 2.3-9.5 0-2.3-2.3z'),
  command: g => g.append('path').attr('d', 'M-6-6.5L2.5 0-6 6.5 M-1.5-6.5L7 0-1.5 6.5'),
  mcp: g => g.append('path').attr('d', 'M0-9.5L8.5-4.7 8.5 4.7 0 9.5-8.5 4.7-8.5-4.7z'),
  config: g => g.append('path').attr('d', 'M-8.5-6.5h17 M-8.5 0h17 M-8.5 6.5h17 M-3-6.5v3.5 M3.5 0v3.5 M-1 6.5v3.5'),
  sdk: g => g.append('path').attr('d', 'M0-8.5L9.5-3.7 0 1.1-9.5-3.7z M-9.5 3.7L0 8.5 9.5 3.7'),
  group: g => g.append('path').attr('d', 'M-9.5-6h7l2.2 3h9.8v10.5h-19z'),
  provider: g => { g.append('path').attr('d', 'M-9.5 0a9.5 9.5 0 1 0 19 0a9.5 9.5 0 1 0-19 0');
    g.append('path').attr('d', 'M-5.5-7.5h11v15h-11z'); },
};
let fBuilt = false;
let fNodes = new Map();      // id → <g>，搜索时调透明度用

const short = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
// 标签宽度 = 字数 × ~6.4px，必须 <= leafGap(58)，否则相邻圆的字会叠在一起
const leafName = id => {
  const seg = id.split('.').pop();
  return short(seg.length > 9 ? id.split('/').pop() : seg, 9);
};

function flowKids(n) {
  const out = [];
  for (const [dir, kind, o] of adjRel.get(n.id) || []) {
    if (dir !== 'out') continue;
    const t = byId.get(o);
    if (t && ['provides', 'hooks', 'contains', 'depends-on'].includes(kind)) out.push([kind, t]);
  }
  // 常用的排前面，卡太小塞不下全部
  out.sort((a, b) => (b[1]._use || 0) - (a[1]._use || 0) || a[1].id.localeCompare(b[1].id));
  return out;
}

function flowCurve(g, x1, y1, x2, y2, kind) {
  const dy = Math.max(26, (y2 - y1) * .42);
  g.append('path').attr('class', 'fedge ' + kind)
    .attr('d', 'M' + x1 + ',' + y1 + ' C' + x1 + ',' + (y1 + dy) + ' ' + x2 + ',' + (y2 - dy) + ' ' + x2 + ',' + y2);
}

function buildFlow() {
  if (!fLayer) {
    svg.append('defs').append('pattern')
      .attr('id', 'dots').attr('width', 24).attr('height', 24).attr('patternUnits', 'userSpaceOnUse')
      .append('circle').attr('cx', 2).attr('cy', 2).attr('r', 1.4).attr('fill', '#2b2443');
    fLayer = svg.append('g');
  }
  // 图层刚建出来时 setView 早就跑过了，可见性得在这里自己对齐
  fLayer.attr('display', view === 'flow' ? null : 'none');
  fLayer.selectAll('*').remove();
  fNodes = new Map();

  const W = innerWidth;
  const cols = Math.max(3, Math.floor((W - F.pad * 2) / F.cellW));
  const l0 = nodes.filter(n => n.kind === 'config');
  const l1 = nodes.filter(n => ['package', 'mcp', 'group', 'provider'].includes(n.kind))
    .sort((a, b) => (b._use || 0) - (a._use || 0) || a.id.localeCompare(b.id));

  const box = new Map(), leaf = new Map();
  l0.forEach((n, i) => {
    const rowW = l0.length * F.cellW;
    box.set(n.id, {x: W / 2 - rowW / 2 + i * F.cellW + (F.cellW - F.cardW) / 2, y: F.top0});
  });
  l1.forEach((n, i) => {
    const x = F.pad + (i % cols) * F.cellW, y = F.top1 + Math.floor(i / cols) * F.cellH;
    box.set(n.id, {x, y});
    const kids = flowKids(n).slice(0, F.maxLeaf);
    const cx0 = x + F.cardW / 2 - ((kids.length - 1) * F.leafGap) / 2;
    kids.forEach(([kind, t], j) => leaf.set(t.id, {x: cx0 + j * F.leafGap, y: y + F.cardH + 46, kind}));
  });

  const rows = Math.ceil(l1.length / cols);
  const H = F.top1 + rows * F.cellH + 60;
  const bgG = fLayer.append('g');          // 网格单独一层：算包围盒时要排除
  bgG.append('rect').attr('x', -4000).attr('y', -4000)
    .attr('width', W + 8000).attr('height', H + 4000).attr('fill', 'url(#dots)');

  const edgeG = fLayer.append('g'), nodeG = fLayer.append('g');

  // 连线：配置 → 包，包 → 子节点（子节点卡片优先，其次圆节点）
  for (const id of box.keys()) {
    const b = box.get(id);
    const done = new Set();
    for (const [dir, kind, o] of adjRel.get(id) || []) {
      if (dir !== 'out' || done.has(o)) continue;
      const tb = box.get(o), tl = leaf.get(o);
      const toCard = box.has(o) && !(kind === 'provides' || kind === 'hooks' || kind === 'contains');
      let x2, y2;
      if (toCard) { x2 = tb.x + F.cardW / 2; y2 = tb.y; }
      else if (tl) { x2 = tl.x; y2 = tl.y - F.leafR; }
      else if (tb) { x2 = tb.x + F.cardW / 2; y2 = tb.y; }
      else continue;
      done.add(o);
      flowCurve(edgeG, b.x + F.cardW / 2, b.y + F.cardH, x2, y2, kind);
    }
  }

  const wire = g => {
    g.on('click', e => { e.stopPropagation(); highlight(g.datum().id); show(g.datum().id); })
     .on('contextmenu', e => { e.preventDefault(); e.stopPropagation();
        highlight(g.datum().id); show(g.datum().id); openMenu(e, g.datum()); })
     .on('mouseover', e => {
        const d = g.datum();
        const tip = $('#tip');
        tip.innerHTML = '<b>' + esc(d.id) + '</b> <span class="k">' + esc(d.kind) + '</span>' +
          (d.version ? ' <span class="k">v' + esc(d.version) + '</span>' : '') +
          (d._use ? ' <span class="k">·' + d._use + '次</span>' : '') +
          (d.health ? '<br><span style="color:' + HEALTH_COLOR[d.health] + '">' + esc(HEALTH_LABEL[d.health]) + '</span>' : '') +
          (d.spec ? '<br><span class="k">' + esc(d.spec) + '</span>' : '');
        tip.style.opacity = 1;
     })
     .on('mousemove', e => {
        const tip = $('#tip');
        tip.style.left = Math.min(e.clientX + 14, innerWidth - 360) + 'px';
        tip.style.top = Math.min(e.clientY + 14, innerHeight - 120) + 'px';
     })
     .on('mouseout', () => { $('#tip').style.opacity = 0; });
  };

  // 卡片
  for (const [id, b] of box) {
    const n = byId.get(id);
    if (!n) continue;
    const g = nodeG.append('g').attr('class', 'fnode').attr('transform', 'translate(' + b.x + ',' + b.y + ')')
      .datum(n);
    const col = COLORS[n.kind] || '#888';
    g.append('rect').attr('class', 'fcard').attr('width', F.cardW).attr('height', F.cardH)
      .attr('rx', 10).attr('stroke', n.health ? HEALTH_COLOR[n.health] : col);
    const gl = g.append('g').attr('transform', 'translate(26,31)').attr('fill', 'none')
      .attr('stroke', col).attr('stroke-width', 1.7)
      .attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round');
    (GLYPH[n.kind] || GLYPH.tool)(gl);
    g.append('text').attr('class', 'fnm').attr('x', 46).attr('y', 27).text(short(n.id, 21));
    const outDeg = (adjRel.get(id) || []).filter(a => a[0] === 'out').length;
    const meta = [n.version ? 'v' + n.version : '', n._use ? n._use + '次' : '', outDeg + ' 出边']
      .filter(Boolean).join(' · ');
    g.append('text').attr('class', 'fver').attr('x', 46).attr('y', 45).text(meta);
    // 底部端口（参考图里那些灰色小菱形）
    g.append('path').attr('class', 'fport').attr('d', 'M0-6 6 0 0 6-6 0z')
      .attr('transform', 'translate(' + F.cardW / 2 + ',' + F.cardH + ')');
    fNodes.set(id, g);
    wire(g);
  }

  // 能力圆节点
  for (const [id, p] of leaf) {
    const n = byId.get(id);
    if (!n) continue;
    const col = COLORS[n.kind] || '#888';
    const g = nodeG.append('g').attr('class', 'fleaf').datum(n)
      .attr('transform', 'translate(' + p.x + ',' + p.y + ')');
    g.append('circle').attr('r', F.leafR).attr('stroke', n.health ? HEALTH_COLOR[n.health] : col);
    const gl = g.append('g').attr('transform', 'scale(.72)').attr('fill', 'none')
      .attr('stroke', '#cfc8e8').attr('stroke-width', 2.1)
      .attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round');
    (GLYPH[n.kind] || GLYPH.tool)(gl);
    if (!n.health) {
      g.append('text').attr('class', 'tick').attr('x', F.leafR - 3).attr('y', F.leafR - 1).text('✓');
    }
    // 两行交错摆，再短的标签也不会糊成一条
    const alt = Math.round((p.x - F.pad) / F.leafGap) & 1;
    g.append('text').attr('class', 'flnm').attr('y', F.leafR + 16 + alt * 13).attr('text-anchor', 'middle')
      .text(leafName(n.id));
    fNodes.set(id, g);
    wire(g);
  }

  // 子节点放不下的，折成 +N
  for (const n of l1) {
    const b = box.get(n.id);
    const kids = flowKids(n);
    if (!b || kids.length <= F.maxLeaf || !kids.length) continue;
    const last = leaf.get(kids[F.maxLeaf - 1][1].id);
    // 紧贴最后一个圆，别飘到隔壁卡片的地盘上
    nodeG.append('text').attr('class', 'fmore')
      .attr('x', (last ? last.x : b.x + F.cardW / 2) + F.leafGap * .78)
      .attr('y', (last ? last.y : b.y + F.cardH + 46) + 5)
      .text('+' + (kids.length - F.maxLeaf));
  }
  fBuilt = true;
}

function fitFlow() {
  if (!fLayer) return;
  // 只量内容层：背景网格铺得很大，算进去会缩到看不清
  const content = fLayer.selectAll('.fnode,.fleaf,.fmore,.fedge');
  if (content.empty()) return;
  const first = content.node().getBBox();
  const bb = {x: first.x, y: first.y, width: first.width, height: first.height};
  content.each(function () {
    const b = this.getBBox();
    const x0 = Math.min(bb.x, b.x), y0 = Math.min(bb.y, b.y);
    bb.width = Math.max(bb.x + bb.width, b.x + b.width) - x0;
    bb.height = Math.max(bb.y + bb.height, b.y + b.height) - y0;
    bb.x = x0; bb.y = y0;
  });
  const pad = 60;
  bb.x -= pad; bb.y -= pad; bb.width += pad * 2; bb.height += pad * 2;
  // 缩放下限：硬要一屏塞完会把字缩到看不清，宁可让用户往下拖
  const k = Math.max(.72, Math.min(innerWidth / bb.width, 1.35));
  // 宽度居中、高度贴顶（下面留白比上面留白更像编辑器）
  svg.call(zoom.transform, d3.zoomIdentity
    .translate(innerWidth / 2 - k * (bb.x + bb.width / 2), 64 - k * bb.y)
    .scale(k));
}

function applyFlowFilter() {
  if (!fBuilt) return;
  const t = ($('#q').value || '').trim().toLowerCase();
  for (const [id, g] of fNodes) {
    const n = byId.get(id) || {};
    const hit = !t || (id + ' ' + (n.description || '')).toLowerCase().includes(t);
    g.attr('opacity', hit ? 1 : .1);
  }
  fLayer.selectAll('.fedge').attr('opacity', t ? .18 : null);
}

// ================= 搜索 =================
$('#q').oninput = e => {
  const t = e.target.value.trim().toLowerCase();
  if (view === 'list') return renderList();
  if (view === 'flow') return applyFlowFilter();
  if (!t) return applyFilters();
  sel.attr('opacity', d => (d.id + ' ' + (d.description || '')).toLowerCase().includes(t) ? 1 : .07);
  tsel.attr('opacity', d => (d.id + ' ' + (d.description || '')).toLowerCase().includes(t) ? 1 : .05);
};
$('#q').onkeydown = e => {
  if (e.key !== 'Enter') return;
  const t = e.target.value.trim().toLowerCase();
  const hit = nodes.find(n => n.id.toLowerCase() === t) || nodes.find(n => n.id.toLowerCase().includes(t)) ||
              nodes.find(n => (n.description || '').toLowerCase().includes(t));
  if (hit) { highlight(hit.id); show(hit.id); if (view === 'graph') focusNode(hit); }
};

// ================= 重新扫描 =================
$('#refresh').onclick = async () => {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  showPanel('重新扫描', '正在跑 pi-graph.py + pi-graph-render.py…\n\n');
  await stream(await api('/api/refresh', {}));
  location.reload();
};

// ================= 检查更新 =================
$('#updates').onclick = async () => {
  if (OFFLINE) return showPanel('只读模式', NEED_SERVER);
  showPanel('检查更新', '查 npm registry（6 小时缓存）…\n\n');
  const r = await (await api('/api/updates?force=1')).json();
  if (r.error) return append('\n✗ ' + r.error + '\n', 'err');
  Object.assign(UP, r.pkgs || {});
  const list = Object.entries(UP).map(([id, u]) => `${u.outdated ? '↑' : ' '} ${id.padEnd(28)} ${u.current || '?'} → ${u.latest || (u.error ? 'ERR' : '?')}`);
  append(list.join('\n') + '\n', null);
  append(`\n可升级 ${Object.values(UP).filter(u => u.outdated).length} 个。右键节点即可更新。\n`, 'ok');
  render();
  if (view === 'list') renderList();
};

// ================= 启动 =================
const mode = $('#mode');
function paintMode() {
  mode.textContent = OFFLINE ? '后端未连' : '动作已连接';
  mode.className = OFFLINE ? 'off' : 'on';
  mode.title = OFFLINE
    ? '本地后端没在跑：先跑一次 pi-graph-agent.sh install，之后开页面就能直接改'
    : '已连接 pi-graph-serve.mjs（127.0.0.1，白名单命令）';
}
let myBuild = 0;         // 本页构建时间；后端报的 HTML mtime 更新就说明我过期了
let staleOffered = false;
function offerReload() {
  if (staleOffered) return;
  staleOffered = true;
  toast('warn', '页面已更新（当前是旧副本）· 点此重新载入', 0, () => location.reload());
}
async function ping() {
  try {
    // 必须带上 token：后端用 tokenOk 告诉页面「你手里这份还能不能用」
    const r = await fetch(BASE + '/api/ping', {cache: 'no-store', headers: {'x-token': TOKEN}});
    const j = await r.json();
    OFFLINE = !(j && j.ok && j.tokenOk);
    // 我改过脚本、重建过 HTML 之后，已经开着的标签页不会自己刷新 —— 提醒一下
    if (j && j.htmlMtime) {
      if (!myBuild) myBuild = j.htmlMtime;
      else if (j.htmlMtime > myBuild + 1000) offerReload();
    }
    // ping 也用来兜底：SSE 断了也要能发现后端回来没
    if (j && j.ok && j.tokenOk && !es) connectLive();
  } catch {
    OFFLINE = true;
  }
  paintMode();
}
setInterval(() => { if (!OFFLINE) ping(); }, 9000);
document.addEventListener('visibilitychange', () => { if (!document.hidden && !OFFLINE) ping(); });

// ================= 实时同步 =================
// 后端盯着 pi-graph.json / HTML 的 mtime，一变就推 SSE。收到后原地换数据、保住
// 当前视图和筛选，不整页刷新（刷新会把终端的滚动位置和输出全丢掉）。
let es = null;
let liveTimer = 0;
let liveRetry = 0;
function setLive(state) {
  const el = $('#live');
  if (!el) return;
  el.textContent = {on: '● 实时', off: '○ 实时关', wait: '◌ 实时…'}[state];
  el.className = state === 'on' ? 'on' : state === 'wait' ? 'wait' : 'off';
  el.title = state === 'on'
    ? '已连上实时同步：图谱一变，这个页面自动更新'
    : state === 'wait'
      ? '正在连接实时同步…'
      : '实时同步已关闭（后端 --no-live，或连接断开）';
}
async function pullGraph() {
  const r = await fetch(BASE + '/graph.json', {cache: 'no-store', headers: {'x-token': TOKEN}});
  const j = await r.json();
  applyGraph(j);
}
function applyGraph(j) {
  if (!j || !Array.isArray(j.nodes)) return;
  DATA.nodes = j.nodes;
  DATA.links = (j.edges || []).map(e => ({source: e.from, target: e.to, kind: e.kind}));
  nodes = DATA.nodes;
  links = DATA.links;
  // 选中的节点可能已经消失了，清掉免得后面报错
  const ids = new Set(nodes.map(n => n.id));
  for (const id of [...selected]) if (!ids.has(id)) selected.delete(id);
  if (pinned && !ids.has(pinned)) pinned = null;
  // 先重建索引再渲染：否则列表/流程视图会拿着上一版 byId 查不到新节点
  indexGraph();
  if (view === 'list') renderList();
  else if (view === 'flow') buildFlow();
  else render();   // render() 内部会重新去重叠标签
  headerStat();
}
function connectLive() {
  if (OFFLINE) return setLive('off');
  if (es) { try { es.close(); } catch {} es = null; }
  setLive('wait');
  try {
    // EventSource 不能带自定义头，token 只能走查询串（本来就是本机回环）
    es = new EventSource(BASE + '/api/events?token=' + encodeURIComponent(TOKEN));
  } catch {
    return setLive('off');
  }
  es.addEventListener('open', () => { liveRetry = 0; setLive('on'); });
  es.addEventListener('graph', () => {
    // 抖动合并：一次保存可能触发多次 mtime 变化
    clearTimeout(liveTimer);
    liveTimer = setTimeout(() => {
      pullGraph().then(() => toast('info', '图谱已自动更新', 2200)).catch(() => {});
    }, 350);
  });
  es.addEventListener('html', () => offerReload());
  es.onerror = () => {
    setLive('off');
    if (es) { try { es.close(); } catch {} es = null; }
    // 退避重连，别在服务器没起来时刷屏
    liveRetry = Math.min(liveRetry + 1, 6);
    setTimeout(connectLive, 1000 * liveRetry);
  };
}

paintMode();
connectLive();
$('#view').onclick = () => setView({graph: 'flow', flow: 'list', list: 'graph'}[view]);
// Ctrl+`（或 Cmd+`）开关终端
addEventListener('keydown', e => {
  if (e.key === '`' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); toggleTerm(); }
});
addEventListener('hashchange', () => {
  const h = location.hash.slice(1);
  setView(['graph', 'flow', 'list'].includes(h) ? h : 'graph');
});
bindList();
render();
setView(view);
ping();
addEventListener('resize', () => {
  if (!sim) return;
  sim.force('center', d3.forceCenter(innerWidth / 2, innerHeight / 2))
     .force('x', d3.forceX(innerWidth / 2)).force('y', d3.forceY(innerHeight / 2)).alpha(.3).restart();
});
</script>
</body></html>
"""


def local_token() -> str:
  """读页面/后端共用的令牌；没有就交给 pi-graph.py 生成（单一来源，避免两处实现漂移）。"""
  f = AGENT / "pi-graph.token"
  try:
    t = f.read_text(encoding="utf-8").strip()
    if t:
      return t
  except OSError:
    pass
  try:
    r = subprocess.run(
      [sys.executable, str(Path(__file__).resolve().parent / "pi-graph.py"), "token"],
      capture_output=True,
      text=True,
      check=True,
      timeout=30,
    )
    return r.stdout.strip()
  except (OSError, subprocess.SubprocessError):
    return ""


def b64(name: str) -> str:
  p = VENDOR / name
  return base64.b64encode(p.read_bytes()).decode() if p.exists() else ""


def build(out_path: Path):
  if not SRC.exists():
    sys.exit(f"找不到图谱数据 {SRC}\n先运行: python3 ~/.pi/scripts/pi-graph.py")
  try:
    G = json.loads(SRC.read_text(encoding="utf-8"))
  except (OSError, ValueError) as e:
    sys.exit(f"读取失败 {SRC}: {e}")

  nodes, links = G["nodes"], G["edges"]
  ids = {n["id"] for n in nodes}

  # 孤立的 skill 没有边，挂到一个 group 节点上，否则力导向图里它们只会乱飘
  orphans = [
    n
    for n in nodes
    if n["kind"] == "skill"
    and not any(e["from"] == n["id"] or e["to"] == n["id"] for e in links)
  ]
  if orphans:
    nodes.append({"id": "skills", "kind": "group", "label": "skills"})
    ids.add("skills")
    links += [{"from": "skills", "to": n["id"], "kind": "contains"} for n in orphans]

  links = [e for e in links if e["from"] in ids and e["to"] in ids]

  kinds: dict = {}
  for n in nodes:
    kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
  stat = " · ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
  health = [n for n in nodes if n.get("health")]
  stat += f"　|　边 {len(links)}"
  if health:
    stat += f"　|　健康 {len(health)}"

  payload = {
    "nodes": nodes,
    "links": [
      {"source": e["from"], "target": e["to"], "kind": e["kind"]} for e in links
    ],
  }
  d3src = (
    (VENDOR / "d3.min.js").read_text(encoding="utf-8")
    if (VENDOR / "d3.min.js").exists()
    else ""
  )
  if not d3src:
    sys.exit(f"缺 {VENDOR / 'd3.min.js'}，先跑 vendor 下载（见脚本头注释）")

  out = (
    HTML.replace("__TOKEN__", local_token())
    .replace("__D3__", d3src)
    .replace("__DATA__", json.dumps(payload, ensure_ascii=False))
    .replace("__COLORS__", json.dumps(COLORS))
    .replace("__HCOLOR__", json.dumps(HEALTH_COLOR))
    .replace("__HLABEL__", json.dumps(HEALTH_LABEL, ensure_ascii=False))
    .replace("__STAT__", stat)
    .replace("__FONT_VT__", b64("vt323.woff2"))
    .replace("__FONT_P2P__", b64("pressstart2p.woff2"))
  )
  for k, v in PALETTE.items():
    out = out.replace(f"__P_{k.upper()}__", v)
  return out, stat, len(nodes), len(links), len(health)


if __name__ == "__main__":
  ap = argparse.ArgumentParser()
  ap.add_argument("-o", "--out", default=str(AGENT / "pi-graph.html"))
  ap.add_argument("--open", action="store_true", help="生成后用默认浏览器打开")
  a = ap.parse_args()
  html, stat, nn, ne, nh = build(Path(a.out))
  Path(a.out).write_text(html, encoding="utf-8")
  print(f"节点 {nn}  关系 {ne}  健康 {nh}")
  print(f"统计 {stat}")
  print(f"输出 {a.out}  ({len(html) // 1024} KB)")
  if a.open:
    import subprocess

    subprocess.run(["open", a.out], check=False)
