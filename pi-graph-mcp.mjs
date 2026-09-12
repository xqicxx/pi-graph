#!/usr/bin/env node
/**
 * pi-graph MCP server —— 把 ~/.pi/agent/pi-graph.json 暴露成 4 个工具。
 *
 * 只做编排：真正的解析交给 ~/.pi/scripts/pi-graph.py，不重复实现一遍查询逻辑。
 * 传输：stdio（pi-mcp-adapter / Claude Desktop 都能直接挂）
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const HOME = homedir();
const SCRIPT = join(HOME, ".pi", "scripts", "pi-graph.py");
const RENDER = join(HOME, ".pi", "scripts", "pi-graph-render.py");
const GRAPH = join(HOME, ".pi", "agent", "pi-graph.json");

// SDK 装在 pi 自己的 node_modules 里，脚本目录解析不到，用绝对 file: URL 导入
const NM = join(HOME, ".pi", "agent", "npm", "node_modules");
const { McpServer } = await import(
  pathToFileURL(
    join(NM, "@modelcontextprotocol", "sdk", "dist", "esm", "server", "mcp.js"),
  ).href
);
const { StdioServerTransport } = await import(
  pathToFileURL(
    join(
      NM,
      "@modelcontextprotocol",
      "sdk",
      "dist",
      "esm",
      "server",
      "stdio.js",
    ),
  ).href
);
const { z } = await import(pathToFileURL(join(NM, "zod", "index.js")).href);

/** 跑 pi-graph.py 的子命令；失败时把 stderr 原样带回，不吞错。 */
function runCli(args) {
  if (!existsSync(SCRIPT)) {
    return { ok: false, text: `找不到 ${SCRIPT}` };
  }
  const r = spawnSync("python3", [SCRIPT, ...args], {
    encoding: "utf-8",
    timeout: 30_000,
  });
  const out = (r.stdout || "").trim();
  const err = (r.stderr || "").trim();
  if (r.error) return { ok: false, text: `执行失败: ${r.error.message}` };
  if (r.status !== 0)
    return { ok: false, text: err || out || `退出码 ${r.status}` };
  return { ok: true, text: out || "(空)" };
}

const asResult = ({ ok, text }) => ({
  content: [{ type: "text", text }],
  isError: !ok,
});

const server = new McpServer({ name: "pi-graph", version: "1.0.0" });

server.registerTool(
  "graph_stats",
  {
    title: "Pi graph statistics",
    description:
      "Overview of the local Pi ecosystem graph: node and edge counts by kind " +
      "(packages, tools, skills, hooks, MCP servers, SDK deps).",
    inputSchema: {},
  },
  async () => asResult(runCli(["stats"])),
);

server.registerTool(
  "graph_find",
  {
    title: "Search the Pi graph",
    description:
      "Search graph nodes by id or description substring. Use this to find which " +
      "extension provides a tool, which packages exist, or where a skill lives.",
    inputSchema: {
      term: z.string().describe('Search term, e.g. "telegram", "memory".'),
    },
  },
  async ({ term }) => asResult(runCli(["find", String(term)])),
);

server.registerTool(
  "graph_show",
  {
    title: "Inspect one graph node",
    description:
      "Full detail for a single node: metadata plus every inbound and outbound " +
      "relationship (depends-on, provides, hooks, declares, configures).",
    inputSchema: {
      node: z.string().describe('Exact node id, e.g. "pi-lens".'),
    },
  },
  async ({ node }) => asResult(runCli(["show", String(node)])),
);

server.registerTool(
  "graph_render",
  {
    title: "Regenerate the graph view",
    description:
      "Re-extract the graph from the local Pi install and rebuild the interactive " +
      "HTML view at ~/.pi/agent/pi-graph.html. Run after installing or removing packages.",
    inputSchema: {},
  },
  async () => {
    const built = runCli([]); // 无参数 = 重新提取
    if (!built.ok) return asResult(built);
    const r = spawnSync("python3", [RENDER], {
      encoding: "utf-8",
      timeout: 30_000,
    });
    const tail = (r.stdout || "").trim().split("\n").slice(-2).join("\n");
    return asResult({ ok: r.status === 0, text: `${built.text}\n${tail}` });
  },
);

server.registerTool(
  "session_list",
  {
    title: "List recent Pi sessions",
    description:
      "Recent Pi sessions with turn count, tool-call count and size. Use to find a " +
      "session id prefix before digging into its turn chain.",
    inputSchema: {
      limit: z
        .number()
        .int()
        .min(1)
        .max(100)
        .optional()
        .describe("How many sessions to list (default 20)."),
    },
  },
  async ({ limit }) => asResult(runCli(["sessions", String(limit ?? 20)])),
);

server.registerTool(
  "session_tree",
  {
    title: "Show a session's turn chain",
    description:
      "One session as a node list: every turn with its wall-clock duration, thinking " +
      "size and the tools it called, plus the number of branch points. This is the " +
      "PiX-style per-node context, read straight from the session JSONL.",
    inputSchema: {
      id: z
        .string()
        .describe(
          "Session id prefix, e.g. the timestamp/uuid stem from session_list.",
        ),
    },
  },
  async ({ id }) => asResult(runCli(["session", String(id)])),
);

server.registerResource(
  "graph-data",
  "pi-graph://data",
  {
    title: "Raw Pi ecosystem graph",
    description: "The full nodes/edges JSON backing every graph_* tool.",
    mimeType: "application/json",
  },
  async (uri) => ({
    contents: [
      {
        uri: uri.href,
        mimeType: "application/json",
        text: existsSync(GRAPH)
          ? await (await import("node:fs/promises")).readFile(GRAPH, "utf-8")
          : '{"error":"graph not built yet"}',
      },
    ],
  }),
);

await server.connect(new StdioServerTransport());
