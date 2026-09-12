#!/bin/bash
# pi-graph 动作服务自检。
#   ./pi-graph-serve.selftest.sh          --dry 通路检查（不执行任何命令）
#   ./pi-graph-serve.selftest.sh --drill  真实重装演练（npm，改 settings.json 后自动回滚）
set -u
PORT=${PORT:-8791}
SERVE="$HOME/.pi/scripts/pi-graph-serve.mjs"
DRILL=0
[ "${1:-}" = '--drill' ] && DRILL=1
LOG=$(mktemp)
FAIL=0

ARGS=(--port "$PORT")
[ $DRILL -eq 0 ] && ARGS+=(--dry)
node "$SERVE" "${ARGS[@]}" >"$LOG" 2>&1 &
PID=$!
trap 'kill $PID 2>/dev/null' EXIT

for _ in $(seq 1 40); do
  grep -q 'token=' "$LOG" && break
  sleep 0.25
done
# 固定 token 含大写与 - / _，别只匹配小写
TOKEN=$(sed -n 's/.*token=\([A-Za-z0-9_-]*\).*/\1/p' "$LOG" | head -1)
if [ -z "$TOKEN" ]; then
  echo 'FAIL 服务没起来'
  cat "$LOG"
  exit 1
fi
BASE="http://127.0.0.1:$PORT"

ck() { # ck 名称 期望 实际
  if [ "$2" = "$3" ]; then
    echo "ok   $1"
  else
    echo "FAIL $1  期望[$2] 实际[$3]"
    FAIL=$((FAIL + 1))
  fi
}
post() { curl -s -m 30 -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d "$2" "$BASE$1"; }
send() { curl -s -m 300 -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d "$2" "$BASE$1"; }
package_count() { python3 -c "import json;print(len(json.load(open('$HOME/.pi/agent/settings.json')).get('packages',[])))"; }

# 1 鉴权
ck '无 token 拒绝' '403' "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/graph.json")"
ck '错误 token 拒绝' '403' "$(curl -s -o /dev/null -w '%{http_code}' -H 'x-token: nope' "$BASE/graph.json")"
ck '带 token 拿 HTML' '200' "$(curl -s -o /tmp/pg-html -w '%{http_code}' "$BASE/?token=$TOKEN")"
# 图谱 / 列表 / 流程三种视图都有右键处理，数量只要求「至少 2 处」
ck 'HTML 含右键菜单' 'true' "$([ "$(grep -c contextmenu /tmp/pg-html)" -ge 2 ] && echo true)"

# 2 派生 argv（preview 在任何模式都只算不跑）
ck 'update → pi update' 'pi update npm:pi-lens' "$(post /api/preview '{"action":"update","id":"pi-lens"}' | jq -r '.steps[0]|join(" ")')"
ck 'reinstall → 两步' 'pi install npm:pi-lens' "$(post /api/preview '{"action":"reinstall","id":"pi-lens"}' | jq -r '.steps[1]|join(" ")')"
ck 'openRepo → open url' 'https://github.com/apmantza/pi-lens' "$(post /api/preview '{"action":"openRepo","id":"pi-lens"}' | jq -r '.steps[0][1]')"
ck 'skill 定位到 SKILL.md' 'true' "$(post /api/file '{"id":"pdf"}' | jq -r '.path|endswith("skills/pdf/SKILL.md")')"

# 3 安全边界：非法组合与非法输入必须被拒
ck '工具节点不能 update' '400' "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d '{"action":"update","id":"pi.fabric_exec"}' "$BASE/api/action")"
ck '破坏性动作要 confirm' '400' "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d '{"action":"uninstall","id":"pi-lens"}' "$BASE/api/action")"
ck '未知动作拒绝' '400' "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d '{"action":"rm -rf /","id":"pi-lens"}' "$BASE/api/action")"
ck 'rollback 拒绝任意路径' 'true' "$(post /api/rollback '{"backup":"/etc/passwd"}' | jq -r '.error|length > 0')"
ck 'file 只读 ~/.pi/agent' '404' "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d '{"id":"settings.json","path":"/etc/passwd"}' "$BASE/api/file")"

# 4 dry 通路：回显 argv 而不执行（只有 --dry 才有 JSON 回包）
if [ $DRILL -eq 0 ]; then
  ck 'dry 不执行' 'true' "$(post /api/action '{"action":"uninstall","id":"pi-lens","confirm":true}' | jq -r '.dry')"
  ck 'dry 仍给 argv' 'pi remove npm:pi-lens' "$(post /api/action '{"action":"uninstall","id":"pi-lens","confirm":true}' | jq -r '.steps[0]|join(" ")')"
  ck 'refresh 有步骤' '2' "$(post /api/refresh '{}' | jq -r '.steps|length')"
  ck 'updates 在 dry 下不联网' 'true' "$(post /api/updates '{}' | jq -r '.dry')"
  ck '批量预览算出 3 条 argv' '3' "$(post /api/preview '{"action":"update","ids":["pi-lens","pi-memory","pi-subagents"]}' | jq -r '.ok')"
  ck '批量预览会点名坏 id' '1' "$(post /api/preview '{"action":"update","ids":["pi-lens","pi.bash"]}' | jq -r '.bad')"
  ck '批量动作白名单' '400' "$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "x-token: $TOKEN" -H 'content-type: application/json' -d '{"action":"rm -rf /","ids":["pi-lens"],"confirm":true}' "$BASE/api/bulk")"
  ck '批量缺 confirm 只回清单' 'true' "$(post /api/bulk '{"action":"uninstall","ids":["pi-lens"]}' | jq -r '.needsConfirm')"
  ck '批量 ids 空被拒' 'true' "$(post /api/bulk '{"action":"update","ids":[],"confirm":true}' | jq -r '.error|length>0')"
  ck '批量 dry 不执行' 'true' "$(post /api/bulk '{"action":"update","ids":["pi-lens"],"confirm":true}' | jq -r '.dry')"
  ck 'ping 免 token 可探活' 'true' "$(curl -s -m 5 "$BASE/api/ping" | jq -r '.ok')"
  ck 'ping 带对 token 则 tokenOk' 'true' "$(curl -s -m 5 -H "x-token: $TOKEN" "$BASE/api/ping" | jq -r '.tokenOk')"
  ck 'mcptest 在 dry 下不执行' 'true' "$(post /api/mcptest '{"id":"context7"}' | jq -r '.dry')"
fi

# 4.5 launchd 场景：PATH 被精简后 pi 还能不能用
# 真实事故：launchd 只给 /usr/bin:/bin:/usr/sbin:/sbin，spawn("pi") 直接 ENOENT，
# 右键的更新/重装全部「点了没反应」。直接跑服务会继承完整 PATH，测不出这个。
if [ $DRILL -eq 0 ]; then
  LP=$(mktemp -d)
  # 注意：node 自己也不在系统 PATH 里，所以要用绝对路径启动，
  # 这样才真的复现「服务起来了，但 PATH 里没有 pi」的 launchd 场景
  NODE_BIN=$(command -v node)
  env PATH=/usr/bin:/bin:/usr/sbin:/sbin "$NODE_BIN" "$SERVE" --port $((PORT + 7)) --dry >"$LP/l" 2>&1 &
  LPID=$!
  for _ in $(seq 1 40); do grep -q 'token=' "$LP/l" && break; sleep 0.25; done
  LT=$(sed -n 's/.*token=\([A-Za-z0-9_-]*\).*/\1/p' "$LP/l" | head -1)
  LB="http://127.0.0.1:$((PORT + 7))"
  ck '精简 PATH 下服务仍启动' 'true' "$([ -n "$LT" ] && echo true || echo false)"
  ck '精简 PATH 下 pi 仍可解析' 'pi update npm:pi-lens' \
    "$(curl -s -m 20 -X POST -H "x-token: $LT" -H 'content-type: application/json' -d '{"action":"update","id":"pi-lens"}' "$LB/api/preview" | jq -r '.steps[0]|join(" ")')"
  ck '精简 PATH 下无 ENOENT' '0' "$(grep -c ENOENT "$LP/l" 2>/dev/null | head -1 || echo 0)"
  kill $LPID 2>/dev/null
  wait $LPID 2>/dev/null   # 收掉 job 通知，不然会打一行 "Terminated: 15"
  rm -rf "$LP"
fi

# 5 真实重装演练
if [ $DRILL -eq 1 ]; then
  PKG='npm:pi-markdown-preview'
  NAME='pi-markdown-preview'
  DIR="$HOME/.pi/agent/npm/node_modules/$NAME"
  BEF=$(pi list 2>/dev/null | grep -c "$NAME")
  N0=$(package_count)
  OUT=$(send /api/action '{"action":"reinstall","id":"pi-markdown-preview","confirm":true}')
  BAK=$(ls -t "$HOME/.pi/agent"/settings.json.bak-ui-* 2>/dev/null | head -1)
  ck '重装：settings 未重复' '1' "$(grep -c "$PKG" "$HOME/.pi/agent/settings.json")"
  ck '重装：两步都 exit 0' '2' "$(echo "$OUT" | grep -c 'exit 0')"
  ck '重装：无 npm error' '0' "$(echo "$OUT" | grep -ci 'npm error\|ERR!')"
  ck '重装：包目录还在' 'true' "$([ -d "$DIR" ] && echo true || echo false)"
  ck '重装：pi list 不受影响' "$BEF" "$(pi list 2>/dev/null | grep -c "$NAME")"
  ck '重装：settings 包数不变' "$N0" "$(package_count)"
  if [ -n "${BAK:-}" ]; then
    ck '回滚备份可用' 'true' "$(post /api/rollback "{\"backup\":\"$BAK\"}" | jq -r '.ok')"
    ck '回滚后设置仍合法' "$N0" "$(package_count)"
  else
    echo 'FAIL 没生成 .bak-ui-* 备份'
    FAIL=$((FAIL + 1))
  fi
fi

echo "---- 失败 $FAIL 项"
exit $((FAIL > 0))
