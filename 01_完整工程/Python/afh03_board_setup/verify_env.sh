#!/usr/bin/env bash
set -uo pipefail

MODEL=""
VENV=""
GRAB=""
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        --model)  MODEL="${2:-}"; shift 2 ;;
        --venv)   VENV="${2:-}"; shift 2 ;;
        --grab)   GRAB="${2:-}"; shift 2 ;;
        --python) PYTHON_BIN="${2:-}"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

if [ -n "$VENV" ]; then RUN_PY="$VENV/bin/python"; else RUN_PY="$(command -v "$PYTHON_BIN" || echo "$PYTHON_BIN")"; fi
FAIL=0
hr() { echo "------------------------------------------------------------"; }
sec() { echo; echo "== $* =="; }
ok()  { echo "  [OK]   $*"; }
bad() { echo "  [FAIL] $*"; FAIL=$((FAIL+1)); }
nn()  { echo "  [--]   $*"; }

echo "############################################################"
echo "# AFH03 视觉/AI 环境自检   $(date '+%F %T')"
echo "############################################################"

sec "系统"
echo "  内核      : $(uname -r)  架构: $(uname -m)"
[ -r /proc/device-tree/compatible ] && \
    echo "  SoC       : $(tr '\0' ' ' < /proc/device-tree/compatible | tr -s ' ')"
echo "  发行版    : $(. /etc/os-release 2>/dev/null; echo "$PRETTY_NAME")"
echo "  内存      : $(awk '/MemTotal/{t=$2}/MemAvailable/{a=$2}END{printf "%.0f MB total, %.0f MB available", t/1024, a/1024}' /proc/meminfo 2>/dev/null)"
echo "  解释器    : $RUN_PY -> $("$RUN_PY" -V 2>&1)"

sec "Python 包"
"$RUN_PY" - <<'PYEOF'
import sys
def show(name, mod, attr="__version__"):
    try:
        m = __import__(mod)
        v = getattr(m, attr, "?")
        print("  [OK]   %-12s %s" % (name, v))
        return m
    except Exception as e:
        print("  [FAIL] %-12s %s" % (name, e))
        return None
fails = 0
if show("numpy", "numpy") is None: fails += 1
m = show("opencv", "cv2")
if m is None:
    fails += 1
else:
    try:
        bi = m.getBuildInformation()
        gui = "有" if "GUI:" in bi and "NONE" not in bi.split("GUI:")[1].split("\n")[0] else "无(GUI disabled)"
        print("           opencv GUI 支持: %s" % gui)
        print("           cv2 文件: %s" % m.__file__)
    except Exception:
        pass
if show("rknnlite", "rknnlite") is None: fails += 1
else:
    try:
        from rknnlite.api import RKNNLite
        print("           RKNNLite.NPU_CORE_0=%d  NPU_CORE_0_1_2=%d" %
              (RKNNLite.NPU_CORE_0, RKNNLite.NPU_CORE_0_1_2))
    except Exception as e:
        print("           RKNNLite 导入异常: %s" % e); fails += 1
show("ruamel.yaml", "ruamel.yaml")
show("psutil", "psutil")
sys.exit(1 if fails else 0)
PYEOF
[ $? -eq 0 ] || bad "Python 包不完整（bash install_ai_env.sh 重装）"

sec "NPU 用户态"
if [ -f /usr/lib/librknnrt.so ]; then
    ok "/usr/lib/librknnrt.so  ($(stat -c%s /usr/lib/librknnrt.so) bytes)"
    strings /usr/lib/librknnrt.so 2>/dev/null | grep -i 'librknnrt version' | head -2 | sed 's/^/         /'
else
    bad "/usr/lib/librknnrt.so 不存在"
fi
[ -x /usr/bin/rknn_server ] && ok "/usr/bin/rknn_server" || nn "/usr/bin/rknn_server 缺失（板上推理不需要它）"
lsmod 2>/dev/null | grep -i rknpu | sed 's/^/         /' || nn "未见 rknpu 内核模块（RKNPU 走 /dev/rknpu 或 drm accel）"
ls -l /dev/rknpu* 2>/dev/null | sed 's/^/         /' || true
ls -l /dev/dri/ 2>/dev/null | sed 's/^/         /' || true

if [ -n "$MODEL" ] && [ -f "$MODEL" ]; then
    sec "NPU 实机推理（init_runtime）"
    "$RUN_PY" - "$MODEL" <<'PYEOF'
import sys
from rknnlite.api import RKNNLite
p = sys.argv[1]
r = RKNNLite(verbose=False)
if r.load_rknn(p) != 0:
    print("  [FAIL] load_rknn"); sys.exit(1)
print("  [OK]   load_rknn  %s" % p)
if r.init_runtime(core_mask=RKNNLite.NPU_CORE_0) != 0:
    print("  [FAIL] init_runtime（librknnrt 版本与 whl 不匹配？）"); sys.exit(1)
print("  [OK]   init_runtime  SDK=%s" % r.get_sdk_version())
r.release()
PYEOF
    [ $? -eq 0 ] || bad "NPU 实测失败"
else
    sec "NPU 实机推理"
    nn "未指定 --model，跳过"
fi

sec "视频节点"
if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl --list-devices 2>&1 | sed 's/^/  /'
else
    nn "没有 v4l2-ctl（apt install v4l-utils 可装）"
fi
for v in /sys/class/video4linux/video*/name; do
    [ -f "$v" ] || continue
    printf "  %-16s %s\n" "/dev/$(basename "$(dirname "$v")")" "$(cat "$v")"
done

sec "GStreamer"
if command -v gst-launch-1.0 >/dev/null 2>&1; then
    ok "$(gst-launch-1.0 --version 2>/dev/null | head -1)"
else
    nn "未安装 gst-launch-1.0"
fi

sec "已知端口/设备冲突（现场踩过的坑）"
if command -v ss >/dev/null 2>&1; then
    if ss -ltn 2>/dev/null | grep -qE ':5555[[:space:]]'; then
        warn_port=$(ss -ltnp 2>/dev/null | grep -E ':5555[[:space:]]' | head -1)
        echo "  [注意] TCP 5555 已被占用: ${warn_port:-unknown}"
        echo "         板机模拟器请换端口（--port 15555）；连真示波器的 5555 不受影响"
    else
        ok "TCP 5555 空闲（可直接在本机起 SCPI 服务器）"
    fi
fi
[ -c /dev/watchdog ] && echo "  [注意] /dev/watchdog 存在（看门狗已启用，长时间阻塞会被复位）" \
    || nn "无 /dev/watchdog（本镜像未启用看门狗）"

sec "显示 / 桌面"
echo "  DISPLAY=${DISPLAY:-<未设置>}   WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-<未设置>}"
if command -v xrandr >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
    xrandr --listmonitors 2>/dev/null | sed 's/^/  /'
    xrandr 2>/dev/null | grep -E ' connected| disconnected' | sed 's/^/  /'
else
    nn "无 X 会话或没有 xrandr"
fi
ls /sys/class/drm/*/status >/dev/null 2>&1 && \
    for s in /sys/class/drm/*/status; do printf "  %-32s %s\n" "$s" "$(cat "$s")"; done

sec "GPIO / 总线"
if [ -r /sys/kernel/debug/gpio ]; then
    grep -E 'gpio-|GPIO' /sys/kernel/debug/gpio | head -40 | sed 's/^/  /'
else
    nn "/sys/kernel/debug/gpio 不可读（需要 root 且 debugfs 已挂载）"
fi
[ -d /sys/class/i2c-dev ] && ls /dev/i2c-* 2>/dev/null | tr '\n' ' ' | sed 's/^/  I2C: /' && echo

sec "PCIe（异构方案 b 才需要）"
if command -v lspci >/dev/null 2>&1; then
    lspci 2>/dev/null | sed 's/^/  /' || nn "lspci 无输出"
else
    nn "没有 lspci"
fi

if [ -n "$GRAB" ]; then
    sec "抓帧 $GRAB -> /tmp/afh03_frame.png"
    SAFE_SNAP="$(dirname "$0")/tools/v4l2_poll_snap.py"
    if [ -f "$SAFE_SNAP" ]; then
        timeout 30 "$RUN_PY" "$SAFE_SNAP" -d "$GRAB" --out /tmp/afh03_frame.raw \
                --png /tmp/afh03_frame.png --report --timeout-ms 3000
        RC=$?
        if [ "$RC" = "0" ]; then
            ok "已用自 poll 工具抓帧 -> /tmp/afh03_frame.png（另存 /tmp/afh03_frame.raw）"
        elif [ "$RC" = "3" ]; then
            nn "poll 超时：$GRAB 当前不出帧（已由工具自己干净退出，未 kill 任何进程）"
        else
            bad "抓帧失败（自 poll 工具 rc=$RC）"
        fi
    else
        nn "为了安全，verify_env.sh 不再自己抓帧（cap.read() 可能永久阻塞）。请用："
        echo "         python3 tools/v4l2_poll_snap.py -d $GRAB --out /tmp/f.raw --png /tmp/f.png --report"
        echo "     若只想核对格式，用只读命令："
        echo "         timeout 8 v4l2-ctl -d $GRAB --get-fmt-video"
    fi
fi

hr
if [ "$FAIL" -eq 0 ]; then
    echo "结论：自检通过（0 个 FAIL）"
    exit 0
else
    echo "结论：有 $FAIL 个 FAIL，见上面 [FAIL] 行"
    exit 1
fi
