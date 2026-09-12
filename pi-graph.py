#!/usr/bin/env python3
"""Pi 生态知识图谱 — 本机提取器。

数据源（优先级从高到低）：
  1. 运行期工具注册表  ~/.pi/agent/pi-registry.json（fabric tools.list 导出，权威）
  2. 包元数据          ~/.pi/agent/npm/node_modules/*/package.json
  3. 扩展源码          各包的 index.ts（正则抓 hook / command）
  4. skills            ~/.pi/agent/skills/*/SKILL.md
  5. MCP 配置          ~/.pi/agent/{mcp,fabric,telegram}.json

节点: package / sdk / tool / command / hook / skill / mcp / config
边:   depends-on / provides / hooks / declares / configures / contains
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HOME = Path.home()
AGENT = HOME / ".pi" / "agent"
NPM = AGENT / "npm" / "node_modules"
REGISTRY = AGENT / "pi-registry.json"
OUT = AGENT / "pi-graph.json"

SDK_PREFIXES = ("@earendil-works/", "@mariozechner/")

nodes: dict = {}
edges: set = set()


def canon(spec: str) -> str:
    """settings.json 的包源 → 与 npm 目录一致的规范名。"""
    s = spec.strip()
    for pre in ("npm:", "git+", "git:", "https://", "http://"):
        if s.startswith(pre):
            s = s[len(pre) :]
    return s.rstrip("/").removeprefix("github.com/")


def split_spec(spec: str):
    """settings 的包源 → (安装目录, 版本/ref)。ref 非空 = 锁定，不参与 update。"""
    s = spec.strip()
    if s.startswith("npm:"):
        rest = s[4:]
        m = re.search(r"@([^/@]+)$", rest)  # @scope/name@1.2.3 里 scope 的 @ 不算版本
        if m:
            return NPM / rest[: m.start()], m.group(1)
        return NPM / rest, None
    rest = s
    for pre in ("git+", "git:", "https://", "http://", "ssh://"):
        if rest.startswith(pre):
            rest = rest[len(pre) :]
            break
    m = re.search(r"@([^/@]+)$", rest)
    ref = None
    if m:
        ref, rest = m.group(1), rest[: m.start()]
    return AGENT / "git" / rest.removeprefix("git@").replace(":", "/").strip("/"), ref


def repo_url(spec: str) -> str:
    """包源的浏览地址（右键「打开仓库」）。"""
    s = spec.strip()
    if s.startswith("npm:"):
        p, _ = split_spec(s)
        rel = (
            "/".join(p.parts[-2:])
            if len(p.parts) >= 2 and p.parts[-2].startswith("@")
            else p.name
        )
        return "https://www.npmjs.com/package/" + rel
    d, _ = split_spec(s)
    try:
        return "https://" + str(d.relative_to(AGENT / "git"))
    except ValueError:
        return ""


def node(nid: str, kind: str, **kw):
    n = nodes.setdefault(nid, {"id": nid, "kind": kind, "label": nid})
    n.update(kw)
    return n


def edge(a: str, b: str, kind: str):
    if a != b:
        edges.add((a, b, kind))


TOKEN_FILE = AGENT / "pi-graph.token"


def stable_token() -> str:
    """本地回环接口的访问令牌：固定一份，页面与后端共用。

    固定而不是每次随机 —— 这样双击打开 HTML 也能直接连上后端。
    随机 token 只挡得住「不知道 token」的跨站脚本，
    而这份文件只有本机进程读得到，安全性等价、可用性好得多。
    """
    try:
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if t:
            return t
    except OSError:
        pass
    import secrets

    t = secrets.token_urlsafe(18)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(t, encoding="utf-8")
    TOKEN_FILE.chmod(0o600)
    return t


# ---------- 查询模式（只读图谱，不跑提取）----------
QUERY_HELP = """用法:
  pi-graph.py                 重新提取本机图谱
  pi-graph.py stats           概览统计
  pi-graph.py find <词>       按 id / 描述搜索节点
  pi-graph.py show <节点id>   节点详情与全部相邻关系
  pi-graph.py sessions [N]    最近 N 个会话（轮数/工具数/带思考轮数/体积）
  pi-graph.py session <id>    单个会话的轮次链：每轮耗时、思考字数、工具调用
  pi-graph.py serve [--port N] [--dry]  重新提取+渲染，起本地右键动作服务
  pi-graph.py token           打印（必要时生成）本地接口令牌
  pi-graph.py --selftest      自检
  pi-graph.py <词>            find 的简写
"""


def _load():
    if not OUT.exists():
        sys.exit(f"找不到图谱 {OUT}\n先生成: python3 {Path(__file__).name}")
    try:
        return json.loads(OUT.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"图谱读取失败 {OUT}: {e}")


def _index(G):
    """返回 (id->node, id->[(方向, 关系, 对端)])"""
    by_id = {n["id"]: n for n in G["nodes"]}
    adj = {i: [] for i in by_id}
    for e in G["edges"]:
        adj.setdefault(e["from"], []).append(("out", e["kind"], e["to"]))
        adj.setdefault(e["to"], []).append(("in", e["kind"], e["from"]))
    return by_id, adj


def _q_stats(G):
    print(f"节点 {len(G['nodes'])}   关系 {len(G['edges'])}")
    h = Counter(n["health"] for n in G["nodes"] if n.get("health"))
    if h:
        print("  健康  " + "  ".join(f"{k} {v}" for k, v in h.most_common()))
        for n in G["nodes"]:
            if n.get("health"):
                print(f"    {n['health']:<12} {n['id']}  {n.get('healthDetail', '')}")
    used = sorted((n for n in G["nodes"] if n.get("usage")), key=lambda n: -n["usage"])[
        :12
    ]
    if used:
        print("  最常用  " + "  ".join(f"{n['id']}={n['usage']}" for n in used))
    for name, counter in (
        ("节点", Counter(n["kind"] for n in G["nodes"])),
        ("关系", Counter(e["kind"] for e in G["edges"])),
    ):
        print(f"  {name}  " + "  ".join(f"{k} {v}" for k, v in counter.most_common()))


def _q_find(G, term):
    t = term.lower()
    hits = [
        n
        for n in G["nodes"]
        if t in n["id"].lower() or t in (n.get("description") or "").lower()
    ]
    if not hits:
        sys.exit(f"无匹配: {term}")
    hits.sort(key=lambda n: (t not in n["id"].lower(), len(n["id"])))
    for n in hits[:40]:
        d = f"  — {n['description'][:96]}" if n.get("description") else ""
        print(f"{n['id']}  [{n['kind']}]{d}")
    if len(hits) > 40:
        print(f"… 另有 {len(hits) - 40} 条")


def _q_show(G, nid):
    by_id, adj = _index(G)
    n = by_id.get(nid)
    if not n:
        near = [i for i in by_id if nid.lower() in i.lower()][:8]
        sys.exit(f"没有节点 {nid}" + ("\n候选: " + ", ".join(near) if near else ""))
    print(f"{n['id']}  [{n['kind']}]")
    for k in ("description", "version", "ref", "risk", "spec", "path", "repo"):
        if n.get(k):
            print(f"  {k}: {n[k]}")
    if n.get("health"):
        print(f"  health: {n['health']} — {n.get('healthDetail', '')}")
    if n.get("usage"):
        print(f"  usage: {n['usage']} 次调用（来自会话转录）")
    rel = adj.get(nid, [])
    if not rel:
        print("  (无关系边)")
        return
    print(f"  ── {len(rel)} 条关系")
    for kind in sorted({k for _, k, _ in rel}):
        outs = sorted(o for d, k, o in rel if k == kind and d == "out")
        ins = sorted(o for d, k, o in rel if k == kind and d == "in")
        if outs:
            print(
                f"  {kind} → "
                + "  ".join(outs[:14])
                + ("  …" if len(outs) > 14 else "")
            )
        if ins:
            print(
                f"  {kind} ← " + "  ".join(ins[:14]) + ("  …" if len(ins) > 14 else "")
            )


def _forget(name: str) -> None:
    """把包从 npm 工作区清单里摘掉（改前留备份）。

    卸载残留之所以会「复活」，是因为 pi remove 只动 settings.json，
    而 ~/.pi/agent/npm/package.json 里还留着这个依赖，npm install 会照着装回来。
    """
    pj = AGENT / "npm" / "package.json"
    if not pj.exists():
        sys.exit(f"找不到 {pj}")
    try:
        j = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"读不了 {pj}: {e}")

    hit = []
    for key in ("dependencies", "devDependencies", "optionalDependencies"):
        deps = j.get(key) or {}
        if name in deps:
            del deps[name]
            j[key] = deps
            hit.append(key)
    if not hit:
        print(f"{name} 不在 npm 工作区清单里，无需处理")
        return

    import shutil
    import time

    bak = pj.with_suffix(f".json.bak-forget-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(pj, bak)
    tmp = pj.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(j, indent=2) + "\n", encoding="utf-8")
    tmp.replace(pj)
    print(f"已从 npm 工作区清单移除 {name}（{', '.join(hit)}）；备份 {bak.name}")


def _selftest():
    """显式 raise 而非 assert —— 后者会被 python -O 静默剥掉，自检就失去意义。"""
    G = _load()
    by_id, adj = _index(G)

    def check(ok, msg):
        if not ok:
            raise SystemExit(f"自检失败: {msg}")

    check(by_id, "图谱为空")
    check(G["edges"], "没有关系边")
    for e in G["edges"]:
        check(e["from"] in by_id, f"悬空边 from={e['from']}")
        check(e["to"] in by_id, f"悬空边 to={e['to']}")
    pid = next((i for i in by_id if i.startswith("pi-")), None)
    check(pid, "没有 pi-* 包节点")
    kinds = {k for _, k, _ in adj.get(pid, [])}
    check("provides" in kinds, f"{pid} 缺少 provides 关系")
    check("depends-on" in kinds, f"{pid} 缺少 depends-on 关系")
    pkgs = [n for n in by_id.values() if n["kind"] == "package" and n.get("spec")]
    check(pkgs, "settings 的包没有 spec 字段（右键动作无法定位）")
    check(any(n.get("path") for n in pkgs), "没有任何包解析出安装路径")
    sess = _sess_files()
    check(sess, "找不到任何会话文件")
    srows = _sess_rows(sess[0])
    check(any(r.get("type") == "message" for r in srows), "最新会话里没有 message 条目")
    sturns = _sess_turns(srows)
    check(sturns, "最新会话解析不出任何轮")
    check(
        all(t["start"] and isinstance(t["tools"], list) for t in sturns),
        "轮节点缺 start / tools 字段",
    )
    html = AGENT / "pi-graph.html"
    if html.exists():
        check("contextmenu" in html.read_text(encoding="utf-8"), "HTML 里没有右键菜单")
    unhealthy = {n["id"]: n.get("health") for n in by_id.values() if n.get("health")}
    check(
        all(
            v in ("missing", "broken-deps", "duplicate", "inactive", "leftover")
            for v in unhealthy.values()
        ),
        f"未知健康标记: {unhealthy}",
    )
    check(by_id.get("pi.bash", {}).get("usage", 0) > 100, "pi.bash 的使用热度没统计到")
    check(any(n.get("npmName") for n in by_id.values()), "没有 npmName，检查更新会失效")
    print(
        f"自检通过：{len(by_id)} 节点 / {len(G['edges'])} 边 / 抽样 {pid} / 带 spec 包 {len(pkgs)}"
        f" / 健康 {len(unhealthy)}"
    )


# ---------- 会话图（PiX 式：会话是树，轮是节点） ----------
SESSIONS = AGENT / "sessions"


def _sess_files():
    if not SESSIONS.is_dir():
        sys.exit(f"找不到会话目录 {SESSIONS}")
    return sorted(
        SESSIONS.glob("*/*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True
    )


def _sess_rows(path):
    """读一个会话文件。文件可能在读的瞬间被删/被换（会话随时在写），失败就当空。"""
    rows = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return rows
    for line in text.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _sess_turns(rows):
    """条目 → 轮。每条 user 消息开启一轮，其后的 assistant / toolResult 归它。"""
    turns, cur = [], None
    for r in rows:
        if r.get("type") != "message":
            continue
        m = r.get("message") or {}
        role, ts = m.get("role"), r.get("timestamp") or ""
        if role == "user":
            cur = {
                "start": ts,
                "end": ts,
                "think": 0,
                "tools": [],
                "results": 0,
                "text": 0,
            }
            turns.append(cur)
        if cur is None:
            continue
        if ts:
            cur["end"] = ts
        for c in m.get("content") or []:
            t = c.get("type")
            if t == "thinking":
                cur["think"] += len(c.get("thinking") or "")
            elif t == "toolCall":
                cur["tools"].append(c.get("name") or "?")
            elif t == "text":
                cur["text"] += len(c.get("text") or "")
        if role == "toolResult":
            cur["results"] += 1
    return turns


def _sess_branches(rows):
    """分叉点 = 有多个子节点的 parentId 个数（PiX 的 branch 在这边就是它）。"""
    kids = Counter(r.get("parentId") for r in rows if r.get("parentId"))
    return sum(1 for v in kids.values() if v > 1)


def _sess_secs(t0, t1):
    from datetime import datetime

    try:
        a = datetime.fromisoformat(t0.replace("Z", "+00:00"))
        b = datetime.fromisoformat(t1.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (b - a).total_seconds())


def _sess_summary(p):
    """一个会话的概览。文本输出和 --json 共用这一份数据，不各算一遍。"""
    rows = _sess_rows(p)
    turns = _sess_turns(rows)
    first = next((r.get("timestamp") for r in rows if r.get("timestamp")), "")
    return {
        "id": p.stem,
        "project": p.parent.name,
        "started": first,
        "entries": len(rows),
        "turns": len(turns),
        "tools": sum(len(t["tools"]) for t in turns),
        "withThinking": sum(1 for t in turns if t["think"]),
        "sizeMB": round(p.stat().st_size / 1e6, 1),
    }


def _q_sessions(limit, as_json=False):
    files = _sess_files()
    if not files:
        sys.exit("没有会话文件")
    out = [_sess_summary(p) for p in files[:limit]]
    if as_json:
        print(json.dumps({"total": len(files), "sessions": out}, ensure_ascii=False))
        return
    print(f"{min(limit, len(files))}/{len(files)} 个会话（按最近修改）")
    for s in out:
        print(
            f"  {s['id'][:13]:<14} {s['started'][:16]}  {s['turns']:>4}轮 {s['tools']:>4}工具 "
            f"{s['withThinking']:>4}带思考 {s['sizeMB']:>6.1f}MB  {s['project']}"
        )


def _q_session(sid, as_json=False):
    hits = [p for p in _sess_files() if sid in p.stem]
    if not hits:
        sys.exit(f"无匹配会话: {sid}")
    p = hits[0]
    rows = _sess_rows(p)
    turns = _sess_turns(rows)
    data = {
        "id": p.stem,
        "path": str(p),
        "project": p.parent.name,
        "entries": len(rows),
        "branches": _sess_branches(rows),
        "sizeMB": round(p.stat().st_size / 1e6, 1),
        "turns": [
            {
                "n": i,
                "start": t["start"],
                "seconds": round(_sess_secs(t["start"], t["end"]), 1),
                "thinkingChars": t["think"],
                "textChars": t["text"],
                "toolResults": t["results"],
                "tools": t["tools"],
            }
            for i, t in enumerate(turns, 1)
        ],
    }
    if as_json:
        print(json.dumps(data, ensure_ascii=False))
        return
    if len(hits) > 1:
        print(f"⚠️  {len(hits)} 个会话匹配 {sid}，取最近的一个；要精确定位请给更长的前缀")
    print(f"会话 {data['id']}")
    print(
        f"  条目 {data['entries']}   轮 {len(turns)}   分叉点 {data['branches']}   "
        f"{data['sizeMB']}MB   {data['project']}"
    )
    for t in data["turns"]:
        names = Counter(t["tools"]).most_common(4)
        tools = " ".join(f"{n}x{c}" if c > 1 else n for n, c in names) or "-"
        print(
            f"  #{t['n']:<4} {t['start'][11:19]} {t['seconds']:>6.1f}s  "
            f"思考{t['thinkingChars']:>6}字 工具{len(t['tools']):>3}个: {tools[:58]}"
        )


def _serve(rest):
    """重新提取 + 渲染，然后起本地动作服务（仅 127.0.0.1）。"""
    import shutil
    import subprocess

    here = Path(__file__).resolve().parent
    for s in ("pi-graph.py", "pi-graph-render.py"):
        subprocess.run([sys.executable, str(here / s)], check=False)
    node_bin = shutil.which("node") or shutil.which("bun")
    if not node_bin:
        sys.exit("找不到 node / bun，无法起服务")
    sys.exit(
        subprocess.run([node_bin, str(here / "pi-graph-serve.mjs"), *rest]).returncode
    )


if len(sys.argv) > 1:
    # query 模式：读现成图谱，不重新提取
    _arg, _rest = sys.argv[1], sys.argv[2:]
    if _arg in ("-h", "--help", "help"):
        print(QUERY_HELP)
    elif _arg == "token":
        print(stable_token())
    elif _arg == "forget":
        # 从 npm 工作区清单里摘掉一个包：光删目录没用，
        # ~/.pi/agent/npm/package.json 里还列着它的话，npm install 会装回来
        if not _rest:
            sys.exit("forget 需要包名")
        _forget(_rest[0])
    elif _arg == "--selftest":
        _selftest()
    elif _arg == "serve":
        _serve(_rest)
    elif _arg == "sessions":
        _json = "--json" in _rest
        _args = [a for a in _rest if a != "--json"]
        try:
            _limit = int(_args[0]) if _args else 20
        except ValueError:
            # isdigit() 挡不住 '²' 这类 Unicode 数字，这里才是真的守卫
            sys.exit(f"sessions 的参数应是数字: {_args[0]}")
        _q_sessions(_limit, _json)
    elif _arg == "session":
        _json = "--json" in _rest
        _args = [a for a in _rest if a != "--json"]
        if not _args:
            sys.exit("session 需要会话 id 前缀")
        _q_session(_args[0], _json)
    else:
        _g = _load()
        if _arg == "stats":
            _q_stats(_g)
        elif _arg == "show":
            if not _rest:
                sys.exit("show 需要节点 id")
            _q_show(_g, _rest[0])
        elif _arg == "find":
            if not _rest:
                sys.exit("find 需要搜索词")
            _q_find(_g, " ".join(_rest))
        else:
            _q_find(_g, " ".join([_arg, *_rest]))
    sys.exit(0)


# ---------- 1. 运行期注册表：权威的「谁提供什么」 ----------
providers: Counter = Counter()
if REGISTRY.exists():
    try:
        reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        sys.exit(f"读取注册表失败 {REGISTRY}: {e}")
    for t in reg:
        ns = t.get("namespace") or ""
        prov = t.get("provider") or "unknown"
        providers[prov] += 1
        tool_id = t.get("ref") or f"{prov}.{t['name']}"
        node(
            tool_id,
            "tool",
            name=t["name"],
            risk=t.get("risk"),
            description=(t.get("desc") or "")[:160],
        )
        # namespace 里带 extension: 前缀的就是真正的所属扩展；
        # 其余 namespace（linear / blender / artificial-analysis）是 MCP 服务器名
        owner_kind = "provider"
        if ns.startswith("extension:"):
            owner = ns.split(":", 1)[1]
        else:
            owner = ns or prov
            if prov == "mcp":
                owner_kind = "mcp"
        node(owner, owner_kind)
        edge(owner, tool_id, "provides")
else:
    print(
        f"⚠️  未找到 {REGISTRY}，跳过运行期数据（先用 fabric tools.list 导出）",
        file=sys.stderr,
    )


# ---------- 2. 已安装的 pi 包 ----------
def pkg_name(pj: Path) -> str:
    parent = pj.parent
    if parent.parent.name.startswith("@"):
        return f"{parent.parent.name}/{parent.name}"
    return parent.name


for pj in list(NPM.glob("*/package.json")) + list(NPM.glob("@*/*/package.json")):
    name = pkg_name(pj)
    # npm 安装用的临时目录（.pi-discord-AiTbzHJM）不是包
    if name.startswith(".") or "/." in name:
        continue
    try:
        j = json.loads(pj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    deps = list({**(j.get("dependencies") or {}), **(j.get("peerDependencies") or {})})
    base = name.split("/")[-1].lower()
    if not (
        base.startswith("pi-")
        or base == "pi"
        or any(d.startswith(SDK_PREFIXES) for d in deps)
    ):
        continue
    repo = j.get("repository")
    if isinstance(repo, dict):
        repo = repo.get("url")
    if repo:
        repo = (
            re.sub(r"^git\+", "", repo)
            .replace("git://", "https://")
            .removesuffix(".git")
        )
    node(
        name,
        "package",
        version=j.get("version"),
        repo=repo,
        description=(j.get("description") or "")[:140],
        path=str(pj.parent),
        installed=True,
    )
    # 运行期注册表可能先把它建成 provider（extension:pi-lens 的 namespace）——
    # 同一个 id 只能有一个 kind，包身份更可操作，优先级更高
    nodes[name]["kind"] = "package"
    for d in deps:
        if d.startswith(SDK_PREFIXES):
            node(d, "sdk")
            edge(name, d, "depends-on")


# ---------- 3. 扩展源码：hook 与 command ----------
PKG_DIRS = [p for p in NPM.iterdir() if p.is_dir() and p.name.startswith("pi-")]
PKG_DIRS += [p for p in NPM.glob("@*/*") if p.is_dir() and p.name.startswith("pi-")]

for d in PKG_DIRS:
    src = next(
        (
            f
            for f in (d / "index.ts", d / "index.js", d / "src" / "index.ts")
            if f.exists()
        ),
        None,
    )
    if not src:
        continue
    try:
        txt = src.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    nm = d.name if not d.parent.name.startswith("@") else f"{d.parent.name}/{d.name}"
    hooks = sorted(set(re.findall(r'\bon\(\s*["\']([a-z_]{3,})["\']', txt)))
    cmds = sorted(set(re.findall(r'["\']\/([a-z][a-z0-9-]{1,})["\']', txt)))
    if not (hooks or cmds):
        continue
    node(nm, "package")
    for h in hooks:
        node(h, "hook")
        edge(nm, h, "hooks")
    for c in cmds:
        node("/" + c, "command")
        edge(nm, "/" + c, "provides")


# ---------- 4. skills ----------
for sk in list((AGENT / "skills").glob("*/SKILL.md")) + list(
    (HOME / ".agents/skills").glob("*/SKILL.md")
):
    try:
        head = sk.read_text(encoding="utf-8", errors="replace")[:900]
    except OSError:
        continue
    m = re.search(r"^name:\s*(.+)$", head, re.M)
    # frontmatter 里 name 可能带引号（name: "pdf"），带引号的 id 会让右键动作定位不到
    nm = m.group(1).strip().strip('"').strip("'") if m else sk.parent.name
    d = re.search(r"^description:\s*(.+)$", head, re.M)
    local = str(sk.parent).startswith(str(AGENT / "skills"))
    node(
        nm,
        "skill",
        description=(d.group(1).strip()[:160] if d else ""),
        path=str(sk.parent),
        source="local" if local else "package",
        writable=local,
    )


# ---------- 5. MCP 服务器 ----------
for cfg in (AGENT / "mcp.json", AGENT / "fabric.json", AGENT / "telegram.json"):
    if not cfg.exists():
        continue
    try:
        j = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    servers = j.get("mcpServers") or j.get("mcp") or {}
    if not servers:
        continue
    node(cfg.name, "config")
    for s in servers:
        # 运行期注册表已经把它建成 mcp/provider，这里只补边不覆盖
        node(s, "mcp", file=str(cfg), configKey=s)
        nodes[s]["kind"] = "mcp"
        edge(cfg.name, s, "configures")


# ---------- 6. settings.json 声明的包 ----------
try:
    st = json.loads((AGENT / "settings.json").read_text(encoding="utf-8"))
    node("settings.json", "config")
    for p in st.get("packages") or []:
        if isinstance(p, dict):  # 过滤式对象形式 {source, extensions:[…]}
            p = p.get("source") or ""
        if not p:
            continue
        c = canon(p)
        node(c, "package")
        nodes[c]["kind"] = "package"
        edge("settings.json", c, "declares")
        d, ref = split_spec(p)
        n = nodes[c]
        n["spec"] = p  # 动作层唯一依据：原样回填 pi update/remove/install
        n["pinned"] = bool(ref)
        n["installed"] = d.exists()
        if ref:
            n["ref"] = ref
        if n["installed"]:
            n["path"] = str(d)
            if not n.get("repo"):
                n["repo"] = repo_url(p)
            pj = d / "package.json"
            if pj.exists():
                try:
                    n.setdefault(
                        "version",
                        json.loads(pj.read_text(encoding="utf-8")).get("version"),
                    )
                except (OSError, ValueError):
                    pass
except (OSError, ValueError):
    pass


# ---------- 7. npm 包名（供「检查更新」查 registry） ----------
for _n in nodes.values():
    if _n["kind"] == "package" and (_n.get("spec") or "").startswith("npm:"):
        _s = _n["spec"][4:]
        _m = re.search(r"@([^/@]+)$", _s)
        _n["npmName"] = _s[: _m.start()] if _m else _s


# ---------- 8. 健康信号 ----------
# 全部本地可查、零网络：装丢了 / 依赖残缺 / 重复声明 / 孤立 skill / 声明了但没加载的 mcp
for _n in nodes.values():
    if _n["kind"] != "package":
        continue
    if _n.get("spec") and not _n.get("installed"):
        _n["health"] = "missing"  # settings 声明了，目录却不在
        continue
    _p = Path(_n["path"]) if _n.get("path") else None
    if not _p or not _p.exists():
        continue
    if (_p / "package.json").exists():
        try:
            _j = json.loads((_p / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        _broken = [d for d in (_j.get("dependencies") or {}) if not (NPM / d).exists()]
        if _broken:
            _n["health"] = "broken-deps"
            _n["healthDetail"] = "缺依赖: " + ", ".join(_broken[:4])

_specs = Counter(n["spec"] for n in nodes.values() if n.get("spec"))
for _n in nodes.values():
    if _n.get("spec") and _specs[_n["spec"]] > 1:
        _n["health"] = "duplicate"
        _n["healthDetail"] = f"settings 里重复声明 {_specs[_n['spec']]} 次"


for _n in nodes.values():
    if _n["kind"] == "mcp" and not any(
        b == _n["id"] and k == "provides" for a, b, k in edges
    ):
        _n.setdefault("health", "inactive")  # 配置文件里声明，本次运行没加载
        _n.setdefault("healthDetail", "已声明但运行期未加载")


# ---------- 9. 使用热度（会话转录） ----------
# 全量扫 ~130MB 会话约 0.6s，暂不做增量缓存；
# ponytail: 涨到 GB 级再加 mtime 缓存，否则得不偿失
usage: Counter = Counter()
_CALL = re.compile(r'"type":"tool(?:Call|_use)","id":"[^"]*","name":"([^"]+)"')
_REF = re.compile(r'"ref":"(pi\.[a-z_]+)"')
_SKILL = re.compile(r"skills/([a-z0-9-]+)/SKILL\.md")
for _f in (AGENT / "sessions").rglob("*.jsonl"):
    try:
        _t = _f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue
    usage.update(_CALL.findall(_t))  # 直接调的 pi 内建工具
    usage.update(_REF.findall(_t))  # fabric_exec 里 pi.xxx 的引用
    usage.update(_SKILL.findall(_t))  # skill 被读到的次数

# 同一个工具的两种记法（直接调 "bash" / fabric 里 "pi.bash"）累加，
# 顺序无关，避免谁先谁后覆盖谁
for _tid, _cnt in usage.items():
    _tgt = _tid if _tid in nodes else (f"pi.{_tid}" if f"pi.{_tid}" in nodes else None)
    if _tgt:
        nodes[_tgt]["usage"] = nodes[_tgt].get("usage", 0) + _cnt


# ---------- 10. 卸载残留 ----------
# 卸载不会删目录：settings 里没了 → 没有 spec → 界面上连动作都点不到，
# 于是用户看到的是「卸载完了东西还在，还没动静」。单独标出来，给「移到废纸篓」用。
_INFRA = {
    "npm",
    "git",
    "sessions",
    "skills",
    "prompts",
    "bin",
    "memory",
    "projects-memory",
    "genapps",
    "fabric",
    "extensions",
    "extensions-disabled",
    "tmp",
}
_declared = {n["id"] for n in nodes.values() if n.get("spec")}

# 被已声明包依赖的东西不算残留（比如 pi-tui-kit 是别人拉进来的）
_dep_names: set = set()
for _n in nodes.values():
    if not (_n.get("spec") and _n.get("path")):
        continue
    _pj = Path(_n["path"]) / "package.json"
    if not _pj.exists():
        continue
    try:
        _j = json.loads(_pj.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    for _key in ("dependencies", "peerDependencies"):
        _dep_names.update((_j.get(_key) or {}).keys())


def _dir_size_mb(p: Path) -> float:
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            continue
    return round(total / 1048576, 1)


_leftovers = (
    [
        d
        for d in sorted(NPM.iterdir())
        if d.is_dir()
        and d.name.startswith("pi-")
        and d.name not in _declared
        and d.name not in _dep_names
    ]
    if NPM.exists()
    else []
)
_leftovers += [
    d
    for d in sorted(AGENT.iterdir())
    if d.is_dir()
    and d.name.startswith("pi-")
    and d.name not in _INFRA
    and d.name not in _declared
]

for _d in _leftovers:
    _n = nodes.get(_d.name) or node(_d.name, "package")
    if _n.get("spec"):
        continue  # 还在 settings 里的不算残留
    _n["kind"] = "package"
    _n["path"] = str(_d)
    _n["health"] = "leftover"
    _n["sizeMB"] = _dir_size_mb(_d)
    _n["healthDetail"] = f"卸载残留 · {_n['sizeMB']} MB · 已不在 settings 里"


# ---------- 输出 ----------
# 顺手保证 token 文件存在：装了常驻后端后，页面里内联的就是它
stable_token()
for a, b, _ in edges:
    if a not in nodes:
        node(a, "unknown")
    if b not in nodes:
        node(b, "unknown")

OUT.write_text(
    json.dumps(
        {
            "nodes": list(nodes.values()),
            "edges": [{"from": a, "to": b, "kind": k} for a, b, k in sorted(edges)],
            # 会话里统计到的工具/skill 调用次数（页面的「使用热度」）
            "meta": {"tools": dict(usage.most_common(400))},
        },
        ensure_ascii=False,
        indent=1,
    ),
    encoding="utf-8",
)

kinds = Counter(n["kind"] for n in nodes.values())
ek = Counter(k for _, _, k in edges)
print(f"节点 {len(nodes)}   关系 {len(edges)}   输出 {OUT}")
print("  节点  " + "  ".join(f"{k} {v}" for k, v in kinds.most_common()))
print("  关系  " + "  ".join(f"{k} {v}" for k, v in ek.most_common()))
if providers:
    print(
        "  运行期 provider  "
        + "  ".join(f"{k} {v}" for k, v in providers.most_common())
    )
