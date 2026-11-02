# -*- coding: utf-8 -*-
"""
kb_dataset.py —— 从**知识库**生成训练数据（没有现场样本，只能蒸馏，且如实说明）

T1「参数判别」scope
  输入 = 单次示波器测量参数（频率偏差 / vpp / 置信度 / 探头状态 / 是否有基准 / 哨兵标志）
  标签 = **生成时直接调用 rules.judge_item**（单一真值源，不二次反推）
  采样 = 设计网格（刻意打边界 ±5% / 50 mV / 50% 基准 / 置信度 0.6）+ 随机抖动
  意义 = 把确定性规则蒸馏成可给**软概率**的网络，对噪声/缺失更鲁棒

T2「故障定位」locate
  输入 = 一轮 SOP 问答观测（每题 异常掩码 + 已答掩码）+ 汇总特征
  标签 = 该轮指向的**模块**（机柜/分机/模块；只保留"有显式判据"的模块）
  采样 = 从 KB 的 step_fault 反推：选中模块 -> 其判据步按概率判异常 -> 其余正常/未答，
        并注入**操作员误报/漏答**模拟真实噪声
  意义 = 把"权重投票"升级成带概率与排序的模型

⚠ 这是**规则蒸馏**，不是"现场实测学出来的"。它提供的是概率、抗噪、排序；
   不能凭空获得知识库之外的知识。诚实边界写在 GUIDE.md。
"""
import json
import os
import sqlite3
import sys

import numpy as np

def _find_dir(names, markers):
    """在若干候选位置里找包含 marker 文件的目录（兼容包内中文目录名）"""
    base = os.path.dirname(os.path.abspath(__file__))
    cands = []
    for n in names:
        cands += [os.path.join(base, n), os.path.join(base, "..", n),
                  os.path.join(base, "..", "..", n)]
    cands += ["D:\\AFH03\\scope", "D:\\AFH03\\ml"]
    for c in cands:
        try:
            cc = os.path.abspath(c)
        except Exception:
            continue
        for m in markers:
            if os.path.exists(os.path.join(cc, m)):
                return cc
    return None

_R = _find_dir(["scope", "波形检测"], ["rules.py"])
if _R and _R not in sys.path:
    sys.path.insert(0, _R)

import rules as R

SCOPE_INPUTS = [
    "is_freq", "has_expect", "has_meas", "dev_norm", "dev_over", "abs_dev",
    "vpp_log", "vpp_over_50mv", "vpp_missing", "conf_present", "conf", "conf_low",
    "probe_ok", "has_baseline", "amp_norm", "amp_below_50", "all_missing",
]
SCOPE_LABELS = ["正常", "不正常", "未判定"]
LAB2IDX = {R.NORMAL: 0, R.ABNORMAL: 1, R.UNDET: 2}

def feat_scope(mode, expect, meas_hz, vpp, conf, probe_ok, baseline):
    """一条测量 -> 可解释特征向量（17 维）"""
    e = R._num(expect)
    f = R._num(meas_hz)
    v = R._num(vpp)
    b = R._num(baseline)
    c = 1.0 if conf is None else float(conf)
    has_exp = 1.0 if (e is not None and e > 0) else 0.0
    has_meas = 1.0 if f is not None else 0.0
    dev = None
    if has_exp and has_meas:
        dev = abs(f - e) / e * 100.0
    dev_norm = 0.0 if dev is None else min(dev / 20.0, 2.0)
    dev_over = 1.0 if (dev is not None and dev > R.TOL_PCT_DEFAULT) else 0.0
    abs_dev = -1.0 if dev is None else min(dev, 25.0) / 25.0
    vlog = 0.0 if v is None else float(np.log1p(max(v, 0.0) * 1000.0) / 10.0)
    v_over = 0.0 if v is None else (1.0 if v >= R.NOISE_VPP_V else 0.0)
    v_miss = 1.0 if v is None else 0.0
    conf_low = 1.0 if c < R.CONF_MIN else 0.0
    has_base = 1.0 if (b is not None and b > 0) else 0.0
    amp = (v / b * 100.0) if (has_base and v is not None) else None
    amp_norm = 0.0 if amp is None else min(amp / 200.0, 2.0)
    amp_low = 1.0 if (amp is not None and amp < R.AMP_LOW_PCT) else 0.0
    return np.array([
        1.0 if mode == "freq" else 0.0, has_exp, has_meas, dev_norm, dev_over, abs_dev,
        vlog, v_over, v_miss, 1.0, min(c, 1.0), conf_low,
        1.0 if probe_ok else 0.0, has_base, amp_norm, amp_low,
        1.0 if (f is None and v is None) else 0.0,
    ], np.float32)

def gen_scope(n_random=9000, seed=0, items_path=r"D:\AFH03\scope\items_lan.json"):
    """返回 X(17 维) / y(3 类) / kinds（grid|rand）/ meta"""
    rng = np.random.default_rng(seed)
    items = json.load(open(items_path, encoding="utf-8"))["items"]
    X, y, kinds = [], [], []

    def add(item, mode, expect, mhz, vpp, conf, pk, base, kind):

        it2 = dict(item)
        it2["baseline_vpp"] = base
        meas = {"freq_hz": mhz, "vpp_v": vpp, "confidence": 1.0 if conf is None else conf,
                "probe_ok": pk}
        lab = R.judge_item(it2, meas)["verdict"]           
        X.append(feat_scope(mode, expect, mhz, vpp, conf, pk, base))
        y.append(LAB2IDX[lab])
        kinds.append(kind)

    devs = [-30, -10, -5.1, -5.0, -4.9, -3, -1, -0.02, 0.0, 0.02, 1, 3, 4.9, 5.0, 5.1, 10, 30]
    vpps = [None, 0.0, 0.01, 0.049, 0.05, 0.051, 0.1, 0.3, 0.8, 1.2, 2.0]
    bases = [None, 0.5, 1.0, 2.0]
    confs = [None, 0.3, 0.5, 0.59, 0.60, 0.8, 0.99]
    probes = [True, False]

    for it in items:
        if it["judge_mode"] == "freq":
            e = it["expect_freq_hz"]
            for dv in devs:
                f = e * (1 + dv / 100.0)
                for vp in (None, 0.01, 0.6):
                    for c in confs:
                        for pk in probes:
                            add(it, "freq", e, f, vp, c, pk, None, "grid")

            for vp in (None, 0.01, 0.049, 0.051, 0.5):
                for c in (None, 0.59, 0.61):
                    for pk in probes:
                        for sen in ("*****", "9.9E+37"):
                            add(it, "freq", e, sen, vp, c, pk, None, "grid")
        else:
            for vp in vpps:
                for bs in bases:
                    for c in confs:
                        for pk in probes:
                            add(it, "presence", None, None, vp, c, pk, bs, "grid")

    for _ in range(n_random):
        it = items[int(rng.integers(len(items)))]
        c = None if rng.random() < 0.08 else float(rng.uniform(0.2, 1.0))
        pk = bool(rng.random() > 0.15)
        if it["judge_mode"] == "freq":
            e = it["expect_freq_hz"]
            r = rng.random()
            if r < 0.05:
                f = rng.choice(["*****", "9.9E+37", None])
            else:
                f = e * (1 + rng.normal(0, 0.03))
            vp = None if rng.random() < 0.10 else float(abs(rng.normal(0.6, 0.4)))
            add(it, "freq", e, f, vp, c, pk, None, "rand")
        else:
            r = rng.random()
            vp = (None if r < 0.06 else
                  (rng.choice(["*****", "9.9E+37"]) if r < 0.09 else
                   float(abs(rng.normal(0.5, 0.45)))))
            bs = None if rng.random() < 0.70 else float(abs(rng.normal(1.0, 0.3)) + 0.05)
            add(it, "presence", None, None, vp, c, pk, bs, "rand")

    return (np.asarray(X, np.float32), np.asarray(y, np.int64), kinds,
            {"inputs": SCOPE_INPUTS, "labels": SCOPE_LABELS, "n_items": len(items)})

class LocateData:
    def __init__(self, db_path=r"D:\AFH03\diag\afh03_diag.db"):
        self.con = sqlite3.connect(db_path)
        self.con.row_factory = sqlite3.Row
        self.steps = [dict(r) for r in self.con.execute("SELECT * FROM sop_steps ORDER BY id")]
        self.sidx = {s["id"]: i for i, s in enumerate(self.steps)}
        self.faults = [dict(r) for r in self.con.execute("SELECT * FROM faults ORDER BY id")]
        self.fbyid = {f["id"]: f for f in self.faults}
        self.link = {}
        for r in self.con.execute("SELECT step_id,fault_id FROM step_fault"):
            self.link.setdefault(r["step_id"], set()).add(r["fault_id"])
        self.step_modules = {}
        for sid, fids in self.link.items():
            self.step_modules[sid] = {
                (self.fbyid[f]["cabinet"], self.fbyid[f]["unit"], self.fbyid[f]["module"])
                for f in fids if f in self.fbyid}
        self.modules = sorted({m for s in self.step_modules.values() for m in s})
        self.midx = {m: i for i, m in enumerate(self.modules)}
        self.module_steps = {i: [] for i in range(len(self.modules))}
        for sid, mods in self.step_modules.items():
            for m in mods:
                self.module_steps[self.midx[m]].append(self.sidx[sid])
        self.cats = sorted({(s["cat"] or "") for s in self.steps})
        self.cidx = {c: i for i, c in enumerate(self.cats)}

    def stats(self):
        allmods = {(f["cabinet"], f["unit"], f["module"]) for f in self.faults}
        return {"steps": len(self.steps), "faults": len(self.faults),
                "linked_steps": len(self.step_modules),
                "learnable_modules": len(self.modules),
                "all_modules": len(allmods),
                "cabinets": len({f["cabinet"] for f in self.faults}),
                "units": len({(f["cabinet"], f["unit"]) for f in self.faults})}

    def dim(self):
        return len(self.steps) * 2 + len(self.cats) + 4

    def gen(self, n=6000, seed=0, fp_rate=0.05, miss_rate=0.35, augment=False):
        """augment=True：每条样本**随机抽一个漏答/误报水平**（噪声增广），
        让模型对"干净答案~很脏答案"都鲁棒（否则只在训练时那个噪声水平上表现好）。"""
        rng = np.random.default_rng(seed)
        ns, D = len(self.steps), self.dim()
        X = np.zeros((n, D), np.float32)
        y = np.zeros(n, np.int64)
        for k in range(n):
            mi = int(rng.integers(len(self.modules)))
            y[k] = mi
            if augment:
                miss_k = float(rng.uniform(0.0, 0.60))     
                fp_k = float(rng.uniform(0.0, 0.12))
            else:
                miss_k, fp_k = miss_rate, fp_rate
            truth = set(self.module_steps[mi])
            abn = np.zeros(ns, np.float32)
            ans = np.zeros(ns, np.float32)
            for j in truth:
                if rng.random() > miss_k:             
                    ans[j] = 1.0
                    if rng.random() < 0.90:           
                        abn[j] = 1.0
            n_fp = int(fp_k * ns)
            for _ in range(n_fp):                     
                j = int(rng.integers(ns))
                if j not in truth:
                    ans[j] = 1.0
                    abn[j] = 1.0
            X[k, :ns] = abn
            X[k, ns:2 * ns] = ans
            base = 2 * ns
            for j in np.nonzero(abn)[0]:
                X[k, base + self.cidx[self.steps[j]["cat"] or ""]] += 1.0
            b2 = base + len(self.cats)
            X[k, b2] = min(abn.sum(), 50) / 10.0
            X[k, b2 + 1] = min(ans.sum(), 166) / 20.0
            X[k, b2 + 2] = abn.sum() / max(1.0, ans.sum())
            X[k, b2 + 3] = 1.0
        names = ["%s/%s/%s" % m for m in self.modules]
        return X, y, names

    def rule_baseline(self, X):
        """规则基线：异常步 -> 判据 -> 模块 加权投票（与 engine.verdict 同思路）"""
        ns = len(self.steps)
        out = []
        for row in X:
            abn = row[:ns]
            score = {}
            for j in np.nonzero(abn)[0]:
                for m in self.step_modules.get(self.steps[j]["id"], ()):
                    score[m] = score.get(m, 0.0) + float(abn[j])
            if not score:
                out.append(-1)
                continue
            best = max(score.items(), key=lambda kv: kv[1])
            out.append(self.midx.get(best[0], -1))
        return np.asarray(out, np.int64)
