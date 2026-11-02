#!/bin/sh

SVC="${AFH03_VIDEO_SVC:-afh03-forensics.service}"
DEV="${AFH03_VIDEO_DEV:-/dev/video22}"

holders() {
    for p in /proc/[0-9]*; do
        pid=${p#/proc/}
        for fd in "$p"/fd/*; do
            [ -e "$fd" ] || continue
            t=$(readlink "$fd" 2>/dev/null)
            case "$t" in
                *"$DEV") echo "  pid=$pid comm=$(cat "$p/comm" 2>/dev/null) cmd=$(tr '\0' ' ' < "$p/cmdline" 2>/dev/null | cut -c1-100)" ;;
            esac
        done
    done
}

do_status() {
    echo "== 设备 =="
    ls -l "$DEV" 2>&1
    echo "== 当前占用者 =="
    h=$(holders)
    if [ -n "$h" ]; then echo "$h"; else echo "  （空闲：没有进程打开 $DEV）"; fi
    echo "== 服务状态 =="
    for s in "$SVC" afh03-vision.service afh03-vision-gui.service; do
        printf "  %-28s enabled=%-9s active=%s\n" "$s" "$(systemctl is-enabled "$s" 2>&1)" "$(systemctl is-active "$s" 2>&1)"
    done
}

wait_free() {
    _n=${1:-20}
    i=0
    while [ "$i" -lt "$_n" ]; do
        [ -z "$(holders)" ] && { echo "  [$DEV 已空闲，第 ${i}s]"; return 0; }
        i=$((i + 1)); sleep 1
    done
    echo "  [WARN] 等了 ${_n}s 仍有进程占用："; holders
    return 1
}

do_take() {
    echo "== 1) 优雅停掉 $SVC（服务会自己释放 V4L2 流）=="
    systemctl stop "$SVC" 2>&1 || true
    echo "== 2) 等 $DEV 空闲 =="
    wait_free "${1:-20}" || return 1
    echo "== 3) 自检：能否只读拿到格式（不取流）=="
    timeout 8 v4l2-ctl -d "$DEV" --get-fmt-video 2>&1 | sed -n '1,5p'
    echo
    echo "可以开流了。**务必**用自 poll 工具（超时自己退出，不需要外部 kill）："
    echo "  python3 tools/v4l2_poll_snap.py -d $DEV --out /tmp/f.raw --png /tmp/f.png --report"
    echo "用完记得：sudo bash tools/afh03_video22_lock.sh release"
    return 0
}

do_release() {
    echo "== 把 $SVC 拉回来 =="
    systemctl start "$SVC" 2>&1 || true
    sleep 3
    systemctl is-active "$SVC" 2>&1
    do_status
}

case "${1:-status}" in
    status)  do_status ;;
    take)    do_take "${2:-20}" ;;
    release) do_release ;;
    with)
        shift
        [ "$1" = "--" ] && shift
        [ $# -eq 0 ] && { echo "用法: $0 with -- <命令>"; exit 2; }
        do_take 20 || exit 3
        rc=0
        "$@" || rc=$?
        do_release
        exit $rc
        ;;
    *) echo "用法: $0 status|take [秒]|release|with -- <命令>"; exit 2 ;;
esac
