#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="${AFH03_DIR:-$(cd "$HERE/.." && pwd)}"
CFG="${AFH03_CONFIG:-config/example_config.json}"
UNIT=afh03-vision

if [ -n "${AFH03_USER:-}" ]; then
    USER_NAME="$AFH03_USER"
else
    USER_NAME="$(logname 2>/dev/null || echo "${SUDO_USER:-}")"
    [ -z "$USER_NAME" ] && USER_NAME="$(awk -F: '$3>=1000 && $3<65534 {print $1; exit}' /etc/passwd)"
    [ -z "$USER_NAME" ] && USER_NAME="rock"
fi

usage() { sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; }

render() {
    sed -e "s|@USER@|$USER_NAME|g" -e "s|@DIR@|$DIR|g" \
        -e "s|@CONFIG@|$CFG|g" "$1" > "$2"
}

case "${1:-}" in
system)
    [ -f "$DIR/soc_vision/main_runtime.py" ] || { echo "[ERR] 找不到 $DIR/soc_vision/main_runtime.py"; exit 1; }
    [ -f "$DIR/$CFG" ] || { echo "[ERR] 找不到配置文件 $DIR/$CFG"; exit 1; }
    echo "安装 systemd 服务: unit=$UNIT user=$USER_NAME dir=$DIR"
    render "$HERE/$UNIT.service" "/etc/systemd/system/$UNIT.service"
    chmod 644 "/etc/systemd/system/$UNIT.service"
    systemctl daemon-reload
    systemctl enable "$UNIT"
    systemctl restart "$UNIT"
    sleep 2
    systemctl --no-pager --full status "$UNIT" | head -20
    echo
    echo "看日志: journalctl -u $UNIT -f"
    echo "停服务: systemctl stop $UNIT    禁用: systemctl disable $UNIT"
    ;;

autostart)
    HOMEDIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"
    [ -z "$HOMEDIR" ] && HOMEDIR="$HOME"
    AD="$HOMEDIR/.config/autostart"
    mkdir -p "$AD"
    render "$HERE/$UNIT.desktop" "$AD/$UNIT.desktop"
    chown -R "$USER_NAME":"$USER_NAME" "$HOMEDIR/.config" 2>/dev/null || true
    chmod 644 "$AD/$UNIT.desktop"
    echo "已安装会话自启: $AD/$UNIT.desktop  (user=$USER_NAME, dir=$DIR)"
    echo "下次登录 XFCE 桌面会自动启动。现在想立刻跑一次："
    echo "  cd $DIR && DISPLAY=:0 python3 -m soc_vision.main_runtime --config $CFG"
    ;;

status)
    echo "== systemd 单元 =="
    systemctl --no-pager --full status "$UNIT" 2>&1 | head -25
    echo
    echo "== 最近 30 行日志 =="
    journalctl -u "$UNIT" -n 30 --no-pager 2>&1
    ;;

uninstall)
    systemctl stop "$UNIT" 2>/dev/null || true
    systemctl disable "$UNIT" 2>/dev/null || true
    rm -f "/etc/systemd/system/$UNIT.service"
    systemctl daemon-reload 2>/dev/null || true
    for h in /home/* /root; do rm -f "$h/.config/autostart/$UNIT.desktop" 2>/dev/null || true; done
    echo "已卸载 $UNIT"
    ;;

*)
    usage
    exit 1
    ;;
esac
