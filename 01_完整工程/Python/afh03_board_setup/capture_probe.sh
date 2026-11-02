#!/usr/bin/env bash
set -uo pipefail

DEV=""
RAW=0
OUTDIR="/tmp/afh03_probe"
W=1920; H=1080
PYTHON_BIN="${PYTHON_BIN:-python3}"
TMO="timeout ${AFH03_V4L2_TIMEOUT:-8}"

usage() { sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
    case "$1" in
        -d|--device) DEV="${2:-}"; shift 2 ;;
        --raw)       RAW=1; shift ;;
        -o|--outdir) OUTDIR="${2:-}"; shift 2 ;;
        -w)          W="${2:-}"; shift 2 ;;
        -h2|--height) H="${2:-}"; shift 2 ;;
        -h|--help)   usage; exit 0 ;;
        *) echo "未知参数: $1"; usage; exit 1 ;;
    esac
done

mkdir -p "$OUTDIR"

echo "################ AFH03 视频节点探测 ################"
echo

echo "== 1. /dev/video* 与驱动名字 =="
for v in /sys/class/video4linux/video*/name; do
    [ -f "$v" ] || continue
    d="/dev/$(basename "$(dirname "$v")")"
    n="$(cat "$v" 2>/dev/null)"
    printf "  %-16s %s\n" "$d" "$n"
done
echo

echo "== 2. v4l2-ctl --list-devices（按驱动分组）=="
if command -v v4l2-ctl >/dev/null 2>&1; then
    $TMO v4l2-ctl --list-devices 2>&1 | sed 's/^/  /'
else
    echo "  (没有 v4l2-ctl，apt install v4l-utils)"
fi
echo

echo "== 3. media 拓扑（rkisp 的 video 节点对应关系看这里）=="
if [ -d /sys/class/media ]; then
    ls -d /sys/class/media/* 2>/dev/null | sed 's/^/  /'
    for m in /dev/media*; do [ -e "$m" ] && echo "  $m"; done
else
    echo "  (无 media controller)"
fi
echo

if [ -z "$DEV" ]; then
    for v in /sys/class/video4linux/video*/name; do
        [ -f "$v" ] || continue
        if grep -qiE 'milianke|fpga' "$v" 2>/dev/null; then
            DEV="/dev/$(basename "$(dirname "$v")")"; break
        fi
    done
    [ -z "$DEV" ] && [ -e /dev/video22 ] && DEV=/dev/video22
    [ -z "$DEV" ] && DEV="$(ls /dev/video* 2>/dev/null | head -1)"
fi

if [ -z "$DEV" ]; then
    echo "找不到任何 /dev/video* —— 检查 MIPI 线、驱动、设备树"
    exit 1
fi

echo "== 4. 目标节点 $DEV =="
if command -v v4l2-ctl >/dev/null 2>&1; then
    $TMO v4l2-ctl -d "$DEV" --info 2>&1 | sed 's/^/  /'
    echo "  --- 支持的格式 ---"
    $TMO v4l2-ctl -d "$DEV" --list-formats-ext 2>&1 | sed 's/^/  /'
    echo "  --- 当前格式 ---"
    $TMO v4l2-ctl -d "$DEV" --get-fmt-video 2>&1 | sed 's/^/  /'
    echo "  --- 可用 ctrl（曝光/增益是否可锁，LED 判定很关键）---"
    $TMO v4l2-ctl -d "$DEV" -l 2>&1 | sed 's/^/  /'
fi
echo

echo "== 5. 抓一帧 =="
echo "  🚫 纪律：不要用无超时的取流命令。首选自 poll 工具（超时自己 STREAMOFF+close，永不外部 kill）："
echo "       python3 tools/v4l2_poll_snap.py -d $DEV --out $OUTDIR/raw_yuyv.bin --png $OUTDIR/frame_poll.png --report"
echo "     下面的 v4l2-ctl 路径是**高危兜底**：它没有内部超时，只在你已确认会出帧时用（已套 $TMO）。"
if [ "$RAW" = 1 ]; then
    echo "  方式：v4l2-ctl 抓 1 帧原始 YUYV -> $OUTDIR/raw_yuyv.bin（套 $TMO；rc=124 会立即中止）"
    if command -v v4l2-ctl >/dev/null 2>&1; then
        $TMO v4l2-ctl -d "$DEV" --set-fmt-video=width=$W,height=$H,pixelformat=YUYV \
                 --stream-mmap=4 --stream-count=1 --stream-to="$OUTDIR/raw_yuyv.bin" 2>&1 | sed 's/^/    /'
        RAWRC=${PIPESTATUS[0]:-1}
        if [ "$RAWRC" = "124" ]; then
            echo "    [WARN] v4l2-ctl 超时被 timeout 杀掉（rc=124）—— 设备没在出帧"
            echo "    [ABORT] 按纪律**立即停止**，不要连环重试取流（连环 kill 是 SoC 卡死/复位的根因）；"
            echo "            请改用：python3 tools/v4l2_poll_snap.py -d $DEV --out /tmp/f.raw --report"
            exit 3
        fi
        ls -l "$OUTDIR/raw_yuyv.bin" 2>/dev/null | sed 's/^/    /'
        echo "    期望大小 = $((W*H*2)) 字节（YUYV）"
        if [ -f "$OUTDIR/raw_yuyv.bin" ]; then
            "$PYTHON_BIN" - "$OUTDIR/raw_yuyv.bin" <<'PYEOF'
import sys
d = open(sys.argv[1], "rb").read()
if not d:
    print("    [EMPTY] 抓到 0 字节"); raise SystemExit(0)
n = len(d)
ff = d.count(0xff)
print("    0xFF 占比 = %.2f%%（%d/%d）  不同字节值 = %d" % (ff*100.0/n, ff, n, len(set(d))))
if ff * 100.0 / n > 95:
    print("    [DUMMY] 几乎全是 0xFF -> FPGA 没有配置（需要重新下载 bit），这不是真实画面")
else:
    print("    [REAL?] 字节有分布，像真实图像数据（再用 png 目视确认）")
PYEOF
        fi
    else
        echo "    需要 v4l2-ctl（apt install v4l-utils）"
    fi
fi

if command -v python3 >/dev/null 2>&1 && [ -f "$(dirname "$0")/tools/v4l2_poll_snap.py" ]; then
    echo "  方式（首选）：自 poll 工具 -> $OUTDIR/frame_poll.png（超时自己 STREAMOFF+close，不需要外部 kill）"
    timeout 30 "$PYTHON_BIN" "$(dirname "$0")/tools/v4l2_poll_snap.py" -d "$DEV" \
            --out "$OUTDIR/raw_yuyv.bin" --png "$OUTDIR/frame_poll.png" --report --timeout-ms 3000
    echo "    自 poll 工具 rc=$?（0=成功 / 3=超时已干净退出）"
else
    echo "  [skip] 找不到 tools/v4l2_poll_snap.py，已**按纪律跳过** OpenCV 阻塞式抓帧"
fi

echo "  方式（高危兜底，仅在确认会出帧时用）：python3 + OpenCV 抓帧 -> $OUTDIR/frame_opencv.png（套 $TMO）"
if [ "${AFH03_ALLOW_UNSAFE_OPENCV_GRAB:-0}" != "1" ]; then
    echo "    [skip] 默认跳过：cap.read() 在不出帧时会永久阻塞，被 timeout 杀掉会弄脏 CSI 收尾。"
    echo "           确实要用请设 AFH03_ALLOW_UNSAFE_OPENCV_GRAB=1（**并自行承担卡死风险**）"
else
$TMO "$PYTHON_BIN" - "$DEV" "$W" "$H" "$OUTDIR" <<'PYEOF'
import sys, os
try:
    import cv2
    import numpy as np
except Exception as e:
    print("    [skip] 没有 cv2/numpy: %s" % e); sys.exit(0)
dev, W, H, outdir = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
if not cap.isOpened():
    print("    [FAIL] 打不开 %s" % dev); sys.exit(1)
cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'YUYV'))
cap.set(cv2.CAP_PROP_FRAME_WIDTH, W)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, H)
cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
print("    实际协商: %dx%d fourcc=%s" % (
    int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
    int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
    int(cap.get(cv2.CAP_PROP_FOURCC))))
good = 0
for i in range(60):
    ret, f = cap.read()
    if ret and f is not None:
        good += 1
        if good == 3:                      # 丢掉前 2 帧，避免拿到未稳定的首帧
            p = os.path.join(outdir, "frame_opencv.png")
            cv2.imwrite(p, f)
            print("    取帧成功 shape=%s -> %s" % (f.shape, p))
            print("    帧亮度 mean=%.1f max=%d（若 mean≈0 说明是黑帧，检查曝光/连线）" %
                  (f.mean(), f.max()))
            gray = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            uniq = int(len(np.unique(gray)))
            white = float((gray >= 250).mean() * 100.0)
            print("    灰度: min=%d max=%d 均值=%.1f 标准差=%.1f 灰阶数=%d 纯白占比=%.2f%%" %
                  (gray.min(), gray.max(), gray.mean(), gray.std(), uniq, white))
            if uniq <= 20 and white > 90:
                print("    [DUMMY] 灰阶极少且几乎全白 -> FPGA 未配置（rkcif dummy buffer），不是真实画面")
            else:
                print("    [REAL] 灰阶丰富/有噪声 -> 像真实画面")
            break
    else:
        good = 0
cap.release()
sys.exit(0 if good else 1)
PYEOF
RC=$?
if [ $RC -eq 124 ]; then
    echo "    [WARN] OpenCV 抓帧被 timeout(${AFH03_V4L2_TIMEOUT:-8}s) 杀掉 —— 设备没在出帧"
elif [ $RC -ne 0 ]; then
    echo "    [FAIL] OpenCV 抓帧失败（格式不匹配？先用 v4l2-ctl 设成 YUYV 或 NV12 再试）"
fi
fi   # ← 结束 AFH03_ALLOW_UNSAFE_OPENCV_GRAB 的外层 if

echo
echo "== 6. 结果文件 =="
ls -l "$OUTDIR" 2>/dev/null | sed 's/^/  /'
echo
echo "提示："
echo "  * FPGA 嵌入状态字解码：python3 -c \"import sys;sys.path.insert(0,'$(dirname "$0")');from soc_vision.fpga_status import scan_raw_yuyv;print(scan_raw_yuyv(open('$OUTDIR/raw_yuyv.bin','rb').read()))\""
echo "  * NV12 的 imx415 节点：把 --set-fmt-video 的 pixelformat 换成 NV12，python 侧用 pixfmt='NV12'"
