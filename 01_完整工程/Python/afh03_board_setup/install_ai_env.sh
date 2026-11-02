#!/usr/bin/env bash

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

WHEEL_DIR="$SCRIPT_DIR/whl"
MIRROR="https://pypi.tuna.tsinghua.edu.cn/simple"
VENV=""
HEADLESS=0
SKIP_APT=0
DO_SHA=1
PYTHON_BIN="${PYTHON_BIN:-python3}"

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    cat <<'EOF'

可选参数：
  --wheel-dir DIR     存放 7 个 .whl 的目录（默认 <脚本目录>/whl）
  --mirror URL        公网 pip 镜像（默认清华源；离线时用不到）
  --venv PATH         装进虚拟环境而不是系统 python（推荐 /opt/afh03-ai）
  --headless          只装 opencv-python-headless（无 GUI，省 14MB）
  --skip-apt          跳过系统库 apt 安装（纯离线场景）
  --no-sha            跳过 whl 的 sha256 校验
  --python BIN        指定 python 解释器（默认 python3）
  -h|--help           显示本帮助
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --wheel-dir)  WHEEL_DIR="${2:-}"; shift 2 ;;
        --mirror)     MIRROR="${2:-}"; shift 2 ;;
        --venv)       VENV="${2:-}"; shift 2 ;;
        --python)     PYTHON_BIN="${2:-}"; shift 2 ;;
        --headless)   HEADLESS=1; shift ;;
        --skip-apt)   SKIP_APT=1; shift ;;
        --no-sha)     DO_SHA=0; shift ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "[ERR] 未知参数: $1"; usage; exit 1 ;;
    esac
done

C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_INF=$'\033[36m'; C_END=$'\033[0m'
if [ ! -t 1 ]; then C_OK=""; C_WARN=""; C_ERR=""; C_INF=""; C_END=""; fi
STEP=0
step() { STEP=$((STEP+1)); echo; echo "${C_INF}>>> [$STEP] $*${C_END}"; }
ok()   { echo "    ${C_OK}OK${C_END}   $*"; }
warn() { echo "    ${C_WARN}WARN${C_END} $*"; }
err()  { echo "    ${C_ERR}ERR${C_END}  $*" >&2; }
die()  { err "$*"; exit "${2:-1}"; }

echo "============================================================"
echo " AFH03 RK3576 - AI 运行环境安装"
echo " Date        : $(date '+%F %T')"
echo " Wheel dir   : $WHEEL_DIR"
echo " Python      : $PYTHON_BIN"
echo " venv        : ${VENV:-<系统 python>}"
echo " opencv 变体 : $([ "$HEADLESS" = 1 ] && echo headless || echo GUI)"
echo "============================================================"

step "检查板卡与解释器"
[ "$(uname -m)" = "aarch64" ] || warn "当前架构 $(uname -m) 不是 aarch64，这些 whl 只能装在 aarch64 板子上"

command -v "$PYTHON_BIN" >/dev/null 2>&1 || die "找不到 $PYTHON_BIN"
PY_VER="$("$PYTHON_BIN" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null)"
[ -n "$PY_VER" ] || die "$PYTHON_BIN 无法执行"
if [ "$PY_VER" != "3.11" ]; then
    warn "Python 版本是 $PY_VER，本套 whl 是按 cp311 编译的，cp311 whl 无法安装到 $PY_VER"
    warn "板子出厂镜像为 Python 3.11.2；若已被改动，请先恢复 python3.11 或改用 conda python3.11"
    die  "解释器版本不匹配（需要 3.11）" 1
fi
ok "$("$PYTHON_BIN" -c 'import sys;print(sys.version)')"
ok "可执行文件: $(command -v "$PYTHON_BIN")"

if [ -f /usr/lib/librknnrt.so ]; then
    ok "/usr/lib/librknnrt.so 存在"
    strings /usr/lib/librknnrt.so 2>/dev/null | grep -i -m1 'librknnrt version' \
        | sed 's/^/    NPU 运行时: /' || true
else
    warn "/usr/lib/librknnrt.so 不存在 -> rknnlite 会 import 成功但 init_runtime 失败"
    warn "请从出厂镜像恢复，或单独拷 librknnrt.so 到 /usr/lib/"
fi
[ -f /usr/bin/rknn_server ] && ok "/usr/bin/rknn_server 存在" || warn "/usr/bin/rknn_server 缺失"

WHEEL_TABLE='numpy-2.2.6-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl|b64d8d4d17135e00c8e346e0a738deb17e754230d7e0810ac5012750bbd85a5a|14312005
opencv_python-5.0.0.93-cp37-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl|e2b4272e736836f66c2d176e43ab8101f3a00d45654916399f52e150c58981ac|50614064
opencv_python_headless-5.0.0.93-cp37-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl|10818d91510e05c04568ae12b5cd120779c70c01bf897b001a6221fe430df80f|36521085
rknn_toolkit_lite2-2.3.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl|e3e4fefe355dc34a155680e4bcb9e4abb37ebc271f045ec9e0a4a3a018bc5beb|569149
psutil-7.2.2-cp36-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl|b0726cecd84f9474419d67252add4ac0cd9811b04d61123054b9fb6f57df6e9e|156997
ruamel_yaml-0.19.1-py3-none-any.whl|27592957fedf6e0b62f281e96effd28043345e0e66001f97683aa9a40c667c93|118102
ruamel_yaml_clib-0.2.15-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl|ef71831bd61fbdb7aa0399d5c4da06bea37107ab5c79ff884cc07f2450910262|749289'

step "校验 whl 目录: $WHEEL_DIR"
[ -d "$WHEEL_DIR" ] || die "whl 目录不存在: $WHEEL_DIR" 2

MISSING=0
while IFS='|' read -r name sha size; do
    [ -n "$name" ] || continue
    f="$WHEEL_DIR/$name"
    if [ ! -f "$f" ]; then warn "缺失 $name"; MISSING=$((MISSING+1)); continue; fi
    actual_size=$(stat -c%s "$f" 2>/dev/null || echo 0)
    if [ "$actual_size" != "$size" ]; then
        warn "$name 大小不符 (期望 $size, 实际 $actual_size) —— 可能被截断"
    fi
    if [ "$DO_SHA" = 1 ]; then
        actual_sha=$(sha256sum "$f" | awk '{print $1}')
        if [ "$actual_sha" != "$sha" ]; then
            err "$name sha256 不符"; echo "        期望 $sha"; echo "        实际 $actual_sha"
            MISSING=$((MISSING+1)); continue
        fi
    fi
    ok "$name"
done <<< "$WHEEL_TABLE"

[ "$MISSING" -eq 0 ] || die "有 $MISSING 个 whl 缺失或校验失败，请从厂家资料重新拷贝" 2

EXTRA_COUNT=$(find "$WHEEL_DIR" -maxdepth 1 -name '*.whl' 2>/dev/null | wc -l)
ok "目录内共 $EXTRA_COUNT 个 whl"

step "准备 pip"
if [ -n "$VENV" ]; then
    PY="$VENV/bin/python"
    if [ ! -x "$PY" ]; then
        echo "    创建虚拟环境 $VENV ..."
        if ! "$PYTHON_BIN" -m venv "$VENV" 2>/dev/null; then
            if ! "$PYTHON_BIN" -m venv --without-pip "$VENV" 2>/dev/null; then
                die "venv 创建失败：先安装 python3-venv（apt-get install -y python3-venv）" 1
            fi
            warn "venv 无 pip，用官方 get-pip 兜底（需公网）"
            curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && "$PY" /tmp/get-pip.py -i "$MIRROR"
        fi
    fi
    [ -x "$PY" ] || die "虚拟环境 python 不可用: $PY" 1
    PIP=("$PY" -m pip)
    ok "venv python: $("$PY" -V 2>&1)"
else
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        warn "系统 python 没有 pip，尝试 apt 安装 python3-pip"
        if [ "$SKIP_APT" = 0 ]; then
            apt-get update -qq 2>/dev/null || true
            apt-get install -y --no-install-recommends python3-pip 2>/dev/null || true
        fi
    fi
    if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
        warn "apt 未提供 pip，尝试 ensurepip"
        "$PYTHON_BIN" -m ensurepip --upgrade 2>/dev/null || true
    fi
    "$PYTHON_BIN" -m pip --version >/dev/null 2>&1 \
        || die "pip 不可用：离线时请把 python3-pip 的 .deb（arm64）一起拷到板上 dpkg -i" 1
    PIP=("$PYTHON_BIN" -m pip)
    ok "$("$PYTHON_BIN" -m pip --version)"
fi

PIP_EXTRA=()
if [ -z "$VENV" ]; then
    if [ -f /usr/lib/python3.11/EXTERNALLY-MANAGED ]; then
        PIP_EXTRA+=(--break-system-packages)
        warn "系统 python 受 PEP668 保护，已追加 --break-system-packages（等价于厂家 conda 方案的效果）"
    fi
fi
PIP_OFFLINE=(--no-index --find-links "$WHEEL_DIR")

step "补齐 opencv 运行需要的系统库（可 --skip-apt 跳过）"
if [ "$SKIP_APT" = 1 ]; then
    warn "已跳过 apt"
else
    APT_LIBS="libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 libfontconfig1 libdbus-1-3"
    if [ "$HEADLESS" = 0 ]; then APT_LIBS="$APT_LIBS libgtk-3-0"; fi
    if apt-get install -y --no-install-recommends $APT_LIBS >/tmp/afh03_apt.log 2>&1; then
        ok "apt 系统库: $APT_LIBS"
    else
        warn "apt 安装失败（离线/无源）。若 cv2 import 报 libGL.so.1 之类的错，"
        warn "请手动 dpkg -i 这些 .deb；日志 /tmp/afh03_apt.log"
    fi
fi

step "离线安装 whl（--no-index --no-deps，顺序固定）"
install_one() {
    local f="$WHEEL_DIR/$1"
    echo "    -> $1"
    if "${PIP[@]}" install "${PIP_OFFLINE[@]}" --no-deps --upgrade "${PIP_EXTRA[@]}" "$f" \
            >/tmp/afh03_pip_$$.log 2>&1; then
        ok "$1"
    else
        err "$1 安装失败"
        tail -n 25 /tmp/afh03_pip_$$.log | sed 's/^/        /'
        return 1
    fi
}

FAIL=0
install_one numpy-2.2.6-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl || FAIL=1
install_one ruamel_yaml-0.19.1-py3-none-any.whl                                                  || FAIL=1
install_one ruamel_yaml_clib-0.2.15-cp311-cp311-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl || FAIL=1
install_one psutil-7.2.2-cp36-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.manylinux_2_28_aarch64.whl || FAIL=1
if [ "$HEADLESS" = 1 ]; then
    install_one opencv_python_headless-5.0.0.93-cp37-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl || FAIL=1
else
    install_one opencv_python-5.0.0.93-cp37-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl || FAIL=1
fi
install_one rknn_toolkit_lite2-2.3.0-cp311-cp311-manylinux_2_17_aarch64.manylinux2014_aarch64.whl || FAIL=1

[ "$FAIL" -eq 0 ] || die "有 wheel 安装失败，见上面的日志" 3

step "依赖完整性检查（缺什么再用镜像补）"
if ! "${PIP[@]}" check >/tmp/afh03_pipcheck.log 2>&1; then
    warn "pip check 报告问题："
    sed 's/^/        /' /tmp/afh03_pipcheck.log
    warn "尝试用镜像 $MIRROR 补齐（离线会失败，属正常）"
    "${PIP[@]}" install --index-url "$MIRROR" --upgrade ruamel.yaml psutil "${PIP_EXTRA[@]}" \
        >/tmp/afh03_pip_fix.log 2>&1 && ok "已用镜像补齐" || warn "镜像不可用，忽略"
else
    ok "pip check 通过"
fi

step "装后自检（import + 版本 + NPU）"
if [ -n "$VENV" ]; then RUN_PY="$VENV/bin/python"; else RUN_PY="$PYTHON_BIN"; fi

"$RUN_PY" - <<'PYEOF'
import sys, traceback
fail = 0
print("    python     :", sys.version.split()[0], sys.executable)
try:
    import numpy; print("    numpy      :", numpy.__version__)
except Exception as e:
    print("    numpy      : FAIL", e); fail = 1
try:
    import cv2; print("    opencv     :", cv2.__version__,
                      "| GUI:", not cv2.getBuildInformation().count("GUI:                           NONE"))
except Exception as e:
    print("    opencv     : FAIL", e); fail = 1
try:
    import rknnlite
    from rknnlite.api import RKNNLite
    print("    rknnlite   : import OK, NPU_CORE_0 =", RKNNLite.NPU_CORE_0)
except Exception as e:
    print("    rknnlite   : FAIL", e); fail = 1
try:
    import ruamel.yaml; print("    ruamel.yaml:", ruamel.yaml.__version__)
except Exception as e:
    print("    ruamel.yaml: WARN", e)
try:
    import psutil; print("    psutil     :", psutil.__version__)
except Exception as e:
    print("    psutil     : WARN", e)

try:
    import glob
    devs = sorted(glob.glob("/dev/video*"))
    print("    v4l2 节点  :", " ".join(devs) if devs else "(无)")
except Exception:
    pass
sys.exit(1 if fail else 0)
PYEOF
SELF=$?

MODEL=""
for cand in "$SCRIPT_DIR/models/yolov5s_relu.rknn" "$SCRIPT_DIR/yolov5s_relu.rknn" /home/rock/yolo/yolov5s_relu.rknn; do
    [ -f "$cand" ] && { MODEL="$cand"; break; }
done
if [ -n "$MODEL" ]; then
    echo "    用 $MODEL 做 init_runtime 实测 ..."
    "$RUN_PY" - "$MODEL" <<'PYEOF'
import sys
from rknnlite.api import RKNNLite
rknn = RKNNLite(verbose=False)
if rknn.load_rknn(sys.argv[1]) != 0:
    print("    load_rknn  : FAIL"); sys.exit(1)
print("    load_rknn  : OK")
if rknn.init_runtime(core_mask=RKNNLite.NPU_CORE_0) != 0:
    print("    init_runtime: FAIL（librknnrt 与 whl 版本不匹配？）"); sys.exit(1)
print("    init_runtime: OK  SDK version =", rknn.get_sdk_version())
rknn.release()
PYEOF
    [ $? -ne 0 ] && SELF=1
else
    warn "未找到 .rknn 模型，跳过 init_runtime 实测（把 yolov5s_relu.rknn 放到 $SCRIPT_DIR/models/ 可自动测）"
fi

echo
if [ "$SELF" -eq 0 ]; then
    echo "${C_OK}============================================================${C_END}"
    echo "${C_OK} 安装完成，自检通过${C_END}"
    echo " 使用解释器: $RUN_PY"
    echo " 下一步    : bash $SCRIPT_DIR/verify_env.sh"
    echo "             bash $SCRIPT_DIR/capture_probe.sh"
    echo "${C_OK}============================================================${C_END}"
    exit 0
else
    echo "${C_ERR}============================================================${C_END}"
    echo "${C_ERR} 自检未通过，请把上面的 FAIL 行连同以下信息一起排查：${C_END}"
    echo "   ldd \$(python3 -c 'import cv2;print(cv2.__file__)')   # 看缺哪个 .so"
    echo "   strings /usr/lib/librknnrt.so | grep -i 'librknnrt version'"
    echo "${C_ERR}============================================================${C_END}"
    exit 4
fi
