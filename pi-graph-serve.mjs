#!/usr/bin/env node
/**
 * pi-graph 本地动作服务。
 *
 *   node pi-graph-serve.mjs [--port 8787] [--dry] [--open]
 *
 * 设计要点（安全边界都在这里）：
 *   1. 只绑 127.0.0.1，并带一次性访问 token（浏览器同机跨站请求打不进来）。
 *   2. 前端只能发 {action, id}；argv 由本文件从图谱节点派生，且必须是 ACTIONS 白名单里的**固定** argv。
 *      → 没有任何来自请求体的字符串会进入命令行，spawn 也用 argv 数组而非 shell。
 *   3. 破坏性动作要 confirm:true；执行前自动备份 settings.json。
 *   4. --dry 只回显 argv 不执行（给自检用）。
 */
import { spawn, spawnSync } from "node:child_process";
import {
  copyFileSync,
  createReadStream,
  existsSync,
  readFileSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { createServer } from "node:http";
import { homedir } from "node:os";
import { dirname, join, resolve, sep } from "node:path";

const HOME = homedir();
const SCRIPTS = join(HOME, ".pi", "scripts");
const AGENT = join(HOME, ".pi", "agent");
const GRAPH = join(AGENT, "pi-graph.json");
const HTML = join(AGENT, "pi-graph.html");

const argv = process.argv.slice(2);
const flag = (name, def) => {
  const i = argv.indexOf(name);
  return i === -1 ? def : argv[i + 1];
};
const PORT = Number(flag("--port", 8787));
const DRY = argv.includes("--dry");
const OPEN = argv.includes("--open");
// 网页终端 = 在本机执行任意命令。它和 /api/action 的白名单是两回事：
// action 永远不会执行请求体里的字符串，shell 就是干这个的。
// 默认关：这是个能跑任意命令的端点，公开分享的项目不该默认开。
// 要网页终端就显式加 --shell。右键动作不受影响（那是白名单 argv + 二次确认）。
const SHELL = argv.includes("--shell");
const SHELL_BIN = process.env.SHELL || "/bin/zsh";
const SHELL_MAX = 4000;
// PATH 里必须自己补上 pi / node 的位置。
// launchd 拉起来的服务只有 PATH=/usr/bin:/bin:/usr/sbin:/sbin，
// 于是 spawn("pi") 直接 ENOENT —— 网页终端和右键动作都会“点了没反应”。
// 所有子进程共用这一份环境（shell、白名单动作、MCP 自检、重扫）。
const EXEC_PATH = [
  dirname(process.execPath), // node 自己的目录
  join(HOME, ".local/share/node/bin"), // pi 的安装位置
  join(HOME, ".pi/agent/bin"),
  "/opt/homebrew/bin",
  "/usr/local/bin",
]
  .filter((d) => {
    try {
      return existsSync(d);
    } catch {
      return false;
    }
  })
  .join(":");
const EXEC_ENV = {
  ...process.env,
  PATH: EXEC_PATH + ":" + (process.env.PATH || ""),
};

/** 找出某个命令在 EXEC_ENV 下会解析到哪个可执行文件（找不到返回 null） */
function which(cmd) {
  for (const dir of (EXEC_ENV.PATH || "").split(":")) {
    if (!dir) continue;
    const p = join(dir, cmd);
    try {
      if (existsSync(p)) return p;
    } catch {
      /* 目录不可读就跳过 */
    }
  }
  return null;
}
/** 跑一次 pi-graph.py 拿 stdout。会话 JSON 随会话增长（几十 MB），超时给宽一点。 */
function runPy(args, timeout = 40000) {
  const r = spawnSync("python3", [join(SCRIPTS, "pi-graph.py"), ...args], {
    encoding: "utf-8",
    timeout,
    env: EXEC_ENV,
    maxBuffer: 64 * 1024 * 1024,
  });
  if (r.error) return { ok: false, error: r.error.message };
  if (r.status !== 0)
    return {
      ok: false,
      error: (r.stderr || "").trim() || `退出码 ${r.status}`,
    };
  return { ok: true, text: (r.stdout || "").trim() };
}

/** 直接吐一段已经算好的 JSON（不解析再序列化，省一次往返） */
function jsonText(res, code, text) {
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    ...CORS,
  });
  res.end(text);
}

// 固定 token：页面里内联同一份，双击 HTML 也能直接操作（见 pi-graph.py 的 stable_token）
const TOKEN_FILE = join(AGENT, "pi-graph.token");
let TOKEN = "";
try {
  TOKEN = readFileSync(TOKEN_FILE, "utf8").trim();
} catch {
  TOKEN = "";
}
if (!TOKEN) {
  TOKEN = Math.random().toString(36).slice(2, 10);
  console.log(
    "⚠️  没有 " +
      TOKEN_FILE +
      "，本次用临时 token（先跑一次 pi-graph.py 生成固定的）",
  );
}

const py = (script) => ["python3", join(SCRIPTS, script)];
const piCmd = (args) => ["pi", ...args];

// action → (节点 → argv|null)。null = 该节点不适用，返回 400。
const ACTIONS = {
  update: (n) =>
    n.kind === "package" && n.spec && !n.pinned
      ? piCmd(["update", n.spec])
      : null,
  reinstall: (n) =>
    n.kind === "package" && n.spec ? piCmd(["install", n.spec]) : null,
  uninstall: (n) =>
    n.kind === "package" && n.spec ? piCmd(["remove", n.spec]) : null,
  // 删除只对本机 skills 目录生效（包内 skill 是包的一部分，只读）
  rmSkill: (n) => {
    if (n.kind !== "skill" || n.source !== "local" || !n.writable || !n.path)
      return null;
    // 只允许删本机 skills 目录里的东西（对比 rmLeftover 的同类检查）
    if (!within(join(AGENT, "skills"), n.path)) return null;
    return ["rm", "-rf", resolve(n.path)];
  },
  // 卸载残留：不清就永远躺在那儿，界面又点不到（没有 spec 就没动作）
  // 移到废纸篓而不是 rm，误删还能捞回来
  rmLeftover: (n) => {
    if (n.health !== "leftover" || !n.path || !n.path.startsWith(AGENT + "/"))
      return null;
    // 目录已经不在就直接说清楚：图谱是快照，用户可能对着同一条重复点
    if (!existsSync(n.path)) return null;
    return [
      "mv",
      n.path,
      join(HOME, ".Trash", n.path.split("/").pop() + "-" + Date.now()),
    ];
  },
  // 只 mv 目录是不够的：npm 工作区清单里还列着的话，
  // 下次 pi update / pi install 触发的 npm install 会把它装回来（真实踩到过）
  forget: (n) =>
    n.health === "leftover" && n.path && n.path.includes("/npm/node_modules/")
      ? [
          "python3",
          join(SCRIPTS, "pi-graph.py"),
          "forget",
          n.path.split("/").pop(),
        ]
      : null,
};
const DESTRUCTIVE = new Set([
  "reinstall",
  "uninstall",
  "rmSkill",
  "rmLeftover",
]);
// 能批量跑的动作白名单（拒绝任何其它字符串）
const BULK_ACTIONS = new Set(["update", "reinstall", "uninstall"]);

// 批量：逐个 derive argv，逐条报错，不执行任何东西
function bulkPlan(ids, action) {
  if (!Array.isArray(ids) || !ids.length || ids.length > 60)
    return { error: "ids 需要 1–60 个节点 id" };
  if (!BULK_ACTIONS.has(action)) return { error: "批量不支持动作 " + action };
  const g = graph();
  const plans = ids.map((id) => {
    const n = g.nodes.find((x) => x.id === id);
    if (!n) return { id, error: "没有节点 " + id };
    const p = preview({ action, id }, action);
    return p.error ? { id, error: p.error } : { id, steps: p.steps };
  });
  const ok = plans.filter((p) => !p.error);
  return {
    action,
    plans,
    ok: ok.length,
    bad: plans.length - ok.length,
    steps: ok.flatMap((p) => p.steps),
  };
}

// file:// 打开的页面要能跨源调 127.0.0.1，所以放行 CORS；
// 真正的门禁是 x-token（只有本机用户读得到那个文件），bind 也只监听回环
const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "content-type,x-token",
  "access-control-allow-methods": "GET,POST,OPTIONS",
  "access-control-max-age": "600",
};
const json = (res, code, body) => {
  res.writeHead(code, {
    "content-type": "application/json; charset=utf-8",
    ...CORS,
  });
  res.end(JSON.stringify(body));
};

function graph() {
  try {
    return JSON.parse(readFileSync(GRAPH, "utf8"));
  } catch (e) {
    throw new Error(`图谱读取失败 ${GRAPH}: ${e.message}`);
  }
}
function nodeOf(id) {
  try {
    return graph().nodes.find((n) => n.id === id);
  } catch {
    return null;
  }
}

// 请求体上限：本地服务也不该被一个超长 body 撑爆内存
const BODY_MAX = 1_000_000;
function body(req) {
  return new Promise((resolveBody, reject) => {
    let s = "";
    req.on("data", (c) => {
      s += c;
      if (s.length > BODY_MAX) {
        reject(new Error("请求体过大"));
        req.destroy();
      }
    });
    req.on("end", () => resolveBody(s));
    req.on("error", reject);
  });
}

/** 路径必须落在某个目录里（真包含，不是字符串前缀）。 */
function within(dir, p) {
  const r = resolve(p);
  return r === resolve(dir) || r.startsWith(resolve(dir) + sep);
}

async function handle(req, res) {
  const url = new URL(req.url, "http://127.0.0.1");
  const route = url.pathname;
  const tok = url.searchParams.get("token") ?? req.headers["x-token"];

  if (req.method === "OPTIONS") {
    res.writeHead(204, CORS);
    return res.end();
  }
  // 探活：即使 token 不对也回 200，让页面自己判断该不该用后端
  if (route === "/api/events") {
    if (!LIVE) return json(res, 403, { error: "实时同步已关闭（--no-live）" });
    res.writeHead(200, {
      "content-type": "text/event-stream; charset=utf-8",
      "cache-control": "no-cache, no-transform",
      connection: "keep-alive",
      "x-accel-buffering": "no",
      ...CORS,
    });
    res.write(": connected\n\n");
    sseClients.add(res);
    // 心跳：中间层/浏览器会在空闲时掐断长连接
    const beat = setInterval(() => {
      try {
        res.write(": ping\n\n");
      } catch {
        clearInterval(beat);
        sseClients.delete(res);
      }
    }, 25000);
    req.on("close", () => {
      clearInterval(beat);
      sseClients.delete(res);
    });
    return;
  }

  if (route === "/api/ping") {
    // htmlMtime：file:// 打开的标签页不会自动刷新，页面靠它发现自己是个旧副本
    let htmlMtime = 0;
    try {
      htmlMtime = statSync(HTML).mtimeMs;
    } catch {
      htmlMtime = 0;
    }
    return json(res, 200, {
      ok: true,
      tokenOk: tok === TOKEN,
      dry: DRY,
      port: PORT,
      shell: SHELL,
      graph: GRAPH,
      htmlMtime,
    });
  }

  if (route === "/" || route === "/index.html") {
    if (tok !== TOKEN) return json(res, 403, { error: "bad token" });
    res.writeHead(200, { "content-type": "text/html; charset=utf-8", ...CORS });
    return createReadStream(HTML).pipe(res);
  }
  if (route === "/graph.json") {
    if (tok !== TOKEN) return json(res, 403, { error: "bad token" });
    res.writeHead(200, {
      "content-type": "application/json; charset=utf-8",
      ...CORS,
    });
    return createReadStream(GRAPH).pipe(res);
  }
  if (tok !== TOKEN) return json(res, 403, { error: "bad token" });

  let q;
  try {
    q = JSON.parse((await body(req)) || "{}");
  } catch {
    return json(res, 400, { error: "请求体不是合法 JSON" });
  }
  // null / 数组 / 标量都不是我们要的对象；不挡的话后面 q.ids 会抛 TypeError
  if (q === null || typeof q !== "object" || Array.isArray(q))
    return json(res, 400, { error: "请求体需要是 JSON 对象" });

  if (route === "/api/preview") {
    // 批量预览：只算 argv，一个都不执行
    if (Array.isArray(q.ids)) return json(res, 200, bulkPlan(q.ids, q.action));
    return json(res, 200, preview(q, q.action));
  }

  if (route === "/api/action") {
    const { action, confirm } = q;
    if (!confirm && DESTRUCTIVE.has(action))
      return json(res, 400, { error: "破坏性动作需要 confirm:true" });
    const p = preview(q, action);
    if (p.error) return json(res, 400, p);
    if (DRY) return json(res, 200, { ...p, dry: true });
    // 执行前备份（回滚用）
    if (["reinstall", "uninstall"].includes(action))
      p.backup = backupSettings();
    return run(p, res);
  }

  if (route === "/api/bulk") {
    const { action, ids, confirm } = q;
    if (!BULK_ACTIONS.has(action))
      return json(res, 400, { error: "批量不支持动作 " + action });
    const plan = bulkPlan(ids, action);
    if (plan.error) return json(res, 400, plan);
    // 批量一定先看清单再执行：没有 confirm 就只回 plan
    if (!confirm) return json(res, 200, { ...plan, needsConfirm: true });
    if (DRY) return json(res, 200, { ...plan, dry: true });
    const steps = plan.plans.filter((p) => !p.error).flatMap((p) => p.steps);
    if (!steps.length) return json(res, 400, { error: "没有一个节点可执行" });
    // 顺序执行（不并发），npm/git 同时跑会互相踩
    return run(
      {
        steps,
        cwd: HOME,
        backup: ["uninstall"].includes(action) ? backupSettings() : null,
      },
      res,
      () => res.end("\n\nDONE 批量 " + action + " " + steps.length + " 步\n"),
    );
  }

  if (route === "/api/refresh") {
    if (DRY)
      return json(res, 200, {
        dry: true,
        steps: [py("pi-graph.py"), py("pi-graph-render.py")],
      });
    return run(
      { steps: [py("pi-graph.py"), py("pi-graph-render.py")], cwd: SCRIPTS },
      res,
      () => {
        res.end(`\n\nDONE ${graph().nodes.length} 节点`);
      },
    );
  }

  if (route === "/api/rollback") {
    const { backup } = q;
    if (!/^\/.*settings\.json\.bak-ui-[\w.-]+$/.test(backup || ""))
      return json(res, 400, {
        error: "只接受 settings.json.bak-ui-* 备份路径",
      });
    if (!existsSync(backup)) return json(res, 404, { error: "备份不存在" });
    if (DRY)
      return json(res, 200, {
        dry: true,
        steps: [["cp", backup, join(AGENT, "settings.json")]],
      });
    copyFileSync(backup, join(AGENT, "settings.json"));
    refreshSoon();
    return json(res, 200, { ok: true, restored: backup });
  }

  if (route === "/api/file") {
    const node = nodeOf(q.id) || {};
    let p = q.path || node.file || join(node.path || "", "SKILL.md");
    if (node.kind === "skill") p = join(node.path || "", "SKILL.md");
    // 真包含判断：startsWith(AGENT) 会被 …/agent/../../.zshrc 这种前缀骗过去
    if (!p || !within(AGENT, p) || !existsSync(p))
      return json(res, 404, { error: "读不到 " + p });
    p = resolve(p);
    const st = statSync(p);
    if (st.isDirectory()) return json(res, 400, { error: "是目录" });
    const txt = readFileSync(p, "utf8");
    return json(res, 200, {
      path: p,
      text: txt.length > 60000 ? txt.slice(0, 60000) + "\n…(截断)" : txt,
    });
  }

  // 会话视图是动态的：面板每次打开都来这里取，不塞进内嵌的静态图谱
  if (route === "/api/sessions") {
    const limit = url.searchParams.get("limit") || "40";
    if (!/^\d{1,3}$/.test(limit))
      return json(res, 400, { error: "limit 需要是 1–3 位数字" });
    const r = runPy(["sessions", limit, "--json"]);
    if (!r.ok) return json(res, 500, { error: r.error });
    return jsonText(res, 200, r.text);
  }

  if (route === "/api/session") {
    // id 只允许会话文件名里会出现的字符，且不能以 - 开头（否则会变成参数）
    const id = url.searchParams.get("id") || "";
    if (!/^[A-Za-z0-9._][A-Za-z0-9._-]{3,79}$/.test(id))
      return json(res, 400, { error: "id 不合法" });
    const r = runPy(["session", id, "--json"]);
    if (!r.ok) return json(res, 404, { error: r.error });
    return jsonText(res, 200, r.text);
  }

  if (route === "/api/updates") {
    if (DRY) return json(res, 200, { dry: true, pkgs: {} });
    try {
      return json(
        res,
        200,
        await checkUpdates(url.searchParams.get("force") === "1"),
      );
    } catch (e) {
      return json(res, 500, { error: String(e.message) });
    }
  }

  if (route === "/api/shell") {
    if (!SHELL)
      return json(res, 403, {
        error: "网页终端未开启（起服务时加 --shell）",
      });
    if (DRY)
      return json(res, 200, {
        dry: true,
        steps: [[SHELL_BIN, "-lc", q.cmd || ""]],
      });
    return runShell(String(q.cmd || ""), res);
  }

  if (route === "/api/mcptest") {
    if (DRY) return json(res, 200, { dry: true, steps: [["spawn", "…"]] });
    return mcpTest(q.id || url.searchParams.get("id"), res);
  }

  return json(res, 404, { error: "no such route" });
}

// 单个坏请求不该带走整个服务：任何未捕获的异常都变成 500
const server = createServer((req, res) => {
  handle(req, res).catch((e) => {
    try {
      json(res, 500, { error: String((e && e.message) || e) });
    } catch {
      /* 响应已经开始写了，只能作罢 */
    }
  });
});

// ---------- P4：更新检查（npm registry，6 小时文件缓存）----------
const UPDATES = join(AGENT, "pi-graph-updates.json");
const UPDATE_TTL = 6 * 3600 * 1000;

async function checkUpdates(force) {
  let cached = null;
  try {
    cached = JSON.parse(readFileSync(UPDATES, "utf8"));
  } catch {
    cached = null;
  }
  if (!force && cached && Date.now() - (cached.at || 0) < UPDATE_TTL)
    return cached;

  const pkgs = graph().nodes.filter(
    (n) => n.kind === "package" && n.npmName && !n.pinned,
  );
  const out = { at: Date.now(), pkgs: {} };
  await Promise.all(
    pkgs.map(async (n) => {
      const url = `https://registry.npmjs.org/${n.npmName.replace("/", "%2F")}/latest`;
      try {
        const r = await fetch(url, { signal: AbortSignal.timeout(8000) });
        const j = await r.json();
        out.pkgs[n.id] = {
          current: n.version || null,
          latest: j.version || null,
          outdated: !!n.version && !!j.version && j.version !== n.version,
          repo: n.repo || null,
        };
      } catch (e) {
        out.pkgs[n.id] = { error: String(e.message || e).slice(0, 90) };
      }
      return out.pkgs[n.id];
    }),
  );
  try {
    writeFileSync(UPDATES, JSON.stringify(out));
  } catch {
    /* 缓存写不进去不影响结果 */
  }
  return out;
}

// ---------- P4：MCP 连接自检（真起进程走一遍 initialize + tools/list）----------
function mcpServers() {
  try {
    return (
      JSON.parse(readFileSync(join(AGENT, "mcp.json"), "utf8")).mcpServers || {}
    );
  } catch {
    return {};
  }
}

function mcpTest(name, res) {
  const cfg = mcpServers()[name];
  if (!cfg) return json(res, 400, { error: `mcp.json 里没有 ${name}` });
  res.writeHead(200, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
    ...CORS,
  });
  res.write(`$ ${[cfg.command, ...(cfg.args || [])].join(" ")}\n`);
  const p = spawn(cfg.command, cfg.args || [], {
    cwd: HOME,
    env: { ...EXEC_ENV, ...(cfg.env || {}) },
  });
  let buf = "";
  let done = false;
  const finish = (msg) => {
    if (done) return;
    done = true;
    clearTimeout(timer);
    p.kill("SIGKILL");
    res.write(msg);
    res.end();
  };
  const timer = setTimeout(
    () => finish(`\n[超时] ${name} 25s 没回应（npx 首次拉包可能就是这么慢）\n`),
    25000,
  );
  const send = (o) => p.stdin.write(JSON.stringify(o) + "\n");
  p.stdout.on("data", (d) => {
    buf += d;
    let i;
    while ((i = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, i).trim();
      buf = buf.slice(i + 1);
      if (!line) continue;
      let msg;
      try {
        msg = JSON.parse(line);
      } catch {
        continue;
      }
      if (msg.id === 1) {
        const si = msg.result?.serverInfo || {};
        res.write(`initialize ok · ${si.name || "?"} ${si.version || ""}\n`);
        send({ jsonrpc: "2.0", method: "notifications/initialized" });
        send({ jsonrpc: "2.0", id: 2, method: "tools/list" });
      } else if (msg.id === 2) {
        const names = (msg.result?.tools || []).map((t) => t.name);
        finish(
          `tools/list ok · ${names.length} 个工具\n` +
            names.slice(0, 40).join(", ") +
            (names.length > 40 ? " …" : "") +
            "\n",
        );
      }
    }
  });
  p.stderr.on("data", (d) => res.write(String(d)));
  p.on("error", (e) => finish(`\n!! ${e.message}\n`));
  send({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "pi-graph", version: "1" },
    },
  });
}

function preview({ action, id, path }, act) {
  const n = nodeOf(id);
  if (!n) return { error: "没有节点 " + id };
  // 清理残留 = 先摘掉 npm 清单条目，再挪目录。顺序不能反：
  // 先挪目录的话中途失败会留下「目录没了但清单还在」，下次 install 又装回来。
  if (act === "rmLeftover") {
    const steps = [];
    const f = ACTIONS.forget(n);
    if (f) steps.push(f);
    const mv = ACTIONS.rmLeftover(n);
    if (!mv) {
      return existsSync(n.path)
        ? { error: "路径不在 ~/.pi/agent 下，已拒绝" }
        : {
            error:
              n.path +
              " 已经不在那儿了（多半已经清理过）—— 点「重新扫描」刷新图谱",
          };
    }
    steps.push(mv);
    return { id, kind: n.kind, spec: n.spec, steps, cwd: HOME };
  }
  let steps = [];
  if (act === "reveal") {
    steps.push(["open", "-R", n.path || n.file || ""]);
  } else if (act === "openPath") {
    steps.push(["open", n.path || n.file || ""]);
  } else if (act === "openRepo") {
    if (!n.repo) return { error: "该节点没有仓库地址" };
    steps.push(["open", n.repo]);
  } else if (act === "config") {
    steps.push(["open", "-a", "Terminal", join(SCRIPTS, "pi-config.sh")]);
  } else if (act === "openFile") {
    if (!path) return { error: "需要 path" };
    steps.push(["open", path]);
  } else {
    const build = ACTIONS[action];
    if (!build) return { error: "未知动作 " + action };
    const cmd = build(n);
    if (!cmd && action === "forget")
      return { error: "不需要（这个残留不在 npm 工作区里）" };
    if (!cmd) {
      if (action === "update" && n.pinned)
        return { error: "ref 已固定，用 pi install " + n.spec + "@新ref" };
      if (
        action === "rmLeftover" &&
        n.health === "leftover" &&
        !existsSync(n.path)
      )
        return {
          error:
            n.path +
            " 已经不在那儿了（多半已经清理过）—— 点「重新扫描」刷新图谱",
        };
      return { error: `动作 ${action} 不适用于 ${n.kind} 节点` };
    }
    steps.push(cmd);
    if (action === "reinstall") {
      steps = [piCmd(["remove", n.spec]), piCmd(["install", n.spec])];
    }
  }
  return { id, kind: n.kind, spec: n.spec, steps, cwd: HOME };
}

// 在 HOME 下跑一条命令，把 stdout/stderr 边跑边推给前端。
// 注意：这里是唯一一处「请求体字符串直接进命令行」的地方，所以它是独立端点、
// 独立开关、独立 UI，绝不复用到 /api/action 上。
function runShell(cmd, res) {
  const text = cmd.trim();
  if (!text) return json(res, 400, { error: "空命令" });
  if (text.length > SHELL_MAX)
    return json(res, 400, { error: "命令太长（上限 " + SHELL_MAX + " 字符）" });

  res.writeHead(200, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
    ...CORS,
  });
  // -l 走登录 shell，PATH 才带得到 homebrew 里的 node/pi
  const p = spawn(SHELL_BIN, ["-lc", text], { cwd: HOME, env: EXEC_ENV });
  let killed = false;
  const kill = () => {
    if (killed) return;
    killed = true;
    try {
      p.kill("SIGTERM");
      setTimeout(() => p.kill("SIGKILL"), 1500).unref?.();
    } catch {
      /* 已经退出了 */
    }
  };
  // 前端关连接（点停止 / 关页面）就把子进程一起收掉，别留孤儿
  res.on("close", kill);

  p.stdout.on("data", (d) => !killed && res.write(d));
  p.stderr.on("data", (d) => !killed && res.write(d));
  p.on("error", (e) => {
    res.write("\n!! 起不来: " + e.message + "\n");
    res.end();
  });
  p.on("close", (code, sig) => {
    if (killed) return res.end("\n[已停止]\n");
    res.write("\n[exit " + code + (sig ? " · " + sig : "") + "]\n");
    res.end();
  });
}

function backupSettings() {
  const p = join(AGENT, "settings.json");
  const bak = `${p}.bak-ui-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19)}`;
  copyFileSync(p, bak);
  return bak;
}

function run({ steps, cwd, backup }, res, done) {
  res.writeHead(200, {
    "content-type": "text/plain; charset=utf-8",
    "cache-control": "no-cache",
    "x-accel-buffering": "no",
    ...CORS,
  });
  let i = 0;
  if (backup) res.write(`# 回滚备份: ${backup}\n`);
  const next = () => {
    if (i >= steps.length) return done ? done() : res.end();
    const cmd = steps[i++];
    res.write(`$ ${cmd.join(" ")}\n`);
    const p = spawn(cmd[0], cmd.slice(1), { cwd: cwd || HOME, env: EXEC_ENV });
    p.stdout.on("data", (d) => res.write(d));
    p.stderr.on("data", (d) => res.write(d));
    p.on("error", (e) => {
      res.write(`\n!! ${e.message}\n`);
      res.end();
    });
    p.on("close", (code) => {
      res.write(`\n[exit ${code}]\n`);
      if (code === 0) next();
      else res.end("\n!! 中止后续步骤\n");
    });
  };
  next();
}

let refreshing = false;

// ---------- 实时同步：文件一变就推给所有打开的页面 ----------
// 用轮询 mtime 而不是 fs.watch：watch 在 macOS 上对 rename-替换式写入会丢事件，
// 而这里只有 2 个文件、1.5s 一次 stat，成本可以忽略。
const LIVE = !argv.includes("--no-live");
const sseClients = new Set();
const mtime = (p) => {
  try {
    return statSync(p).mtimeMs;
  } catch {
    return 0;
  }
};
let seenGraph = mtime(GRAPH);
let seenHtml = mtime(HTML);

function broadcast(event) {
  const msg = `event: ${event}\ndata: {}\n\n`;
  for (const c of sseClients) {
    try {
      c.write(msg);
    } catch {
      sseClients.delete(c);
    }
  }
}

if (LIVE) {
  setInterval(() => {
    if (!sseClients.size) return; // 没人在看就不做无谓的 stat
    const g = mtime(GRAPH);
    const h = mtime(HTML);
    if (g && g !== seenGraph) {
      seenGraph = g;
      broadcast("graph");
    }
    if (h && h !== seenHtml) {
      seenHtml = h;
      broadcast("html");
    }
  }, 1500).unref?.();
}
function refreshSoon() {
  if (refreshing) return;
  refreshing = true;
  const p = spawn("python3", [join(SCRIPTS, "pi-graph.py")], {
    cwd: SCRIPTS,
    env: EXEC_ENV,
  });
  p.on("close", () => {
    spawn("python3", [join(SCRIPTS, "pi-graph-render.py")], {
      cwd: SCRIPTS,
      env: EXEC_ENV,
    }).on("close", () => {
      refreshing = false;
    });
  });
}

if (!existsSync(HTML)) {
  console.error(
    `找不到 ${HTML}，先跑: python3 ${join(SCRIPTS, "pi-graph-render.py")}`,
  );
  process.exit(1);
}

// 启动自检：launchd 拉起来的进程 PATH 很干净，pi 找不到的话
// 所有右键动作都会「点了没反应」，不如启动时就说清楚
if (!which("pi")) {
  console.error(
    `⚠️  PATH 里找不到 pi（当前 PATH=${EXEC_ENV.PATH}）\n` +
      "   右键的更新/重装/卸载都会失败，请把 pi 所在目录加进 EXEC_PATH。",
  );
}

server.listen(PORT, "127.0.0.1", () => {
  const url = `http://127.0.0.1:${PORT}/?token=${TOKEN}`;
  console.log(url);
  console.log(`BACKEND ${JSON.stringify({ dry: DRY, graph: GRAPH })}`);
  if (OPEN && !DRY)
    spawn("open", [url], { detached: true, stdio: "ignore" }).unref();
});

process.on("SIGINT", () => process.exit(0));

export { TOKEN, preview, ACTIONS };
