#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查一个 TTF/OTF 的 cmap 是否覆盖指定字符集（纯标准库，不依赖 PIL/fontTools）。

用途：板子离线、PC 没有 PIL 时，先把"要显示的中文"逐字验证字体确实有字形，
避免上板后才发现某些字是豆腐块。
"""
import struct
import sys

def read_cmap(path):
    d = open(path, "rb").read()
    tag = d[:4]
    num_tables = struct.unpack(">H", d[4:6])[0]
    tables = {}
    for i in range(num_tables):
        off = 12 + i * 16
        name = d[off:off + 4].decode("latin-1")
        toff, tlen = struct.unpack(">II", d[off + 8:off + 16])
        tables[name] = (toff, tlen)
    if "cmap" not in tables:
        raise SystemExit("没有 cmap 表（不是 TrueType/OpenType？tag=%r）" % tag)
    co, cl = tables["cmap"]
    n = struct.unpack(">H", d[co + 2:co + 4])[0]
    best = None
    for i in range(n):
        rec = co + 4 + i * 8
        pid, eid, sub = struct.unpack(">HHI", d[rec:rec + 8])
        fmt = struct.unpack(">H", d[co + sub:co + sub + 2])[0]
        if fmt in (4, 12):

            score = (3, 10, 100) if (pid, eid) == (3, 10) else \
                    (3, 1, 80) if (pid, eid) == (3, 1) else (0, eid, 60)
            if best is None or score[2] > best[2]:
                best = (co + sub, fmt, score[2])
    if best is None:
        raise SystemExit("没有可用的 Unicode cmap 子表（只有 format 0/6？）")
    return d, best[0], best[1]

def cmap_lookup(d, off, fmt, cp):
    if fmt == 12:
        ngroups = struct.unpack(">I", d[off + 12:off + 16])[0]
        for g in range(ngroups):
            go = off + 16 + g * 12
            s, e, gid = struct.unpack(">III", d[go:go + 12])
            if s <= cp <= e:
                return gid + (cp - s)
        return 0

    segX2 = struct.unpack(">H", d[off + 6:off + 8])[0]
    seg = segX2 // 2
    ends = struct.unpack(">%dH" % seg, d[off + 14:off + 14 + segX2])
    starts = struct.unpack(">%dH" % seg, d[off + 16 + segX2:off + 16 + segX2 * 2])
    deltas = struct.unpack(">%dh" % seg, d[off + 16 + segX2 * 2:off + 16 + segX2 * 3])
    range_off_base = off + 16 + segX2 * 3
    range_offs = struct.unpack(">%dH" % seg, d[range_off_base:range_off_base + segX2])
    for i in range(seg):
        if cp > ends[i]:
            continue
        if cp < starts[i]:
            return 0
        if range_offs[i] == 0:
            return (cp + deltas[i]) & 0xFFFF
        ro = range_off_base + i * 2 + range_offs[i] + (cp - starts[i]) * 2
        if ro + 2 > len(d):
            return 0
        g = struct.unpack(">H", d[ro:ro + 2])[0]
        return 0 if g == 0 else (g + deltas[i]) & 0xFFFF
    return 0

LABELS = (
    "AFH03 相机画面 帧号 时间 状态行 波形 频率 偏差 峰峰 值 判定 正常 异常 未配置 未标定 拒绝出结果 "
    "示波器 未连接 超时 错误 无信号 端口 不在线 请检查网线 等待 初始化 保存 退出 帮助 "
    "亮 灭 判据 软件 硬件 状态字 魔数 汉字 识别 中文 字体 缺失 英文 标签 代替 "
    "通道 探头 时基 采样率 触发 就绪 幅值 振幅 白名单 容差 数据来源 交叉校验 "
    "模式 阈值 迟滞 去抖 基线 命中率 颜色 红绿蓝 黄 青 紫 图像 亮度 对比度 "
    "左 右 上 下 中 前后 秒 毫秒 微秒 纳秒 千 百 万 十 个 第 共 总计 平均 "
    "使能 禁用 打开 关闭 已 正在 完成 失败 成功 部分 全部 部分完成 待验 已结案 定案 争议 作废 "
    "网口 静态 地址 网关 路由 邻居 扫描 发现 通讯 端口号 协议 波特率 串口 调试 "
    "设备 节点 驱动 内核 版本 固件 位流 下载 烧录 固化 断电 上电 复位 重启 "
)

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path:
        print("用法: python3 font_coverage.py <font.ttf|otf> [额外字符]")
        return 1
    extra = sys.argv[2] if len(sys.argv) > 2 else ""
    chars = sorted(set(LABELS + extra))
    cjk = [c for c in chars if "\u4e00" <= c <= "\u9fff"]
    other = [c for c in chars if c not in cjk and c.strip()]
    d, off, fmt = read_cmap(path)
    print("字体: %s" % path)
    print("  cmap 子表 format=%d 偏移=%d" % (fmt, off))
    miss_cjk = [c for c in cjk if cmap_lookup(d, off, fmt, ord(c)) == 0]
    miss_other = [c for c in other if cmap_lookup(d, off, fmt, ord(c)) == 0]
    print("  汉字: 共 %d 个，缺失 %d 个%s" % (len(cjk), len(miss_cjk),
                                             (" -> " + "".join(miss_cjk)) if miss_cjk else " ✔"))
    print("  其它: 共 %d 个，缺失 %d 个%s" % (len(other), len(miss_other),
                                             (" -> " + "".join(miss_other)) if miss_other else " ✔"))
    return 0 if not miss_cjk else 2

if __name__ == "__main__":
    raise SystemExit(main())
