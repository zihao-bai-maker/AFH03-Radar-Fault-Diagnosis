"""FPGA(PH1A90) 状态回读 —— 首行视频嵌入字（主路线）+ PCIe BAR（备路线）。

背景（与 `项目_FPGA侧设计.md` 的接口约定一致）
--------------------------------------------------
当前 AFH03 工程里 RK3576 与 PH1A90 之间**只有 MIPI CSI3 差分线**，没有任何寄存器总线
（`RK3576J_PH1A90SEG324_MIPI交互管脚定义表.xlsx` 只列了 4 lane + 1 clk）。所以 FPGA 侧
把 8 个 ROI 的判亮结果**塞进 CSI-2 首行的前若干个 32bit 字**，SoC 侧读一帧的原始 YUYV
字节即可解出。魔数：`0xA5C35A00`（寄存器里的 ID/VER 是 `0xA5C30001`）。

FPGA 侧字地址表（`项目_FPGA侧设计.md` §3.2，字节地址 = 字地址 x 4）：
    0x00+6n+0  ROI_n.X0Y0      R/W  {y0[27:16], x0[11:0]}
    0x00+6n+1  ROI_n.X1Y1      R/W  {y1[27:16], x1[11:0]}   半开区间
    0x00+6n+2/3/4  ROI_n.R/G/B_THR   R/W  该通道累加和阈值
    0x00+6n+5  ROI_n.MODE      R/W  bit4 极性, bit3 AND/OR, bit2 用B, bit1 用G, bit0 用R
    0x30+6n+0/1/2  ROI_n.R/G/B_SUM   R  本帧累加和
    0x30+6n+3  ROI_n.PIX_CNT   R   命中像素数（自检：应等于窗口面积）
    0x30+6n+4  ROI_n.MAX_RGB   R   {8'h0,R,G,B}
    0x30+6n+5  ROI_n.LIT       R   {level[31:24], lit[8]}
    0x60  ID/VER   R   0xA5C30001
    0x61  FRAME_CNT R
    0x62  STATUS   R   {frame_cnt[7:0], n_lit[7:0], ready, any_lit}
    0x63  CTRL     R/W bit0 冻结统计, bit1 清零

嵌入块的具体排布 FPGA 文档写的是"首行前 16 个字"，16 个字装不下 8x6 的完整寄存器，
所以本模块**同时支持两种布局**并在返回结果里带上原始字。

上板核对怎么抓帧（**安全顺序，务必照做**）
----------------------------------------
1. **首选（零设备风险）**：让别人/别的工具抓好原始 YUYV，再解文件：
       python3 -m soc_vision.fpga_status --file /tmp/f.raw
2. **次选（自 poll，超时自己退出，不需要外部 kill）**：
       python3 tools/v4l2_poll_snap.py -d /dev/video22 --out /tmp/f.raw --report
       python3 -m soc_vision.fpga_status --file /tmp/f.raw
3. `--dump-dev DEV` 现在**默认也走上面的自 poll 抓帧**（`--timeout-ms` 默认 3000）；抓不到就
   干净退出（返回码 3），**不会卡死板子**。
   ⚠️ `--allow-blocking-dump` 是**高危逃生门**：它调用 `v4l2-ctl`，而 v4l2-ctl **没有内部超时**
   ——无帧时会永久阻塞，被外部 timeout/SIGKILL 杀掉会让 CSI 收尾不干净、**把 SoC 拖到卡死/复位**
   （现场已复现多次）。**只在"已确认会出帧"且外部已套 `timeout` 时使用**。
"""

from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

MAGIC_EMBED = 0xA5C35A00
ID_VER_EXPECT = 0xA5C30001

LAYOUT_CONDENSED = "condensed"
LAYOUT_REGISTER = "register"

MAX_ROI = 8

def words_from_bytes(raw: bytes, endian: str = "<", limit_words: int = 256) -> List[int]:
    """把字节流按 32bit 字切出来。endian: '<' 小端 / '>' 大端。"""
    n = min(limit_words, len(raw) // 4)
    if n <= 0:
        return []
    return list(struct.unpack_from(endian + "%dI" % n, raw, 0))

def find_magic(raw: bytes, magic: int = MAGIC_EMBED,
               search_words: int = 128) -> Tuple[int, str]:
    """在字节流开头找魔数。返回 (字下标, endian)；找不到返回 (-1, '<')。

    两种字节序都试 —— MIPI 线上的 32bit 字节序 FPGA 侧还没最终确认（文档 §7 R6）。
    """
    for endian in ("<", ">"):
        ws = words_from_bytes(raw, endian, search_words)
        for i, w in enumerate(ws):
            if w == magic:
                return i, endian
    return -1, "<"

@dataclass
class FpgaRoi:
    n: int
    r_sum: int = 0
    g_sum: int = 0
    b_sum: int = 0
    pix_cnt: int = 0
    max_rgb: int = 0
    lit_level: int = 0
    lit: bool = False

    @property
    def max_r(self) -> int: return (self.max_rgb >> 16) & 0xFF

    @property
    def max_g(self) -> int: return (self.max_rgb >> 8) & 0xFF

    @property
    def max_b(self) -> int: return self.max_rgb & 0xFF

    def to_dict(self) -> Dict[str, Any]:
        return {"n": self.n, "lit": self.lit, "lit_level": self.lit_level,
                "r_sum": self.r_sum, "g_sum": self.g_sum, "b_sum": self.b_sum,
                "pix_cnt": self.pix_cnt,
                "max_rgb": [self.max_r, self.max_g, self.max_b]}

@dataclass
class FpgaStatus:
    present: bool = False
    magic_index: int = -1
    endian: str = "<"
    layout: str = ""
    id_ver: int = 0
    frame_cnt: int = 0
    status_word: int = 0
    ready: bool = False
    any_lit: bool = False
    n_lit: int = 0
    ctrl: int = 0
    rois: List[FpgaRoi] = field(default_factory=list)
    raw_words: List[int] = field(default_factory=list)
    note: str = ""

    def lit_bits(self, n: int = MAX_ROI) -> List[bool]:
        """返回 n 个 ROI 的亮/灭（缺失的补 False，顺序即 ROI 编号）。"""
        out = [False] * n
        for r in self.rois:
            if 0 <= r.n < n:
                out[r.n] = r.lit
        return out

    def to_dict(self) -> Dict[str, Any]:
        return {
            "present": self.present, "layout": self.layout,
            "magic_index": self.magic_index, "endian": self.endian,
            "id_ver": "0x%08X" % self.id_ver, "frame_cnt": self.frame_cnt,
            "ready": self.ready, "any_lit": self.any_lit, "n_lit": self.n_lit,
            "lit_bits": self.lit_bits(), "rois": [r.to_dict() for r in self.rois],
            "note": self.note,
        }

def _popcount8(v: int) -> int:
    return bin(v & 0xFF).count("1")

def decode_words(words: Sequence[int], magic_index: int = 0,
                 layout: str = "auto") -> FpgaStatus:
    """把魔数之后的字解释成 FpgaStatus。

    layout: "condensed" / "register" / "auto"
    auto 的判定：先按 condensed 解，如果 (a) STATUS.n_lit 与 LIT 位数一致、
    (b) frame_cnt 合理，则接受；否则按 register 解。
    """
    st = FpgaStatus(present=False, magic_index=magic_index,
                    raw_words=list(words[:64]))
    if magic_index < 0 or magic_index >= len(words):
        st.note = "未找到魔数 0x%08X" % MAGIC_EMBED
        return st
    w = words[magic_index:]
    st.present = True

    def try_condensed() -> bool:
        if len(w) < 3:
            return False
        frame = w[1] & 0xFFFFFFFF
        status = w[2]
        n_lit = (status >> 8) & 0xFF
        lit_mask = 0
        rois: List[FpgaRoi] = []
        for n in range(MAX_ROI):
            if 3 + n >= len(w):
                break
            litw = w[3 + n]
            lit = bool(litw & 0xFF)
            rois.append(FpgaRoi(n=n, lit=lit, lit_level=(litw >> 24) & 0xFF))
            lit_mask = (lit_mask << 1) | (1 if lit else 0)
        if not rois:
            return False

        if _popcount8(lit_mask) != n_lit:
            return False
        st.layout = LAYOUT_CONDENSED
        st.frame_cnt = frame
        st.status_word = status
        st.ready = bool((status >> 16) & 1)
        st.any_lit = bool((status >> 17) & 1)
        st.n_lit = n_lit
        st.rois = rois
        st.note = "按 condensed 布局解出（请在板上复核一次：优先 --file 解已抓好的 raw）"
        return True

    def try_register() -> bool:
        if len(w) < 5:
            return False
        idv, frame, status, ctrl = w[1], w[2], w[3], w[4]
        rois: List[FpgaRoi] = []
        for n in range(MAX_ROI):
            base = 5 + 6 * n
            if base + 5 >= len(w):
                break
            litw = w[base + 5]
            rois.append(FpgaRoi(n=n,
                                r_sum=w[base + 0], g_sum=w[base + 1], b_sum=w[base + 2],
                                pix_cnt=w[base + 3], max_rgb=w[base + 4],
                                lit=bool(litw & 0xFF), lit_level=(litw >> 24) & 0xFF))
        if not rois:
            return False
        st.layout = LAYOUT_REGISTER
        st.id_ver = idv
        st.frame_cnt = frame
        st.status_word = status
        st.ctrl = ctrl
        st.n_lit = (status >> 8) & 0xFF
        st.ready = bool((status >> 16) & 1)
        st.any_lit = bool((status >> 17) & 1)
        st.rois = rois
        st.note = "按 register 布局解出（ID/VER=%s）" % ("0x%08X" % idv)
        return True

    if layout == LAYOUT_CONDENSED:
        ok = try_condensed()
    elif layout == LAYOUT_REGISTER:
        ok = try_register()
    else:
        ok = try_condensed() or try_register()
    if not ok:
        st.present = False
        st.note = "找到魔数但后续字不足以解码（原始字见 raw_words）"
    return st

def scan_raw_yuyv(raw: bytes, magic: int = MAGIC_EMBED,
                  layout: str = "auto") -> FpgaStatus:
    """从一帧原始 YUYV 字节里解出状态块（主路线，推荐）。"""
    idx, endian = find_magic(raw, magic)
    if idx < 0:
        st = FpgaStatus(present=False, note="首 512 字节未找到魔数 0x%08X" % magic)
        st.raw_words = words_from_bytes(raw, "<", 32)
        return st
    words = words_from_bytes(raw, endian, 256)
    st = decode_words(words, idx, layout)
    st.endian = endian
    return st

def scan_bgr_frame(bgr: np.ndarray, layout: str = "auto") -> FpgaStatus:
    """BGR 帧的兜底解码（只有 raw 字节拿不到时才用）。

    原理：把 BGR 的前若干行反推回 YUYV（Y 通道取 (B+G+R)/3 不可逆），
    所以这里只在**首行前 48 像素的灰度与原图灰度差异极小**时意义有限；
    正式做法请用 `scan_raw_yuyv`。本函数仍做完整尝试：把 BGR 前 64 像素的
    B/G/R 拼成 4 字节一组的候选字来找魔数。
    """
    if bgr is None or bgr.size == 0:
        return FpgaStatus(present=False, note="空帧")
    row = bgr[0, :64, :].astype(np.uint32)

    cand = []
    for i in range(0, min(60, row.shape[0] - 1), 2):
        b0, g0, _ = row[i]
        b1, g1, _ = row[i + 1]
        cand.append(int((b0 << 0) | (g0 << 8) | (b1 << 16) | (g1 << 24)))
        cand.append(int((b0 << 24) | (g0 << 16) | (b1 << 8) | (g1 << 0)))
    for i, c in enumerate(cand):
        if c == MAGIC_EMBED:
            st = FpgaStatus(present=True, magic_index=i, raw_words=cand[:64],
                            note="从 BGR 反推（可信度低，建议改用原始 YUYV）")
            return st
    return FpgaStatus(present=False, raw_words=cand[:16],
                      note="BGR 反推未找到魔数（正常：色彩转换会破坏嵌入字）")

def read_bar_words(phys_base: int, word_addrs: Sequence[int],
                   devmem: str = "devmem") -> Dict[int, int]:
    """走 PCIe 时用 devmem 直接读 BAR（备选路线）。

    需要先按 `07_异构方案\\...\\deploy\\pcie_setup.sh` 加载 anlogic_pci 驱动，
    BAR0 物理地址从 /sys/bus/pci/devices/0000:XX:XX.X/resource 读。
    """
    out: Dict[int, int] = {}
    for wa in word_addrs:
        addr = phys_base + (wa * 4)
        try:
            txt = subprocess.check_output([devmem, "0x%X" % addr], text=True,
                                          stderr=subprocess.STDOUT, timeout=3)
            out[int(wa)] = int(txt.strip(), 0)
        except Exception as e:                              
            out[int(wa)] = -1
            sys.stderr.write("devmem 读 0x%X 失败: %s\n" % (addr, e))
    return out

def find_fpga_bar0() -> Optional[int]:
    """找 anlogic FPGA 的 BAR0 物理地址（PCIe 路线）。找不到返回 None。"""
    try:
        import glob
        for res in glob.glob("/sys/bus/pci/devices/*/resource"):
            try:
                with open(res, "r") as f:
                    line = f.readline().split()
                if line and line[0].startswith("0x") and int(line[0], 16) != 0:
                    vend = os.path.join(os.path.dirname(res), "vendor")
                    dev = os.path.join(os.path.dirname(res), "device")
                    v = open(vend).read().strip() if os.path.exists(vend) else ""
                    if v in ("0x1edb",):        
                        return int(line[0], 16)
            except Exception:
                continue
    except Exception:
        pass
    return None

def _safe_grab(dev: str, timeout_ms: int, count: int) -> Optional[bytes]:
    """用 `tools/v4l2_poll_snap.py` 的自 poll 抓帧：超时自己 STREAMOFF+close，**不需要外部 kill**。

    返回原始字节；抓不到（超时/工具不可用）返回 None —— 调用方据此**干净退出**，绝不阻塞。
    """
    import importlib
    tools_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    mod = None
    for name in ("v4l2_poll_snap", "tools.v4l2_poll_snap"):
        try:
            mod = importlib.import_module(name)
            break
        except Exception:                                         
            continue
    if mod is None:
        print("[拒绝] 找不到安全抓帧工具 tools/v4l2_poll_snap.py。")
        print("       请用它抓帧后再解文件：")
        print("         python3 tools/v4l2_poll_snap.py -d %s --out /tmp/f.raw --report" % dev)
        print("         python3 -m soc_vision.fpga_status --file /tmp/f.raw")
        return None
    snap = mod.Snapper(dev, 1920, 1080, "YUYV", 4, False)
    try:
        snap.open()
        snap.set_fmt()
        snap.reqbufs()
        snap.map_all()
        snap.streamon()
        for _ in range(max(1, count)):
            _b, data, _dt = snap.grab(timeout_ms)
            if data is None:
                print("[超时] %d ms 内没有帧 —— 已由工具自己 STREAMOFF+close 干净退出"
                      "（没有任何进程被 kill）" % timeout_ms)
                return None
        return data
    except Exception as e:                                        
        print("[安全抓帧失败] %s" % e)
        return None
    finally:
        snap.close()

def _dump_dev(dev: str, count: int = 1, timeout_ms: int = 3000,
              allow_blocking: bool = False) -> int:
    """抓一帧解出状态块。

    默认：用 `tools/v4l2_poll_snap.py` 的**自 poll** 抓帧（超时自己退出，不会卡死板子）。
    高危模式（`allow_blocking=True`）：退回 `v4l2-ctl`，**无内部超时**，仅在你已确认会出帧
    且外部套了 `timeout` 时使用。
    """
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "afh03_fpga_probe.raw")

    if not allow_blocking:
        print("[安全抓帧] 使用 tools/v4l2_poll_snap.py（自 poll，timeout=%d ms；不会外部 kill）"
              % timeout_ms)
        raw = _safe_grab(dev, timeout_ms, count)
        if raw is None:
            print("提示：也可以用 --file 解一个**别人已经抓好**的原始 YUYV，零设备风险。")
            return 3
        with open(tmp, "wb") as f:
            f.write(raw)
        print("抓到 %d 字节（1080p YUYV 应为 %d）" % (len(raw), 1920 * 1080 * 2))
        return _report(raw)

    print("!!! 高危：--allow-blocking-dump 使用 v4l2-ctl，**它没有内部超时** !!!")
    print("!!! 无帧时会永久阻塞；被 timeout/SIGKILL 杀掉会让 CSI 收尾不干净，")
    print("!!! 现场已多次把 SoC 拖到卡死/复位。**请改用自 poll 工具或 --file**。")
    if not os.environ.get("AFH03_I_KNOW_IT_MAY_HANG"):
        print("[拒绝] 若你确认会出帧且外部已套 timeout，再设置环境变量 "
              "AFH03_I_KNOW_IT_MAY_HANG=1 重试。")
        return 3
    print("    已检测到 AFH03_I_KNOW_IT_MAY_HANG=1，继续（**务必**在外面套 timeout！）")
    cmd = ["v4l2-ctl", "-d", dev,
           "--set-fmt-video=width=1920,height=1080,pixelformat=YUYV",
           "--stream-mmap=4", "--stream-count=%d" % count, "--stream-to=%s" % tmp]
    print("+", " ".join(cmd))
    try:
        subprocess.check_call(cmd)
    except Exception as e:                                        
        print("v4l2-ctl 失败: %s（apt install v4l-utils）" % e)
        return 1
    with open(tmp, "rb") as f:
        raw = f.read()
    print("抓到 %d 字节（1080p YUYV 应为 %d）" % (len(raw), 1920 * 1080 * 2))
    return _report(raw)

def _report(raw: bytes) -> int:
    idx, endian = find_magic(raw)
    print("魔数 0x%08X 位置: 字下标 %d, 字节序 %s" %
          (MAGIC_EMBED, idx, "小端" if endian == "<" else "大端"))
    words = words_from_bytes(raw, endian, 64)
    print("首 32 个字（hex）:")
    for i in range(0, min(32, len(words)), 8):
        print("  [%02d] %s" % (i, " ".join("%08X" % w for w in words[i:i + 8])))
    st = scan_raw_yuyv(raw)
    print()
    print("解码结果: present=%s layout=%s note=%s" % (st.present, st.layout or "-", st.note))
    if st.present:
        print("  FRAME_CNT=%d  STATUS=0x%08X  ready=%s any_lit=%s n_lit=%d"
              % (st.frame_cnt, st.status_word, st.ready, st.any_lit, st.n_lit))
        print("  LIT 位: %s" % st.lit_bits())
        for r in st.rois:
            print("  ROI%d: lit=%s level=%d  R/G/B_SUM=%d/%d/%d PIX=%d MAX=%s"
                  % (r.n, r.lit, r.lit_level, r.r_sum, r.g_sum, r.b_sum,
                     r.pix_cnt, (r.max_r, r.max_g, r.max_b)))
    if idx < 0:
        print("提示：若整帧原始 YUYV 里找不到魔数，说明 FPGA 侧 INJECT_ENABLE 还没打开，"
              "或字节序/位置与约定不同 —— 请把上面 32 个字发给 FPGA 侧核对。")
        return 2
    return 0

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="FPGA 状态块解码/探测")
    ap.add_argument("--file", metavar="RAW",
                    help="【首选，零设备风险】直接解一个已经抓好的 YUYV 原始文件")
    ap.add_argument("--dump-dev", metavar="DEV",
                    help="抓一帧再解，例如 /dev/video22。默认走安全的自 poll 抓帧"
                         "（tools/v4l2_poll_snap.py，超时自己 STREAMOFF+close，不会卡死板子）")
    ap.add_argument("--timeout-ms", type=int, default=3000, help="--dump-dev 的 poll 超时（默认 3000）")
    ap.add_argument("--allow-blocking-dump", action="store_true",
                    help="【高危】退回 v4l2-ctl 抓帧：它没有内部超时，无帧时永久阻塞，"
                         "被 kill 掉会弄脏 CSI 收尾。仅在确认会出帧且外部已套 timeout 时使用，"
                         "且需再设环境变量 AFH03_I_KNOW_IT_MAY_HANG=1")
    ap.add_argument("--bar0", type=lambda s: int(s, 0), help="PCIe 路线：BAR0 物理地址")
    ap.add_argument("--roi-n", type=int, default=MAX_ROI, help="ROI 个数（默认 8）")
    a = ap.parse_args(argv)

    if a.dump_dev:
        return _dump_dev(a.dump_dev, timeout_ms=a.timeout_ms,
                         allow_blocking=a.allow_blocking_dump)
    if a.file:
        with open(a.file, "rb") as f:
            return _report(f.read())
    if a.bar0:
        addrs = [0x60, 0x61, 0x62, 0x63]
        for n in range(a.roi_n):
            addrs += [0x30 + 6 * n + k for k in range(6)]
        res = read_bar_words(a.bar0, addrs)
        for wa in sorted(res):
            print("word 0x%02X = 0x%08X" % (wa, res[wa] & 0xFFFFFFFF))
        return 0
    ap.print_help()
    return 1

if __name__ == "__main__":                                  
    raise SystemExit(main())
