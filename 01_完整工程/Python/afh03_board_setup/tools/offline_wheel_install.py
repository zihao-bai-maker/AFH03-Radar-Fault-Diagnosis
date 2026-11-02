#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
offline_wheel_install.py —— 不依赖 pip / 不联网的 wheel 离线安装器

为什么需要它
------------
AFH03 出厂 Debian 12 镜像里**没有 pip、也没有 ensurepip**（实测：
`python3 -m pip --version` -> No module named pip；`python3 -m ensurepip` -> No module named ensurepip；
apt 包列表为空且板子无网络），而新版 `get-pip.py` 已经改成"去 PyPI 下载 pip"，
在离线板子上必然失败。因此本脚本把一个 `.whl`（本质是 zip）**直接铺进 site-packages**，
只用到 Python 标准库（zipfile/sysconfig），任何 Python 3 都能跑。

它按 PEP 427 的规则落盘：
  * `<dist>.data/purelib/...`  -> purelib（dist-packages）
  * `<dist>.data/platlib/...`  -> platlib（Linux 上与 purelib 同目录）
  * `<dist>.data/scripts/...`  -> scripts（/usr/local/bin，自动 +x）
  * `<dist>.data/data/...`     -> data 前缀（/usr/local）
  * `<dist>.data/headers/...`  -> include 前缀
  * 其它所有条目               -> purelib，
并保留 zip 里的可执行位（external_attr），写完打印 `<dist>.dist-info/RECORD` 的条目数做交叉核对。

用法
----
    # 看一个 wheel 里有什么（不落盘）
    python3 offline_wheel_install.py --list numpy-2.2.6-cp311-...whl

    # 装（默认装进系统 dist-packages；无 pip 的板子上就是这条）
    sudo python3 offline_wheel_install.py --site /usr/local/lib/python3.11/dist-packages \
            whl/numpy-2.2.6-...whl whl/opencv_python-5.0.0.93-...whl

    # 装完立刻自检 import
    python3 offline_wheel_install.py --verify numpy,cv2,rknnlite,rknnlite.api

退出码：0 OK / 1 参数错 / 2 落盘失败 / 3 verify 失败
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import sysconfig
import zipfile

def default_site() -> str:
    """系统 site-packages：优先 /usr/local/lib/pythonX.Y/dist-packages（Debian 上 pip 的落点）。"""
    cand = "/usr/local/lib/python%d.%d/dist-packages" % sys.version_info[:2]
    if os.path.isdir(cand):
        return cand
    return sysconfig.get_paths()["purelib"]

def prefix_map() -> dict:
    """PEP 427 的 .data 子目录 -> 实际落盘目录。"""
    paths = sysconfig.get_paths()
    pure = paths.get("purelib", default_site())
    return {
        "purelib": pure,
        "platlib": paths.get("platlib", pure),
        "scripts": paths.get("scripts", "/usr/local/bin"),
        "data": paths.get("data", "/usr/local"),
        "headers": paths.get("include", "/usr/local/include"),
    }

def wheel_dist_name(zf: zipfile.ZipFile) -> str:
    for n in zf.namelist():
        if n.endswith(".dist-info/WHEEL") and "/" in n:
            return n.split("/")[0]
    for n in zf.namelist():
        if ".dist-info/" in n:
            return n.split("/")[0]
    return "<unknown>"

def wheel_meta(zf: zipfile.ZipFile) -> dict:
    dist = wheel_dist_name(zf)
    info = {"dist_info": dist}
    base = zipfile.Path(zf, dist + "/") if hasattr(zipfile, "Path") else None
    for fn in ("METADATA", "WHEEL", "top_level.txt"):
        try:
            info[fn] = zf.read("%s/%s" % (dist, fn)).decode("utf-8", "replace")
        except KeyError:
            info[fn] = ""
    if base is not None:  
        pass

    meta = info["METADATA"]
    for key in ("Name", "Version", "Requires-Python"):
        val = ""
        for line in meta.splitlines():
            if line.startswith(key + ":"):
                val = line.split(":", 1)[1].strip()
                break
        info[key] = val
    info["Requires-Dist"] = [
        l.split(":", 1)[1].strip()
        for l in meta.splitlines()
        if l.startswith("Requires-Dist:")
    ]
    return info

def data_prefix(zf: zipfile.ZipFile) -> str:
    """返回 `<name>.data/` 前缀（若有）。"""
    dist = wheel_dist_name(zf)

    base = dist[: -len(".dist-info")] if dist.endswith(".dist-info") else dist
    for n in zf.namelist():
        if n.startswith(base + ".data/"):
            return base + ".data/"
    return ""

def install_wheel(path: str, site: str, verbose: bool = True) -> int:
    if not zipfile.is_zipfile(path):
        print("  [ERR] 不是合法 wheel/zip: %s" % path)
        return 0
    zf = zipfile.ZipFile(path)
    info = wheel_meta(zf)
    dpre = data_prefix(zf)
    pmap = prefix_map()
    n_file = 0
    n_skip = 0
    rec = None
    try:
        rec = zf.read("%s/RECORD" % info["dist_info"]).decode("utf-8", "replace").splitlines()
    except KeyError:
        pass

    for m in zf.infolist():
        name = m.filename
        if name.endswith("/"):
            continue
        if dpre and name.startswith(dpre):
            rel = name[len(dpre):]
            sub = rel.split("/", 1)[0]
            rest = rel.split("/", 1)[1] if "/" in rel else ""
            tgt = pmap.get(sub)
            if tgt is None or not rest:

                tgt = pmap["data"]
                rest = rel
        else:
            tgt = site
            rest = name
        dest = os.path.join(tgt, rest)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zf.open(m) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        mode = (m.external_attr >> 16) & 0o7777
        if mode:
            try:
                os.chmod(dest, mode)
            except OSError:
                pass
        n_file += 1
    zf.close()
    if verbose:
        print("  [OK]  %-52s %-10s files=%-5d record=%s"
              % (os.path.basename(path), info.get("Version", "?"), n_file,
                 len(rec) if rec else "无"))
        if info["Requires-Dist"]:
            print("         Requires-Dist: %s" % ", ".join(info["Requires-Dist"]))
    return n_file

def do_list(path: str) -> int:
    if not zipfile.is_zipfile(path):
        print("不是合法 zip: %s" % path)
        return 1
    zf = zipfile.ZipFile(path)
    info = wheel_meta(zf)
    print("文件      : %s" % os.path.basename(path))
    print("  大小    : %d bytes" % os.path.getsize(path))
    print("  Name    : %s" % info.get("Name"))
    print("  Version : %s" % info.get("Version"))
    print("  Requires-Python: %s" % info.get("Requires-Python"))
    print("  Requires-Dist  : %s" % (", ".join(info["Requires-Dist"]) or "无"))
    print("  dist-info      : %s" % info["dist_info"])
    dpre = data_prefix(zf)
    print("  .data 目录     : %s" % (dpre or "无"))
    tl = info.get("top_level.txt", "").strip()
    if tl:
        print("  top_level      : %s" % ", ".join(tl.split()))

    tops = {}
    for m in zf.infolist():
        if m.filename.endswith("/"):
            continue
        t = m.filename.split("/")[0]
        tops[t] = tops.get(t, 0) + 1
    print("  顶层条目       : %s" % ", ".join("%s(%d)" % kv for kv in sorted(tops.items())))
    zf.close()
    return 0

def do_verify(mods: str) -> int:
    bad = 0
    for m in [x.strip() for x in mods.split(",") if x.strip()]:
        try:
            mod = __import__(m)
            print("  [OK]   %-20s %s" % (m, getattr(mod, "__version__", "?")))
        except Exception as e:  
            print("  [FAIL] %-20s %s" % (m, e))
            bad += 1
    return 3 if bad else 0

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="离线安装 wheel（无需 pip / 无需网络）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("wheels", nargs="*", help=".whl 文件（可多个，按给定顺序安装）")
    ap.add_argument("--site", default=None, help="目标 site-packages（默认 %s）" % default_site())
    ap.add_argument("--list", action="store_true", help="只打印每个 wheel 的元数据，不落盘")
    ap.add_argument("--verify", default=None, help="装完 import 这些模块（逗号分隔）做自检")
    ap.add_argument("-q", "--quiet", action="store_true")
    a = ap.parse_args(argv)

    if a.list:
        rc = 0
        for w in a.wheels:
            rc |= do_list(w)
        return rc

    if not a.wheels:
        ap.print_help()
        return 1

    site = a.site or default_site()
    print("目标 site-packages: %s" % site)
    try:
        os.makedirs(site, exist_ok=True)
    except OSError as e:
        print("  [ERR] 无法创建 %s: %s（需要 root？）" % (site, e))
        return 2

    total = 0
    for w in a.wheels:
        if not os.path.isfile(w):
            print("  [ERR] 找不到 %s" % w)
            return 2
        try:
            total += install_wheel(w, site, verbose=not a.quiet)
        except Exception as e:  
            print("  [ERR] 安装 %s 失败: %s" % (w, e))
            return 2
    print("共落盘 %d 个文件 -> %s" % (total, site))

    if a.verify:
        rc = do_verify(a.verify)
        if rc != 0:
            return rc
    return 0

if __name__ == "__main__":
    sys.exit(main())
