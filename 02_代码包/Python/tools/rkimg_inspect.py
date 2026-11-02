#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rkimg_inspect.py —— 只读检查 Rockchip 整镜像/分区镜像里配的是哪块屏（内存安全）。

为什么需要
----------
`boot.img` 是 U-Boot FIT，DTB 在里面；而厂家还给了 4.78 GB 的整镜像
（`mlk-AFC03-debian-v1.2.x.img`）。要判断"刷这个整镜像能不能修好黑屏"，就得知道
**整镜像里 boot 分区那份 DTB 是 7 寸还是 10 寸**。整镜像太大，不能整个读进内存，
所以本工具用 **seek 分段读**：① 解析 MBR/GPT → 列出分区；
② 找名字像 boot/uboot/resource 的分区；③ 只读该分区头部，找 U-Boot FIT / DTB；
④ 解析 `panel@0` 的 hactive/vactive/clock-frequency。

用法
----
    python3 rkimg_inspect.py <img>                 # 列分区 + 自动找 DTB 并报面板配置
    python3 rkimg_inspect.py <img> --parts-only    # 只看分区表
    python3 rkimg_inspect.py <img> --part boot     # 指定分区名（子串匹配）
"""

from __future__ import annotations

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dtb_inspect as di                                          

FDT_MAGIC = b"\xd0\x0d\xfe\xed"

def read_at(f, off: int, size: int) -> bytes:
    f.seek(off)
    return f.read(size)

def parse_gpt(f) -> list:
    """返回 [(name, start_lba, n_lba, type_guid)]。"""
    hdr = read_at(f, 512, 512)
    if hdr[:8] != b"EFI PART":
        return []
    (sig, rev, hsz, crc, _r, my_lba, alt_lba, first_use, last_use, _guid,
     pt_lba, n_entries, ent_sz, _pcrc) = struct.unpack_from("<8sIIIIQQQQ16sQIII", hdr, 0)
    out = []
    raw = read_at(f, pt_lba * 512, n_entries * ent_sz)
    for i in range(n_entries):
        e = raw[i * ent_sz:(i + 1) * ent_sz]
        if len(e) < ent_sz or e[:16] == b"\0" * 16:
            continue
        tguid = e[:16]
        first, last, _attr = struct.unpack_from("<QQQ", e, 16)
        name = e[56:128].decode("utf-16-le", "replace").rstrip("\0")
        out.append((name, first, last - first + 1, tguid.hex()))
    return out

def find_dtb_in_region(f, base: int, limit: int, scan: int = 8 << 20) -> dict:
    """在 [base, base+scan) 里找 FDT；若是 FIT，再顺着 /images/fdt 的 data-position 取真 DTB。"""
    blob = read_at(f, base, min(scan, limit))
    i = blob.find(FDT_MAGIC)
    if i < 0:
        return {}
    try:
        nodes = di.parse_fdt(blob[i:i + 1_000_000])
    except Exception as e:                                        
        return {"error": str(e)}
    root = next((p for p, _, _ in nodes if p == "/"), None)
    props = dict(nodes[0][1]) if nodes else {}
    desc = ""
    for p, pr, _ in nodes:
        if p == "/":
            desc = di.fmt_prop("description", pr.get("description", b""))

    fdt_off = fdt_sz = None
    for p, pr, _ in nodes:
        if p.endswith("/images/fdt"):
            fdt_off = struct.unpack(">I", pr["data-position"])[0] if "data-position" in pr else None
            fdt_sz = struct.unpack(">I", pr["data-size"])[0] if "data-size" in pr else None
    res = {"fdt_at": base + i, "description": desc, "fit_fdt_off": fdt_off, "fit_fdt_size": fdt_sz}
    if fdt_off:
        probe = read_at(f, base + fdt_off, min(fdt_sz or 400000, 400000))
        if probe[:4] == FDT_MAGIC:
            res["panel"] = panel_of(probe)
            res["dtb_abs_off"] = base + fdt_off
    if "panel" not in res:

        res["panel"] = panel_of(blob[i:])
    return res

def panel_of(blob: bytes) -> dict:
    nodes = di.parse_fdt(blob)
    out = {}
    for p, pr, nm in nodes:
        if p == "/":
            out["model"] = di.fmt_prop("model", pr.get("model", b""))
        if any(k in pr for k in ("hactive",)):
            out["timing"] = "%s x %s @ %s" % (
                di.fmt_prop("hactive", pr["hactive"]),
                di.fmt_prop("vactive", pr["vactive"]),
                di.fmt_prop("clock-frequency", pr.get("clock-frequency", b"")))
        if "panel@" in nm and "panel-init-sequence" in pr:
            out["init"] = "%d B / %d 条" % (len(pr["panel-init-sequence"]),
                                            len(pr["panel-init-sequence"]) // 4)
        if (pr.get("compatible", b"") == b"goodix,gt9xx"):
            out["touch"] = "max %s x %s" % (di.fmt_prop("max-x", pr.get("max-x", b"")),
                                            di.fmt_prop("max-y", pr.get("max-y", b"")))
    return out

def parse_rkfw(f) -> dict:
    """解析 RKFW 头（update.img）。返回 boot_offset/size、fw_offset/size。"""
    h = read_at(f, 0, 64)
    if h[:4] != b"RKFW":
        return {}
    tags = {0x00: "magic"}
    hdr_size = struct.unpack_from("<H", h, 4)[0]
    ver = struct.unpack_from("<H", h, 6)[0]

    

    boot_off = struct.unpack_from("<I", h, 0x14)[0]
    boot_size = struct.unpack_from("<I", h, 0x18)[0]
    fw_off = struct.unpack_from("<I", h, 0x1C)[0]
    fw_size = struct.unpack_from("<I", h, 0x20)[0]
    return {"header_size": hdr_size, "version": ver,
            "boot_offset": boot_off, "boot_size": boot_size,
            "fw_offset": fw_off, "fw_size": fw_size}

def parse_rkaf(f, base: int) -> list:
    """解析 RKAF 分区目录：返回 [(name, pos, size)]（pos 相对 base）。"""
    head = read_at(f, base, 0x60)
    if head[:4] != b"RKAF":
        return []
    num = struct.unpack_from("<I", head, 0x5C)[0]
    if not (0 < num < 64):
        return []
    man = head[0x08:0x2A].split(b"\0")[0].decode("latin-1", "replace")
    model = head[0x2A:0x4C].split(b"\0")[0].decode("latin-1", "replace")
    print("    RKAF: manufacturer=%r model=%r num_parts=%d" % (man, model, num))

    for stride in (0x90, 0x98, 0xA0, 0x200):
        raw = read_at(f, base + 0x60, num * stride)
        if len(raw) < num * stride:
            continue
        parts = []
        ok = True
        for i in range(num):
            e = raw[i * stride:(i + 1) * stride]
            name = e[0:32].split(b"\0")[0]
            fn = e[32:92].split(b"\0")[0]
            if not name or any((c < 32 or c > 126) for c in name):
                ok = False
                break
            nand, pos, naddr, padded = struct.unpack_from("<4I", e, 92)
            size = struct.unpack_from("<I", e, 112)[0] if stride >= 0x90 else padded
            parts.append((name.decode("latin-1"), pos, size, padded))
        if ok and parts:
            print("    PART 结构长度 = 0x%X" % stride)
            return parts
    return []

def report_rkfw(f, size: int) -> None:
    info = parse_rkfw(f)
    print("  RKFW 头: header_size=%d version=%d" % (info.get("header_size", -1), info.get("version", -1)))
    bo, bs = info.get("boot_offset", 0), info.get("boot_size", 0)
    fo, fs = info.get("fw_offset", 0), info.get("fw_size", 0)
    print("  boot_offset=%d size=%d (%.1f MB)   fw_offset=%d size=%d (%.1f MB)"
          % (bo, bs, bs / 1e6, fo, fs, fs / 1e6))
    if bo and bo < size:
        magic = read_at(f, bo, 4)
        print("  boot 区头 4 字节: %s  (FDT=%s / ANDROID!=%s)"
              % (magic.hex(), magic == FDT_MAGIC, magic == b"ANDROID!"[:4] and True))
    if fo and fo < size:
        parts = parse_rkaf(f, fo)
        for nm, pos, sz, padded in parts:
            print("    %-16s pos=%-12d size=%-12d padded=%d" % (nm, pos, sz, padded))
        cand = [(nm, pos, sz) for nm, pos, sz, _p in parts
                if any(k in nm.lower() for k in ("boot", "uboot", "resource", "recovery"))]
        if not cand:
            cand = [(nm, pos, sz) for nm, pos, sz, _p in parts]
        print("\n  在候选分区里找 DTB/FIT:")
        for nm, pos, sz in cand:
            base = fo + pos
            r = find_dtb_in_region(f, base, sz)
            if not r or "error" in r:
                print("    %-16s @%d  %s" % (nm, base, r or "没有 FDT"))
                continue
            p = r.get("panel", {})
            print("    %-16s @%d  FIT描述=%r fdt@+%s size=%s" %
                  (nm, base, r.get("description", ""), r.get("fit_fdt_off"), r.get("fit_fdt_size")))
            print("        面板: %s | init %s | touch %s | model=%s"
                  % (p.get("timing", "-"), p.get("init", "-"), p.get("touch", "-"),
                     p.get("model", "-")))

def main() -> int:
    ap = argparse.ArgumentParser(description="只读检查 Rockchip 整镜像里的面板配置")
    ap.add_argument("img")
    ap.add_argument("--parts-only", action="store_true")
    ap.add_argument("--part", default="", help="指定分区名（子串匹配，如 boot/uboot/resource）")
    ap.add_argument("--all-parts", action="store_true", help="在所有分区里找 DTB")
    a = ap.parse_args()

    if not os.path.isfile(a.img):
        print("找不到文件: %s" % a.img)
        return 1
    size = os.path.getsize(a.img)
    print("镜像: %s  (%.3f GB)" % (a.img, size / 1e9))
    with open(a.img, "rb") as f:
        head = read_at(f, 0, 64)
        print("  头 8 字节: %s (%s)" % (head[:8].hex(),
                                       head[:4].decode("latin-1", "replace")))
        if head[:4] == b"RKFW":
            report_rkfw(f, size)
            return 0
        print("  是不是 FDT(boot.img): %s" % (head[:4] == FDT_MAGIC))
        parts = parse_gpt(f)
        if not parts:
            print("  [注意] 既不是 RKFW 也不是 GPT（可能是裸 FIT 或未打包镜像）")
            if not a.parts_only:
                r = find_dtb_in_region(f, 0, size)
                print("  首 8 MB 里: %s" % r)
            return 0
        print("\n  分区数: %d" % len(parts))
        print("  %-16s %12s %12s %10s" % ("名字", "起始扇区", "扇区数", "大小"))
        for nm, start, n, _t in parts:
            print("  %-16s %12d %12d %8.1f MB" % (nm or "(无名)", start, n, n * 512 / 1e6))
        if a.parts_only:
            return 0
        cand = []
        for nm, start, n, _t in parts:
            low = nm.lower()
            if a.part:
                if a.part.lower() in low:
                    cand.append((nm, start, n))
            elif a.all_parts:
                cand.append((nm, start, n))
            elif any(k in low for k in ("boot", "uboot", "resource", "recovery", "misc")):
                cand.append((nm, start, n))
        print("\n  在候选分区里找 DTB/FIT:")
        for nm, start, n in cand:
            base = start * 512
            limit = n * 512
            r = find_dtb_in_region(f, base, limit)
            if not r or "error" in r:
                print("    %-16s @%d  %s" % (nm, base, r or "没有 FDT"))
                continue
            print("    %-16s @%d  FIT描述=%r  fdt@+%s size=%s" %
                  (nm, base, r.get("description", ""), r.get("fit_fdt_off"), r.get("fit_fdt_size")))
            p = r.get("panel", {})
            print("        面板: %s | init %s | touch %s | model=%s"
                  % (p.get("timing", "-"), p.get("init", "-"), p.get("touch", "-"),
                     p.get("model", "-")))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
