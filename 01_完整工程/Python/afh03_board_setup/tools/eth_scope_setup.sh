#!/usr/bin/env bash
set -uo pipefail

DEFAULT_IP="192.168.1.50/24"
CON_NAME="afh03-scope"
IFACE=""
IPADDR=""
SCAN=""
USE_DHCP=0
STATUS_ONLY=0
REVERT=0
SCOPE_IP=""
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PKG_DIR="$(dirname "$HERE")"

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_INF=$'\033[36m'; C_END=$'\033[0m'
[ -t 1 ] || { C_OK=""; C_WARN=""; C_ERR=""; C_INF=""; C_END=""; }
ok()   { echo "  ${C_OK}[OK]${C_END}   $*"; }
warn() { echo "  ${C_WARN}[WARN]${C_END} $*"; }
err()  { echo "  ${C_ERR}[ERR]${C_END}  $*" >&2; }
sec()  { echo; echo "${C_INF}== $* ==${C_END}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        --iface) IFACE="${2:-}"; shift 2 ;;
        --ip)    IPADDR="${2:-}"; shift 2 ;;
        --scan)  SCAN="${2:-}"; shift 2 ;;
        --ip-scope) SCOPE_IP="${2:-}"; shift 2 ;;
        --dhcp)  USE_DHCP=1; shift ;;
        --status|--check) STATUS_ONLY=1; shift ;;
        --revert|--undo)  REVERT=1; shift ;;
        -h|--help) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) err "未知参数: $1"; exit 1 ;;
    esac
done
[ -n "$IPADDR" ] || IPADDR="$DEFAULT_IP"
IP_ONLY="${IPADDR%%/*}"
PREFIX="${IPADDR##*/}"
if [ -z "$SCAN" ]; then
    case "$IP_ONLY" in
        *.*.*.*) SCAN="$(echo "$IP_ONLY" | cut -d. -f1-3).0/$PREFIX" ;;
        *)       SCAN="192.168.1.0/24" ;;
    esac
fi

echo "############################################################"
echo "# AFH03 板端以太网 + 示波器发现   $(date '+%F %T')"
echo "# 板子 IP 目标 : $IPADDR    扫描网段: $SCAN"
echo "############################################################"

show_link() {
    sec "网口状态"
    ip -br link 2>&1 | sed 's/^/  /'
    echo "  --- carrier / operstate ---"
    for f in /sys/class/net/*/carrier; do
        d="$(dirname "$f")"; n="$(basename "$d")"
        [ "$n" = "lo" ] && continue
        printf "  %-8s carrier=%s operstate=%s speed=%s\n" \
            "$n" "$(cat "$f" 2>/dev/null || echo '?')" \
            "$(cat "$d/operstate" 2>/dev/null || echo '?')" \
            "$(cat "$d/speed" 2>/dev/null || echo '?')"
    done
    sec "地址与路由"
    ip -br addr 2>&1 | sed 's/^/  /'
    ip route 2>&1 | sed 's/^/  /'
    echo "  --- 邻居表(ARP) ---"
    ip neigh 2>&1 | sed 's/^/  /' || true
}

pick_iface() {
    if [ -n "$IFACE" ]; then echo "$IFACE"; return; fi
    for f in /sys/class/net/*/carrier; do
        d="$(dirname "$f")"; n="$(basename "$d")"
        [ "$n" = "lo" ] && continue
        if [ "$(cat "$f" 2>/dev/null || echo 0)" = "1" ]; then echo "$n"; return; fi
    done
    echo ""
}

if [ "$STATUS_ONLY" = 1 ]; then
    show_link
    sec "SCPI 扫描（只读，找 5555 端口上的 RIGOL）"
    if command -v python3 >/dev/null 2>&1 && [ -f "$PKG_DIR/soc_vision/scpi_scope.py" ]; then
        (cd "$PKG_DIR" && timeout 60 python3 -m soc_vision.scpi_scope --scan "$SCAN" 2>&1 | sed 's/^/  /')
        rc=${PIPESTATUS[0]:-1}
        [ "$rc" = "0" ] || warn "扫描未找到示波器（rc=$rc）—— 网线/网段/示波器电源都要确认"
    else
        warn "找不到 $PKG_DIR/soc_vision/scpi_scope.py，只做网口状态检查"
    fi
    exit 0
fi

if [ "$REVERT" = 1 ]; then
    sec "撤销本脚本的配置"
    if command -v nmcli >/dev/null 2>&1 && nmcli -t -f NAME con show 2>/dev/null | grep -qx "$CON_NAME"; then
        nmcli con down "$CON_NAME" 2>&1 | sed 's/^/  /'
        nmcli con delete "$CON_NAME" 2>&1 | sed 's/^/  /'
        ok "已删除连接 $CON_NAME"
    fi
    if [ -n "$(pick_iface)" ]; then
        ip addr del "$IPADDR" dev "$(pick_iface)" 2>/dev/null && ok "已移除 $IPADDR" || warn "没有 $IPADDR 可移除"
    fi
    exit 0
fi

show_link
IFC="$(pick_iface)"
if [ -z "$IFC" ]; then
    sec "结论"
    err "两个网口的 carrier 都是 0 —— 网线没插，或者插错口。"
    err "板载两个网口对应关系（厂家文档）：底板 ETH0 -> 系统 eth1(end1)，底板 ETH1 -> 系统 eth0(end0)。"
    err "请把示波器的 LAN 口接到板子的网口，然后再跑一次本脚本；或者 --iface end0/end1 手动指定。"
    exit 2
fi
ok "选中的网口: $IFC（carrier=1）"

sec "配置地址"
if [ "$USE_DHCP" = 1 ]; then
    got=""
    if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
        nmcli con up "$IFACE" >/dev/null 2>&1 || true
        nmcli dev connect "$IFC" >/dev/null 2>&1 || true
        sleep 3
        got="$(ip -4 -br addr show "$IFC" | awk '{print $3}')"
    fi
    for c in udhcpc dhclient; do
        if [ -z "$got" ] && command -v "$c" >/dev/null 2>&1; then
            ip link set "$IFC" up
            timeout 20 "$c" -i "$IFC" >/dev/null 2>&1 || true
            sleep 1
            got="$(ip -4 -br addr show "$IFC" | awk '{print $3}')"
        fi
    done
    if [ -n "$got" ]; then ok "DHCP 拿到 $got"; else warn "DHCP 没拿到地址（网络里可能没有 DHCP 服务器）→ 改用静态 IP"; USE_DHCP=0; fi
fi

if [ "$USE_DHCP" = 0 ]; then
    if command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
        nmcli con show "$CON_NAME" >/dev/null 2>&1 && nmcli con delete "$CON_NAME" >/dev/null 2>&1
        if nmcli con add type ethernet ifname "$IFC" con-name "$CON_NAME" \
                ip4 "$IPADDR" >/dev/null 2>&1; then
            nmcli con up "$CON_NAME" >/dev/null 2>&1 || true
            ok "nmcli 连接 $CON_NAME: $IPADDR on $IFC"
        else
            warn "nmcli 添加连接失败，退回 ip 命令"
        fi
    fi
    if ! ip -4 -br addr show "$IFC" | grep -q "$IP_ONLY"; then
        ip link set "$IFC" up
        ip addr add "$IPADDR" dev "$IFC" 2>/dev/null && ok "ip addr add $IPADDR dev $IFC" \
            || warn "地址可能已存在，继续"
    fi
fi

sec "配完后的状态"
ip -4 -br addr show "$IFC" 2>&1 | sed 's/^/  /'
ip route 2>&1 | sed 's/^/  /'
if ! ip -4 -br addr show "$IFC" | grep -q "UP"; then
    err "网口没有起来或没有拿到地址，配置失败"
    exit 3
fi

sec "扫描示波器（ICMP 填 ARP + TCP 5555 问 *IDN?）"
BASE="$(echo "$IP_ONLY" | cut -d. -f1-3)"
for i in $(seq 1 254); do
    ( ping -c1 -W1 "$BASE.$i" >/dev/null 2>&1 & ) 2>/dev/null
done
sleep 2
echo "  --- 存活邻居 ---"
ip neigh | grep -E "REACHABLE|STALE|DELAY" | sed 's/^/  /' || echo "  (ARP 表空：这一侧可能只有示波器且未响应 ICMP)"

FOUND=""
if command -v python3 >/dev/null 2>&1 && [ -f "$PKG_DIR/soc_vision/scpi_scope.py" ]; then
    out="$(cd "$PKG_DIR" && timeout 90 python3 -m soc_vision.scpi_scope --scan "$SCAN" 2>&1)"
    printf '%s\n' "$out" | sed 's/^/  /'
    FOUND="$(printf '%s\n' "$out" | awk '/rigol=yes/ {print $1; exit}')"
else
    warn "没有 python3 或 scpi_scope.py，跳过 SCPI 扫描"
fi

if [ -z "$FOUND" ] && [ -n "$SCOPE_IP" ]; then
    FOUND="$SCOPE_IP"
    warn "扫描没结果，用 --ip-scope 指定的 $FOUND 直接判断"
fi

if [ -z "$FOUND" ]; then
    sec "结论"
    err "网口已配好（$IP_ONLY），但 $SCAN 里没有回答 SCPI 的 RIGOL 仪器。"
    err "排查：① 示波器 LAN 是否使能并配了同网段 IP（Utility->IO->LAN）② 示波器电源/网口指示灯"
    err "      ③ 换一个网段试试 --ip 192.168.0.50/24；④ 直接用 --ip-scope <IP> 指定"
    exit 4
fi

sec "结论"
ok "板子网口 $IFC = $IPADDR"
ok "示波器 = $FOUND"
echo "  --- ping 证据 ---"
ping -c 2 -W 1 "$FOUND" 2>&1 | sed 's/^/  /'
echo
echo "  下一步（主判据 = SCPI 直读）："
echo "    cd $PKG_DIR && python3 -m soc_vision.scpi_scope --host $FOUND --nominal 20000000,40000000 --tol-pct 1 --repeat 5"
echo "  真机验收（与模拟验收同一套断言）："
echo "    python3 tools/scpi_sim_selftest.py            # 把 --host 换成示波器 IP 后再跑一遍"
exit 0
