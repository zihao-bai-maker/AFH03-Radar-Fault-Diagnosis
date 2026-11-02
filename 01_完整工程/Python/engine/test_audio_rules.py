#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audio_rules.py 的合成音频自测（不依赖板子、不依赖 numpy）。

用例覆盖：
  1) 干净单次 click            -> normal
  2) 接触器双脉冲（bounce）     -> normal
  3) 低噪声静音                 -> no_sound
  4) 白噪声                     -> no_sound
  5) 50Hz 连续工频嗡声          -> no_sound
  6) 弱 click 埋在白噪声里      -> undetermined（置信不足，不硬判）
  7) 数字全零静音               -> undetermined（可能是麦克风被静音）
  8) 窗口外有 click（窗口 0.2~1.2s） -> no_sound
  9) 窗口内有 click（窗口 2.5~3.5s） -> normal
 10) 8kHz 采样 click           -> normal
 11) 中等音量+强底噪 click      -> normal
 12) 250ms 低沉 clunk           -> normal
 13) 4ms 短促轻响               -> normal
 14) 5 个判据项 schema/证据字段回归

运行： python test_audio_rules.py
"""

from __future__ import annotations

import math
import random
import shutil
import sys
import tempfile
import wave
from pathlib import Path

import audio_rules as ar

RATE = 16000
TWO_PI = 2.0 * math.pi

def _base(dur: float, rate: int = RATE, noise: float = 0.0015,
          seed: int = 7) -> list[float]:
    rng = random.Random(seed)
    return [rng.gauss(0.0, noise) for _ in range(int(rate * dur))]

def _add_click(x: list[float], rate: int, at: float, amp: float = 0.60,
               f1: float = 1800.0, f2: float = 4200.0, tau: float = 0.012,
               bounce: bool = False) -> None:
    """阻尼振荡 + 初始冲激：模拟接触器吸合的短促 clunk。"""
    def one(start: float, a: float, t_decay: float) -> None:
        i0 = int(round(start * rate))
        n = min(int(0.08 * rate), len(x) - i0)
        for i in range(max(0, n)):
            t = i / rate
            env = math.exp(-t / t_decay)
            v = a * env * (0.75 * math.sin(TWO_PI * f1 * t)
                           + 0.25 * math.sin(TWO_PI * min(f2, rate * 0.45) * t + 0.7))
            if t < 0.0006:  
                v += a * 0.8 * (1.0 - t / 0.0006)
            x[i0 + i] += v

    one(at, amp, tau)
    if bounce:
        one(at + 0.009, amp * 0.45, tau * 0.7)

def _write_wav(path: Path, samples: list[float], rate: int = RATE) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        frames = bytearray()
        for v in samples:
            iv = int(round(max(-1.0, min(1.0, v)) * 32767))
            frames += int(iv).to_bytes(2, "little", signed=True)
        w.writeframes(bytes(frames))

def _silence(dur: float = 4.0) -> list[float]:
    return _base(dur, noise=0.0004, seed=3)

def _clean_click(dur: float = 4.0, at: float = 1.2) -> list[float]:
    x = _base(dur, noise=0.0012, seed=11)
    _add_click(x, RATE, at, amp=0.62)
    return x

def _double_click(dur: float = 4.0) -> list[float]:
    x = _base(dur, noise=0.0012, seed=12)
    _add_click(x, RATE, 1.2, amp=0.58, bounce=True)
    return x

def _white_noise(dur: float = 4.0) -> list[float]:
    rng = random.Random(21)
    return [rng.gauss(0.0, 0.08) for _ in range(int(RATE * dur))]

def _hum(dur: float = 4.0) -> list[float]:
    return [
        0.30 * math.sin(TWO_PI * 50.0 * i / RATE)
        + 0.03 * math.sin(TWO_PI * 150.0 * i / RATE)
        for i in range(int(RATE * dur))
    ]

def _weak_click_in_noise(dur: float = 4.0) -> list[float]:
    x = _base(dur, noise=0.008, seed=31)
    _add_click(x, RATE, 1.2, amp=0.035, tau=0.010)
    return x

def _digital_silence(dur: float = 4.0) -> list[float]:
    return [0.0] * int(RATE * dur)

def _click_at_3s(dur: float = 4.0) -> list[float]:
    x = _base(dur, noise=0.0012, seed=41)
    _add_click(x, RATE, 3.0, amp=0.62)
    return x

def _moderate_click_ambient(dur: float = 4.0) -> list[float]:
    """中等音量 + 较强环境底噪（现场常见）。"""
    x = _base(dur, noise=0.004, seed=61)
    _add_click(x, RATE, 1.2, amp=0.15)
    return x

def _long_clunk(dur: float = 4.0) -> list[float]:
    """较沉的接触器 clunk：300Hz 主分量、约 130ms。"""
    x = _base(dur, noise=0.0012, seed=62)
    i0 = int(1.0 * RATE)
    for i in range(min(int(0.25 * RATE), len(x) - i0)):
        t = i / RATE
        env = math.exp(-t / 0.09)
        x[i0 + i] += 0.5 * env * (
            0.7 * math.sin(TWO_PI * 300.0 * t) + 0.3 * math.sin(TWO_PI * 1200.0 * t)
        )
    return x

def _short_click(dur: float = 4.0) -> list[float]:
    """很短（~4ms 衰减）的继电器轻响。"""
    x = _base(dur, noise=0.0012, seed=66)
    _add_click(x, RATE, 1.2, amp=0.60, tau=0.003)
    return x

CASES = [
    ("clean_click", _clean_click, None, "normal"),
    ("double_click_bounce", _double_click, None, "normal"),
    ("silence_low_noise", _silence, None, "no_sound"),
    ("white_noise", _white_noise, None, "no_sound"),
    ("continuous_hum_50hz", _hum, None, "no_sound"),
    ("weak_click_in_noise", _weak_click_in_noise, None, "undetermined"),
    ("digital_silence", _digital_silence, None, "undetermined"),
    ("click_outside_window", _click_at_3s, (0.2, 1.2), "no_sound"),
    ("click_inside_window", _click_at_3s, (2.5, 3.5), "normal"),
    ("moderate_click_ambient", _moderate_click_ambient, None, "normal"),
    ("long_clunk_250ms", _long_clunk, None, "normal"),
    ("short_click_4ms", _short_click, None, "normal"),
]

def run_acoustic_cases(tmp: Path) -> list[dict]:
    results = []
    for idx, (name, builder, window, expected) in enumerate(CASES, 1):
        path = tmp / f"{idx:02d}_{name}.wav"
        _write_wav(path, builder())
        ev = ar.judge(path, item_id="audio_z31_power_box_contactor", window=window)
        ok = ev["value"] == expected
        if expected == "undetermined":
            ok = ok and ev["confidence"] <= 0.5   
        else:
            ok = ok and ev["confidence"] >= 0.6
        results.append({
            "case": name,
            "expected": expected,
            "actual": ev["value"],
            "confidence": ev["confidence"],
            "score": ev["score"],
            "pass": ok,
        })
    return results

def run_rate_case(tmp: Path) -> dict:
    rate = 8000
    x = _base(4.0, rate=rate, noise=0.0012, seed=51)
    _add_click(x, rate, 1.2, amp=0.62, f2=3200.0)
    path = tmp / "10_click_8khz.wav"
    _write_wav(path, x, rate=rate)
    ev = ar.judge(path, item_id="audio_z20_antenna_main_relay")
    ok = ev["value"] == "normal"
    return {
        "case": "click_8khz", "expected": "normal", "actual": ev["value"],
        "confidence": ev["confidence"], "score": ev["score"], "pass": ok,
    }

def run_schema_case(tmp: Path) -> list[dict]:
    """5 个判据项 + 证据 JSON 字段回归。"""
    results = []
    items = ar.load_items()
    checks = [
        ("items_count_is_5", len(items) == 5, f"实际 {len(items)}"),
        ("parts_are_z", all(str(it["part"]).startswith("z") for it in items),
         ",".join(it["part"] for it in items)),
        ("expect_click", all("吸合声" in it["expect"] for it in items), ""),
        ("abnormal_no_sound", all(it["abnormal"] == "no_sound" for it in items), ""),
        ("flows_match_library",
         [it["flow_no"] for it in items] == ["2", "4", "15(10-I)", "16（10-II）", "19"],
         str([it["flow_no"] for it in items])),
        ("i_ii_share_z16_field",
         items[2]["part"] == items[3]["part"] == "z16"
         and items[2]["field"] == items[3]["field"],
         f'{items[2]["field"]} / {items[3]["field"]}'),
        ("routes_are_strings",
         all(isinstance(it.get("route"), str) for it in items)
         and items[0]["route"] == "" and items[2]["route"] == "I"
         and items[3]["route"] == "II",
         str([it.get("route") for it in items])),
    ]
    for name, ok, detail in checks:
        results.append({"case": name, "expected": "true", "actual": str(bool(ok)).lower(),
                        "confidence": "-", "score": "-", "pass": bool(ok), "detail": detail})

    click = tmp / "schema_click.wav"
    _write_wav(click, _clean_click())
    for it in items:
        ev = ar.judge(click, item=it)
        required = {"part", "route", "modality", "field", "value",
                    "confidence", "evidence", "ts"}
        ok = (
            required.issubset(ev)
            and ev["modality"] == "audio"
            and ev["part"] == it["part"]
            and ev["route"] == (it.get("route") or "")
            and ev["field"] == it["field"]
            and ev["value"] == "normal"
            and ev["feature_id"] == it["feature_id"]
            and isinstance(ev["route"], str)
            and 0 < len(ev["evidence"]) <= 200
            and bool(ev["ts"])
        )
        results.append({
            "case": f"evidence_{it['item_id']}", "expected": "normal",
            "actual": ev["value"], "confidence": ev["confidence"],
            "score": ev["score"], "pass": ok,
        })
    return results

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    tmp = Path(tempfile.mkdtemp(prefix="audio_rules_test_", dir=str(ar.ENGINE_DIR)))
    try:
        results = run_acoustic_cases(tmp)
        results.append(run_rate_case(tmp))

        results.extend(run_schema_case(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"{'case':<36} {'expected':<13} {'actual':<13} {'score':<8} {'conf':<6} pass")
    print("-" * 92)
    for r in results:
        print(f"{r['case']:<36} {r['expected']:<13} {r['actual']:<13} "
              f"{str(r['score']):<8} {str(r['confidence']):<6} "
              f"{'PASS' if r['pass'] else 'FAIL'}")
    passed = sum(1 for r in results if r["pass"])
    total = len(results)
    print("-" * 92)
    print(f"通过率: {passed}/{total} = {passed / total * 100:.1f}%")
    failed = [r["case"] for r in results if not r["pass"]]
    if failed:
        print("失败用例: " + ", ".join(failed))
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
