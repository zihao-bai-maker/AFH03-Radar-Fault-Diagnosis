# -*- coding: utf-8 -*-
"""
infer.py —— 板端可用的纯 numpy 推理（只依赖 numpy + .npz）

两个模型：
  Judge   ：参数判别（17 维 -> 正常/不正常/未判定 + 概率），**带弃权**
  Locator ：故障定位（SOP 观测 -> 模块 top-k + 概率）

设计原则（适配性）：
  * 模型只做"辅助打分"：**规则仍然权威**，推理结果附带 `rules_verdict` 供对照
  * 概率不够就**弃权**（abstain），不硬给结论
  * 单一 .npz（float32，几十 KB），加载 <5ms，单次推理 <0.1ms；无 sklearn/torch 依赖

用法：
  python infer.py --selftest                 # 板级自检（无硬件）
  python infer.py --judge "freq,10e6,10002000,1.2,0.95,1,None"
  python infer.py --size                     # 打印模型体积/参数量/延迟
"""
import argparse
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

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

import kb_dataset as DS                                  
import mlp as M                                          
import rules as R                                        

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

DEFAULT_SCOPE = os.path.join(HERE, "out", "model_scope.npz")
DEFAULT_LOCATE = os.path.join(HERE, "out", "model_locate.npz")
ABSTAIN_THR = 0.70          

class Judge:
    """参数判别：输入一次测量参数 -> 三态 + 概率 + 是否弃权"""

    def __init__(self, path=DEFAULT_SCOPE, abstain_thr=ABSTAIN_THR):
        self.m = M.MLP.load(path)
        self.labels = self.m.meta.get("labels") or DS.SCOPE_LABELS
        self.abstain_thr = abstain_thr

    def judge(self, mode, expect=None, meas_hz=None, vpp=None, conf=None,
              probe_ok=True, baseline=None):
        x = DS.feat_scope(mode, expect, meas_hz, vpp, conf, probe_ok, baseline)
        p = self.m.predict_proba(x[None, :])[0]
        i = int(p.argmax())
        rules_item = {"idx": 0, "signal": "-", "route": "-", "part": "-",
                      "judge_mode": mode, "expect_freq_hz": expect,
                      "tol_pct": R.TOL_PCT_DEFAULT, "baseline_vpp": baseline,
                      "noise_vpp_v": R.NOISE_VPP_V, "amp_low_pct": R.AMP_LOW_PCT}
        rl = R.judge_item(rules_item, {"freq_hz": meas_hz, "vpp_v": vpp,
                                       "confidence": 1.0 if conf is None else conf,
                                       "probe_ok": probe_ok})
        return {
            "verdict": self.labels[i],
            "prob": [round(float(x), 4) for x in p],
            "confidence": round(float(p[i]), 4),
            "abstain": bool(p[i] < self.abstain_thr),
            "rules_verdict": rl["verdict_cn"],
            "agree": self.labels[i] == rl["verdict_cn"],
            "rule_code": rl["code"],
        }

class Locator:
    """故障定位：输入一轮 SOP 观测掩码 -> 模块 top-k"""

    def __init__(self, dd=None, path=DEFAULT_LOCATE, abstain_thr=0.0):
        self.d = dd or DS.LocateData()
        self.m = M.MLP.load(path)
        self.names = self.m.meta.get("labels") or ["%s/%s/%s" % m for m in self.d.modules]
        self.abstain_thr = abstain_thr

    def _features(self, abn, ans):
        ns = len(self.d.steps)
        D = self.d.dim()
        x = np.zeros(D, np.float32)
        abn = np.asarray(abn, np.float32).reshape(-1)[:ns]
        ans = np.asarray(ans, np.float32).reshape(-1)[:ns]
        x[:ns] = abn
        x[ns:2 * ns] = ans
        base = 2 * ns
        for j in np.nonzero(abn)[0]:
            x[base + self.d.cidx[self.d.steps[j]["cat"] or ""]] += 1.0
        b2 = base + len(self.d.cats)
        x[b2] = min(abn.sum(), 50) / 10.0
        x[b2 + 1] = min(ans.sum(), 166) / 20.0
        x[b2 + 2] = abn.sum() / max(1.0, ans.sum())
        x[b2 + 3] = 1.0
        return x

    def locate(self, abn, ans, topk=3):
        p = self.m.predict_proba(self._features(abn, ans)[None, :])[0]
        order = np.argsort(-p)[:topk]
        out = [{"module": self.names[i], "prob": round(float(p[i]), 4)} for i in order]

        rb = self.d.rule_baseline(self._features(abn, ans)[None, :])[0]
        rule_mod = ("%s/%s/%s" % self.d.modules[rb]) if rb >= 0 else None
        return {"top": out, "best": out[0]["module"] if out else None,
                "confidence": out[0]["prob"] if out else 0.0,
                "abstain": bool(out and out[0]["prob"] < self.abstain_thr),
                "rules_module": rule_mod}

def selftest():
    ok = bad = 0

    def ck(name, cond, extra=""):
        nonlocal ok, bad
        if cond:
            ok += 1
            print("  [PASS] %s %s" % (name, extra))
        else:
            bad += 1
            print("  [FAIL] %s %s" % (name, extra))

    for p in (DEFAULT_SCOPE, DEFAULT_LOCATE):
        ck("模型存在 %s" % os.path.basename(p), os.path.exists(p),
           "(%.1f KB)" % (os.path.getsize(p) / 1024) if os.path.exists(p) else "")
    if not (os.path.exists(DEFAULT_SCOPE) and os.path.exists(DEFAULT_LOCATE)):
        return 1

    J = Judge()

    cases = [
        ("10M 准", dict(mode="freq", expect=10e6, meas_hz=10_002_000, vpp=1.2, conf=0.95), "正常"),
        ("10M +5.0%", dict(mode="freq", expect=10e6, meas_hz=10_500_000, vpp=1.2, conf=0.95), "正常"),
        ("10M +5.1%", dict(mode="freq", expect=10e6, meas_hz=10_510_000, vpp=1.2, conf=0.95), "不正常"),
        ("10M +8%", dict(mode="freq", expect=10e6, meas_hz=10_800_000, vpp=1.2, conf=0.95), "不正常"),
        ("哨兵+无信号", dict(mode="freq", expect=10e6, meas_hz="*****", vpp=0.01, conf=0.9), "不正常"),
        ("哨兵+探头不明", dict(mode="freq", expect=10e6, meas_hz="*****", vpp=0.01,
                          conf=0.9, probe_ok=False), "未判定"),
        ("有信号无基准", dict(mode="presence", vpp=0.8, conf=0.9), "正常"),
        ("无信号", dict(mode="presence", vpp=0.01, conf=0.9), "不正常"),
        ("幅度40%", dict(mode="presence", vpp=0.4, conf=0.9, baseline=1.0), "不正常"),
        ("幅度60%", dict(mode="presence", vpp=0.6, conf=0.9, baseline=1.0), "正常"),
        ("置信度低", dict(mode="presence", vpp=0.8, conf=0.5), "未判定"),
        ("Vpp缺失", dict(mode="presence", vpp=None, conf=0.9), "未判定"),
    ]
    for name, kw, want in cases:
        r = J.judge(**kw)
        ck("模型 vs 规则一致 · %s" % name,
           r["verdict"] == want and r["agree"], "-> %s(%.2f) rules=%s"
           % (r["verdict"], r["confidence"], r["rules_verdict"]))

    t0 = time.time()
    for _ in range(1000):
        J.judge(mode="freq", expect=10e6, meas_hz=10_000_100, vpp=1.0, conf=0.9)
    dt = (time.time() - t0) / 1000.0 * 1000.0
    ck("单次推理 < 1ms", dt < 1.0, "(%.3f ms)" % dt)

    L = Locator()
    ns = len(L.d.steps)
    abn = np.zeros(ns)
    ans = np.zeros(ns)
    if L.d.module_steps[0]:
        for j in L.d.module_steps[0]:
            abn[j] = ans[j] = 1.0
    r = L.locate(abn, ans, topk=3)
    ck("定位返回 top3", len(r["top"]) == 3, str([t["module"].split("/")[-1][:10] for t in r["top"]]))
    ck("top3 概率单调不增", r["top"][0]["prob"] >= r["top"][1]["prob"] >= r["top"][2]["prob"])

    print("\nSELFTEST: PASS=%d FAIL=%d" % (ok, bad))
    return 0 if bad == 0 else 1

def print_size():
    for name, p in (("scope", DEFAULT_SCOPE), ("locate", DEFAULT_LOCATE)):
        if not os.path.exists(p):
            print("  %-7s 缺失 %s" % (name, p))
            continue
        m = M.MLP.load(p)
        npar = sum(w.size for w in m.W) + sum(b.size for b in m.b)
        print("  %-7s %.1f KB  %d 参数  结构 %s"
              % (name, os.path.getsize(p) / 1024, npar,
                 "-".join(str(w.shape[0]) for w in m.W) + "-" + str(m.W[-1].shape[1])))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--size", action="store_true")
    ap.add_argument("--judge", default="", help="mode,expect,meas,vpp,conf,probe_ok,baseline")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if a.size:
        print_size()
        return 0
    if a.judge:
        f = a.judge.split(",")
        g = lambda i, d=None: (f[i] if i < len(f) and f[i] not in ("", "None") else d)  
        def num(i):
            v = g(i)
            if v is None:
                return None
            try:
                return float(v)
            except ValueError:
                return v
        J = Judge()
        r = J.judge(mode=g(0), expect=num(1), meas_hz=num(2), vpp=num(3), conf=num(4),
                    probe_ok=(g(5, "1") in ("1", "true", "True")), baseline=num(6))
        print(r)
        return 0
    print(__doc__)
    return 0

if __name__ == "__main__":
    sys.exit(main())
