#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtb_inspect.py —— 只读解析 DTB 与 Rockchip/Android boot.img（纯标准库）。

用途（DSI 7寸/10寸 面板排查）：
  1) 直接读出一个 .dtb 里面 `/panel@0`（或任意节点）的 **hactive/vactive/clock-frequency**，
     从而判定"这份 DTB 配的是哪块屏"，不用上板；
  2) 解析 boot.img（ANDROID! 头），并把里面所有 FDT 魔数 `d00dfeed` 的位置找出来、
     逐个解析，判断 DTB 是不是被打包在 boot.img 里；
  3) 打印分区/命令行等线索，判断"换 DTB"是替换文件还是必须重刷 boot 分区。

用法：
    python3 dtb_inspect.py <file.dtb|boot.img> [--node panel]
    python3 dtb_inspect.py boot.img --scan-only
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9

def parse_fdt(blob: bytes, verbose: bool = False) -> list:
    """返回 [(path, props_dict, name)]。props 值保留原始 bytes + 尽量转成 str/int。"""
    if len(blob) < 40 or struct.unpack_from(">I", blob, 0)[0] != FDT_MAGIC:
        raise ValueError("不是 FDT（魔数不对）")
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version,
     last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", blob, 0)
    strings = blob[off_strings:off_strings + size_strings]
    p = off_struct
    stack = []
    out = []
    while p < off_struct + size_struct:
        tok = struct.unpack_from(">I", blob, p)[0]
        p += 4
        if tok == FDT_BEGIN_NODE:
            end = blob.index(b"\0", p)
            name = blob[p:end].decode("utf-8", "replace")
            p = (end + 4) & ~3
            stack.append(name)
            out.append(("/" + "/".join([s for s in stack if s]), {}, name))
        elif tok == FDT_END_NODE:
            if stack:
                stack.pop()
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack_from(">2I", blob, p)
            p += 8
            val = blob[p:p + ln]
            p = (p + ln + 3) & ~3
            end = strings.index(b"\0", nameoff)
            pname = strings[nameoff:end].decode("utf-8", "replace")
            if out:
                out[-1][1][pname] = val
        elif tok in (FDT_NOP,):
            continue
        elif tok == FDT_END:
            break
        else:
            raise ValueError("结构块出现未知 token 0x%x @ %d" % (tok, p - 4))
    return out

def as_text(b: bytes) -> str:
    return b.rstrip(b"\0").decode("utf-8", "replace")

def as_u32list(b: bytes):
    if len(b) % 4:
        return None
    return list(struct.unpack(">%dI" % (len(b) // 4), b))

def fmt_prop(name: str, b: bytes) -> str:
    if name in ("compatible", "model", "status"):
        return as_text(b)
    if name == "panel-init-sequence":
        return "<%d bytes，%d 条命令>" % (len(b), len(b) // 4)
    if len(b) == 4:
        return "%d (0x%08x)" % (struct.unpack(">I", b)[0], struct.unpack(">I", b)[0])
    if len(b) == 8:
        return " ".join(str(v) for v in struct.unpack(">2I", b))
    if len(b) <= 64:
        try:
            t = as_text(b)
            if all(32 <= ord(c) < 127 or c == "\0" for c in t):
                return repr(t)
        except Exception:                                     
            pass
        return b.hex()
    return "<%d bytes>" % len(b)

def report_dtb(path: str, node_filter: str = "panel", verbose: bool = False) -> dict:
    blob = open(path, "rb").read()
    nodes = parse_fdt(blob)
    print("== DTB: %s  (%d bytes, %d 个节点) ==" % (path, len(blob), len(nodes)))
    info = {}

    for p, pr, _ in nodes:
        if p == "/":
            print("  model      : %s" % fmt_prop("model", pr.get("model", b"")))
            print("  compatible : %s" % fmt_prop("compatible", pr.get("compatible", b"")))
            info["model"] = as_text(pr.get("model", b""))
        if p == "/chosen":
            for k, v in pr.items():
                print("  chosen.%s : %s" % (k, fmt_prop(k, v)[:200]))

    targets = [t for t in nodes if node_filter.lower() in t[2].lower()
               or "timing" in t[2].lower()]
    if not targets:
        targets = [t for t in nodes if any(k in t[1] for k in
                                           ("hactive", "clock-frequency", "dsi,lanes"))]
    for p, pr, nm in targets:
        print("\n  [节点] %s" % p)
        for k in ("compatible", "status", "reg", "backlight", "power-supply",
                  "dsi,lanes", "dsi,format", "dsi,flags", "width-mm", "height-mm",
                  "clock-frequency", "hactive", "vactive", "hfront-porch", "hsync-len",
                  "hback-porch", "vfront-porch", "vsync-len", "vback-porch",
                  "hsync-active", "vsync-active", "de-active", "pixelclk-active",
                  "native-mode", "panel-init-sequence", "reset-delay-ms",
                  "enable-delay-ms", "disable-delay-ms", "max-x", "max-y", "tp-size"):
            if k in pr:
                print("    %-20s %s" % (k, fmt_prop(k, pr[k])))
                info[k] = fmt_prop(k, pr[k])
    if verbose:
        print("\n  --- 全部节点路径 ---")
        for p, _, _ in nodes:
            print("    %s" % p)
    return info

def scan_fdt_offsets(blob: bytes):
    out = []
    i = blob.find(b"\xd0\x0d\xfe\xed")
    while i >= 0:
        try:
            tot = struct.unpack_from(">I", blob, i + 4)[0]
        except struct.error:
            break
        out.append((i, tot))
        i = blob.find(b"\xd0\x0d\xfe\xed", i + 4)
    return out

def parse_boot_img(path: str, scan_only: bool = False) -> None:
    blob = open(path, "rb").read()
    print("== boot.img: %s  (%d bytes) ==" % (path, len(blob)))
    magic = blob[:8]
    print("  魔数        : %s" % magic.decode("latin-1"))
    if magic != b"ANDROID!":
        print("  [注意] 不是标准 ANDROID! 头；按通用方式扫描 FDT")
    else:
        f = struct.unpack_from("<8s10I16s512s32s", blob, 0)
        (_m, ksize, kaddr, rsize, raddr, ssize, saddr, tags, page, hver, osver,
         name, cmdline, _id) = f
        print("  kernel      : size=%d addr=0x%x" % (ksize, kaddr))
        print("  ramdisk     : size=%d addr=0x%x" % (rsize, raddr))
        print("  second(2nd) : size=%d addr=0x%x   <-- Rockchip 常把 DTB/resource 放这里" % (ssize, saddr))
        print("  page_size   : %d   header_version=%d   os_version=0x%x" % (page, hver, osver))
        print("  镜像名      : %s" % name.rstrip(b"\0").decode("utf-8", "replace"))
        print("  cmdline     : %s" % cmdline.rstrip(b"\0").decode("utf-8", "replace"))

        off_k = page
        off_r = off_k + ((ksize + page - 1) // page) * page
        off_s = off_r + ((rsize + page - 1) // page) * page
        print("  段偏移      : kernel@%d ramdisk@%d second@%d" % (off_k, off_r, off_s))
        for nm, off, sz in (("kernel", off_k, ksize), ("ramdisk", off_r, rsize),
                            ("second", off_s, ssize)):
            if sz and off + 8 <= len(blob):
                mg = blob[off:off + 4]
                print("    %-8s 头4字节=%s%s" % (nm, mg.hex(),
                      "  <== 是 FDT(DTB)!" if mg == b"\xd0\x0d\xfe\xed" else ""))
    if scan_only:
        return
    hits = scan_fdt_offsets(blob)
    print("\n  全盘扫描 FDT 魔数 d00dfeed: 命中 %d 处" % len(hits))
    for off, tot in hits[:8]:
        ok = 40 <= tot <= len(blob) - off
        print("    @%-10d totalsize=%-8d %s" % (off, tot, "OK" if ok else "（越界，可能误命中）"))

    for off, tot in hits:
        if 40 <= tot <= len(blob) - off:
            print("\n  解析第一个有效 FDT @%d（大小 %d）:" % (off, tot))
            try:
                nodes = parse_fdt(blob[off:off + tot])
                for p, pr, nm in nodes:
                    if p == "/":
                        print("    model      : %s" % fmt_prop("model", pr.get("model", b"")))
                        print("    compatible : %s" % fmt_prop("compatible", pr.get("compatible", b"")))
                    if "panel" in nm.lower() or any(k in pr for k in ("hactive",)):
                        print("    [节点] %s" % p)
                        for k in ("compatible", "clock-frequency", "hactive", "vactive",
                                  "hfront-porch", "hsync-len", "hback-porch", "vfront-porch",
                                  "vsync-len", "vback-porch", "dsi,lanes", "max-x", "max-y"):
                            if k in pr:
                                print("      %-18s %s" % (k, fmt_prop(k, pr[k])))
            except Exception as e:                            
                print("    解析失败: %s" % e)
            break

def main() -> int:
    ap = argparse.ArgumentParser(description="只读解析 DTB / boot.img")
    ap.add_argument("file")
    ap.add_argument("--node", default="panel", help="要打印的节点名关键字（默认 panel）")
    ap.add_argument("--scan-only", action="store_true", help="boot.img 只扫不解析")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args()
    if not os.path.isfile(a.file):
        print("找不到文件: %s" % a.file)
        return 1
    head = open(a.file, "rb").read(8)
    if head == b"ANDROID!" or a.file.lower().endswith(".img"):
        parse_boot_img(a.file, a.scan_only)
    else:
        try:
            report_dtb(a.file, a.node, a.verbose)
        except Exception as e:                                
            print("解析 DTB 失败: %s" % e)
            return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
