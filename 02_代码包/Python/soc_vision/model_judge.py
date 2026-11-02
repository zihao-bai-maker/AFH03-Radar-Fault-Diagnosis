# -*- coding: utf-8 -*-
"""模型判断桥接（推测/可能性排序；只读、可关闭、失败降级）。

把交接包 `机器学习/` 里的 numpy MLP 判别模型接到 UI：
  * `model_scope.npz`：17 维波形测量特征 -> 正常/不正常/未判定 + 概率；
  * `model_locate.npz`：旧 166 步 SOP 观测 -> 35 模块概率（当前 127 步 flow 暂无
    直接映射，定位接口先不启用，避免"伪精确"）。

原则（与交接包 GUIDE §4 / 旧诊断系统 ml_bridge 一致）：
  * 规则永远权威；模型只给概率/置信/弃权/一致性提示，不覆盖结论；
  * 模型缺失/异常 -> ok=False，UI 不显示，不影响主流程；
  * 默认开启，可用环境变量 AFH03_USE_MODEL_JUDGE=0 关闭。
"""
import os
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_BASE = os.path.dirname(_HERE)
_LOCK = threading.Lock()
_STATE = {"loaded": False, "ok": False, "judge": None, "err": "", "ml_dir": "",
          "locate": None, "locate_steps": [], "locate_step_parts": [],
          "locate_labels": [], "locate_err": ""}

SCOPE_LABELS = ("正常", "不正常", "未判定")

def _find_ml_dir():
    cands = []
    env = os.environ.get("AFH03_ML_DIR", "")
    if env:
        cands.append(env)
    cands += [
        os.path.join(_BASE, "ml"),
        os.path.join(_HERE, "ml"),
        os.path.join(_BASE, "soc_vision", "ml"),
        "/home/rock/afh03_board_setup/ml",
    ]
    for d in cands:
        if not d:
            continue
        try:
            if (os.path.exists(os.path.join(d, "mlp.py")) and
                    os.path.exists(os.path.join(d, "out", "model_scope.npz"))):
                return os.path.abspath(d)
        except OSError:
            continue
    return ""

def _load():
    """懒加载：只加载一次；失败缓存错误，不抛异常。"""
    with _LOCK:
        if _STATE["loaded"]:
            return _STATE
        _STATE["loaded"] = True
        d = _find_ml_dir()
        if not d:
            _STATE["err"] = "未找到 ml/ 模型目录（mlp.py + out/model_scope.npz）"
            return _STATE
        try:

            
            for p in (os.path.join(d, "波形检测"), d):
                if p not in sys.path:
                    sys.path.insert(0, p)
            import importlib
            _mlp = importlib.import_module("mlp")          
            _ds = importlib.import_module("kb_dataset")    
            _inf = importlib.import_module("infer")
            _STATE["judge"] = _inf.Judge(os.path.join(d, "out", "model_scope.npz"))

            _lp = os.path.join(d, "out", "model_locate_flow.npz")
            if os.path.exists(_lp):
                try:
                    _loc = _mlp.MLP.load(_lp)
                    _st = list(_loc.meta.get("steps") or [])
                    _lb = list(_loc.meta.get("labels") or [])
                    _sp = list(_loc.meta.get("step_parts") or [])
                    if _st and _lb and _sp:
                        _STATE.update(locate=_loc, locate_steps=_st,
                                      locate_step_parts=_sp, locate_labels=_lb)
                except Exception as e:                         
                    _STATE["locate_err"] = "%s: %s" % (type(e).__name__, e)
            _STATE.update(ok=True, err="", ml_dir=d)
        except Exception as e:                             
            _STATE.update(ok=False, err="%s: %s" % (type(e).__name__, e))
        return _STATE

def enabled():
    return str(os.environ.get("AFH03_USE_MODEL_JUDGE", "1")).strip() != "0"

def _norm_state(v):
    s = str(v or "").strip()
    low = s.lower()
    if ("不正常" in s) or ("异常" in s) or (low in ("bad", "fail", "failed", "ng")):
        return "不正常"
    if ("正常" in s) or (low in ("ok", "pass", "passed", "good")):
        return "正常"
    return "未判定"

def _scope_items(scope):
    """从 _sa_scope_view() 或 load_scope_result() 取归一化 items。"""
    res = (scope or {}).get("res") or {}
    items = res.get("items")
    if isinstance(items, list) and items:
        return items
    if (scope or {}).get("hz") is not None or (scope or {}).get("vpp") is not None:
        return [{"name": (scope or {}).get("name") or "CH1",
                 "expect_hz": (scope or {}).get("expect"),
                 "measured_hz": (scope or {}).get("hz"),
                 "vpp_v": (scope or {}).get("vpp"),
                 "verdict": _norm_state((scope or {}).get("state")),
                 "verdict_raw": (scope or {}).get("state")}]
    return []

def judge_scope(scope):
    """参数判别：返回 {ok, verdict, confidence, probs, agree, abstain, line, items, ms}。"""
    if not enabled():
        return {"ok": False, "reason": "已关闭（AFH03_USE_MODEL_JUDGE=0）"}
    st = _load()
    if not st["ok"]:
        return {"ok": False, "reason": st["err"]}
    items = _scope_items(scope)
    if not items:
        return {"ok": False, "reason": "无有效测量条目"}

    judge = st["judge"]
    labels = list(getattr(judge, "labels", SCOPE_LABELS))
    probs = []
    rows = []
    t0 = time.time()
    for it in items[:4]:
        exp = it.get("expect_hz")
        meas = it.get("measured_hz")
        vpp = it.get("vpp_v")
        if exp is None and meas is None and vpp is None:
            continue
        mode = "freq" if (exp is not None or meas is not None) else "presence"
        try:
            conf = float(it.get("confidence")) if it.get("confidence") is not None else 1.0
        except (TypeError, ValueError):
            conf = 1.0
        try:
            r = judge.judge(mode=mode, expect=exp, meas_hz=meas, vpp=vpp,
                            conf=conf, probe_ok=True, baseline=None)
        except Exception:                                   
            continue
        probs.append(r.get("prob") or [0.0, 0.0, 0.0])
        rows.append({"name": it.get("name") or it.get("channel") or "CH1",
                     "model": r.get("verdict"),
                     "confidence": r.get("confidence"),
                     "abstain": r.get("abstain"),
                     "rules": r.get("rules_verdict"),
                     "agree": r.get("agree"),
                     "prob": r.get("prob")})
    if not probs:
        return {"ok": False, "reason": "模型推理失败（无可用条目）"}

    import numpy as np
    p = np.mean(np.asarray(probs, dtype=np.float64), axis=0)
    i = int(p.argmax())
    verdict = str(labels[i])
    conf = float(p[i])
    abstain = bool(conf < 0.70)
    rules_v = _norm_state((scope or {}).get("state") or (scope or {}).get("verdict"))
    agree = (verdict == rules_v)
    meta = []
    if abstain:
        meta.append("置信不足→弃权")
    if (not agree) and rules_v != "未判定":
        meta.append("与规则不一致（以规则/人工为准）")
    line = "%s（置信 %.2f；可能性：%s）" % (
        verdict, conf, " / ".join("%s %.2f" % (labels[k], p[k]) for k in range(len(labels))))
    if meta:
        line += "；" + "；".join(meta)
    return {"ok": True, "verdict": verdict, "confidence": round(conf, 4),
            "abstain": abstain, "probs": {labels[k]: round(float(p[k]), 4) for k in range(len(labels))},
            "agree": agree, "rules_verdict": rules_v, "items": rows,
            "line": line, "ms": round((time.time() - t0) * 1000.0, 2),
            "ml_dir": st["ml_dir"]}

_ABNORMAL_VALUES = {"abnormal", "bad", "fail", "failed", "ng", "error",
                    "off", "no_signal", "missing", "unqualified", "fault"}

def locate_flow(evidences, topk=3):
    """当前 127 步 flow 的“故障部位可能性排序”（推测，不替代规则）。

    evidences：flow["evidence"] 或 session_summary 证据列表；用 step_id 建 127 维掩码。
    返回 {ok, top:[{part,prob}], line, n_abn, n_ans, ms}；无异常观测→不推测。
    """
    if not enabled():
        return {"ok": False, "reason": "已关闭（AFH03_USE_MODEL_JUDGE=0）"}
    st = _load()
    if not st["ok"]:
        return {"ok": False, "reason": st["err"]}
    if st["locate"] is None:
        return {"ok": False, "reason": st.get("locate_err") or "未部署 model_locate_flow.npz"}

    steps = list(st["locate_steps"])
    labels = list(st["locate_labels"])
    n = len(steps)
    idx = {str(s): i for i, s in enumerate(steps)}
    abn = [0.0] * n
    ans = [0.0] * n
    for ev in (evidences or []):
        if not isinstance(ev, dict):
            continue
        sid = str(ev.get("step_id") or "")
        i = idx.get(sid)
        if i is None:
            continue
        ans[i] = 1.0
        val = str(ev.get("value") or "").strip().lower()
        if ev.get("match") is False or val in _ABNORMAL_VALUES:
            abn[i] = 1.0
    n_abn = int(sum(abn))
    n_ans = int(sum(ans))
    if n_abn <= 0:
        return {"ok": False, "reason": "本轮无异常观测，模型不推测",
                "n_abn": 0, "n_ans": n_ans}

    import numpy as np
    step_parts = list(st.get("locate_step_parts") or [])
    if len(step_parts) != n:
        return {"ok": False, "reason": "定位模型缺少 step_parts 映射（模型版本不匹配）"}
    f = np.zeros(2 * n + 2 * len(labels) + 4, np.float32)
    f[:n] = abn
    f[n:2 * n] = ans
    b = 2 * n
    for pi, pname in enumerate(labels):
        _ix = [j for j, q in enumerate(step_parts) if q == pname]
        if _ix:
            f[b + 2 * pi] = min(float(np.sum(np.asarray(abn)[_ix])), 20.0) / 5.0
            f[b + 2 * pi + 1] = min(float(np.sum(np.asarray(ans)[_ix])), 25.0) / 10.0
    b += 2 * len(labels)
    f[b] = min(n_abn, 50) / 10.0
    f[b + 1] = min(n_ans, 127) / 20.0
    f[b + 2] = n_abn / max(1, n_ans)
    f[b + 3] = 1.0
    t0 = time.time()
    p = st["locate"].predict_proba(f[None, :])[0]
    order = list(np.argsort(p)[::-1])
    top = [{"part": str(labels[i]).upper(), "prob": round(float(p[i]), 4)} for i in order[:topk]]
    conf = float(p[order[0]])
    line = "模型候选（top3）：%s（依据：异常 %d 条 / 已答 %d 条；仅参考，不替代规则）" % (
        " / ".join("%s %.2f" % (x["part"], x["prob"]) for x in top),
        n_abn, n_ans)
    return {"ok": True, "top": top, "confidence": round(conf, 4),
            "line": line, "n_abn": n_abn, "n_ans": n_ans,
            "ms": round((time.time() - t0) * 1000.0, 2)}

def model_info():
    st = _load()
    return {"ok": bool(st["ok"]), "err": st["err"], "ml_dir": st["ml_dir"],
            "scope": bool(st["ok"]),
            "locate": bool(st.get("locate") is not None),
            "locate_err": st.get("locate_err") or "",
            "locate_steps": len(st.get("locate_steps") or []),
            "locate_labels": list(st.get("locate_labels") or [])}
