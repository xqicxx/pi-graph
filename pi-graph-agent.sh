#!/bin/bash
# pi-graph 后端常驻管理（开箱即用的关键：装一次，以后开页面就能直接改）。
#
#   ./pi-graph-agent.sh install    装 launchd 常驻（登录自启 + 崩了自动拉起）
#   ./pi-graph-agent.sh status     看状态 / ping
#   ./pi-graph-agent.sh restart    重启
#   ./pi-graph-agent.sh uninstall  卸载
#   ./pi-graph-agent.sh logs       看日志
set -u
LABEL="com.cx.pi-graph"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
PORT=${PI_GRAPH_PORT:-8787}
NODE=$(command -v node || echo /opt/homebrew/bin/node)
SERVE="$HOME/.pi/scripts/pi-graph-serve.mjs"
OUT="$HOME/.pi/agent/pi-graph-serve.log"
UID_N=$(id -u)

case "${1:-status}" in
  install)
    python3 "$HOME/.pi/scripts/pi-graph.py" token >/dev/null
    mkdir -p "$HOME/Library/LaunchAgents"
    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${LABEL}</string>
  <key>ProgramArguments</key><array>
    <string>${NODE}</string><string>${SERVE}</string><string>--port</string><string>${PORT}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>WorkingDirectory</key><string>${HOME}</string>
  <key>StandardOutPath</key><string>${OUT}</string>
  <key>StandardErrorPath</key><string>${OUT}</string>
  <key>ProcessType</key><string>Background</string>
</dict></plist>
PLIST_EOF
    launchctl bootout "gui/${UID_N}/${LABEL}" 2>/dev/null
    launchctl bootstrap "gui/${UID_N}" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST" 2>/dev/null
    sleep 2
    echo "已安装 ${LABEL} —— 端口 ${PORT}，登录自启 + 崩溃自动拉起"
    exec "$0" status
    ;;
  uninstall)
    launchctl bootout "gui/${UID_N}/${LABEL}" 2>/dev/null || launchctl unload -w "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo "已卸载 ${LABEL}"
    ;;
  restart)
    launchctl kickstart -k "gui/${UID_N}/${LABEL}" 2>/dev/null || { launchctl unload "$PLIST" 2>/dev/null; launchctl load -w "$PLIST" 2>/dev/null; }
    sleep 2
    exec "$0" status
    ;;
  logs) tail -40 "$OUT" ;;
  status)
    if launchctl print "gui/${UID_N}/${LABEL}" >/dev/null 2>&1; then
      echo "launchd: 已加载（KeepAlive）"
    else
      echo "launchd: 未加载 —— 跑一次 ./pi-graph-agent.sh install"
    fi
    TOKEN=$(cat "$HOME/.pi/agent/pi-graph.token" 2>/dev/null || echo '')
    R=$(curl -s -m 4 -H "x-token: ${TOKEN}" "http://127.0.0.1:${PORT}/api/ping" 2>/dev/null || echo '')
    if [ -n "$R" ]; then echo "后端: 在线   $R"; else echo "后端: 离线（端口 ${PORT}）"; fi
    echo "页面: file://${HOME}/.pi/agent/pi-graph.html"
    ;;
  *)
    sed -n '2,10p' "$0"; exit 1;;
esac
