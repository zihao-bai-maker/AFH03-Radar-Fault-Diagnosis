#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""声音判定引擎（audio modality）

判定对象：判据库 method="麦克风采集声音" 的 5 项。
吸合声（交流接触器/继电器动作）是**短促宽带脉冲**：
    能量快速上升 -> 数十 ms 内衰减 -> 高频成分明显高于本底。
本引擎只做“有无吸合声”的二分类 + 置信不足时 undetermined，不臆造故障。

依赖：Python 标准库（wave/math/array/json），不依赖 numpy，
      因此 Windows 主机与板端（若有 python3）都能直接运行。

统一证据 JSON（judge 输出）：
    {"part": "z31", "modality": "audio",
     "field": "(audio)_z31_power_box_contactor",
     "value": "normal|no_sound|undetermined", "confidence": 0.93, ...}

命令行：
    python audio_rules.py --list
    python audio_rules.py --wav z31.wav --item audio_z31_power_box_contactor
    python audio_rules.py --wav z31.wav --item audio_z31_power_box_contactor --start 2 --end 4
"""

from __future__ import annotations

import argparse
import array
import json
import math
import sys
import wave
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ENGINE_DIR = Path(__file__).resolve().parent
DEFAULT_ITEMS_PATH = ENGINE_DIR / "audio_items.json"

FRAME_MS = 10.0
HOP_MS = 2.5

NORMAL_SCORE = 0.62       
NO_SOUND_SCORE = 0.38     
DEFAULT_MIN_CONFIDENCE = 0.60
MIN_AUDIO_S = 0.05        

REQUIRED_ITEM_KEYS = (
    "item_id", "flow_no", "check_item", "part",
    "expect", "abnormal", "field", "feature_id",
)
VALID_VALUES = ("normal", "no_sound", "undetermined")

def _decode_pcm(raw: bytes, width: int) -> List[float]:
    """把 little-endian PCM 解码成 [-1, 1) 的 float 列表。"""
    if width == 1:
        return [(b - 128) / 128.0 for b in raw]
    if width == 2:
        a = array.array("h")
        a.frombytes(raw)
        if sys.byteorder != "little":
            a.byteswap()
        return [v / 32768.0 for v in a]
    if width == 3:
        out: List[float] = []
        for i in range(0, len(raw) - 2, 3):
            v = raw[i] | (raw[i + 1] << 8) | (raw[i + 2] << 16)
            if v & 0x800000:
                v -= 1 << 24
            out.append(v / 8388608.0)
        return out
    if width == 4:
        a = array.array("i")
        a.frombytes(raw)
        if sys.byteorder != "little":
            a.byteswap()
        return [v / 2147483648.0 for v in a]
    raise ValueError(f"不支持的采样位宽: {width * 8} bit（支持 8/16/24/32）")

def _downmix(samples: List[float], channels: int) -> List[float]:
    if channels <= 1:
        return samples
    n = len(samples) // channels
    return [
        sum(samples[i * channels:(i + 1) * channels]) / channels
        for i in range(n)
    ]

def read_wav(path: Path) -> Tuple[List[float], int, int, int]:
    """返回 (mono_samples, sample_rate, channels, sample_width_bytes)。"""
    with wave.open(str(path), "rb") as w:
        channels = w.getnchannels()
        width = w.getsampwidth()
        rate = w.getframerate()
        nframes = w.getnframes()
        raw = w.readframes(nframes)
    if channels < 1:
        raise ValueError("WAV 声道数非法")
    samples = _decode_pcm(raw, width)
    return _downmix(samples, channels), rate, channels, width

def _percentile(values: Sequence[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo = int(math.floor(k))
    hi = int(math.ceil(k))
    if lo == hi:
        return s[lo]
    return s[lo] * (hi - k) + s[hi] * (k - lo)

def _db(x: float) -> float:
    return 20.0 * math.log10(max(x, 1e-9))

def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)

def _resolve_window(
    window: Optional[Sequence[float]],
    start_s: Optional[float],
    end_s: Optional[float],
    total_s: float,
) -> Tuple[float, float]:
    if window is None and (start_s is not None or end_s is not None):
        window = (start_s if start_s is not None else 0.0,
                  end_s if end_s is not None else total_s)
    if window is None:
        return 0.0, total_s
    if len(window) != 2:
        raise ValueError("window 必须是 (start_s, end_s)")
    a = 0.0 if window[0] is None else float(window[0])
    b = total_s if window[1] is None else float(window[1])
    if a < 0 or b <= a:
        raise ValueError(f"非法录音窗口: {window!r}")
    a = min(a, total_s)
    b = min(b, total_s)
    if b - a < MIN_AUDIO_S:
        raise ValueError(f"录音窗口过短（{b - a:.3f}s < {MIN_AUDIO_S}s）")
    return a, b

def _segment(mask: Sequence[bool], peak: int, max_gap: int) -> Tuple[int, int]:
    """从 peak 向两侧扩展，允许中间有 max_gap 帧静音；返回 [lo, hi]。"""
    lo = peak
    gap = 0
    i = peak - 1
    while i >= 0:
        if mask[i]:
            lo = i
            gap = 0
        else:
            gap += 1
            if gap > max_gap:
                break
        i -= 1
    hi = peak
    gap = 0
    i = peak + 1
    while i < len(mask):
        if mask[i]:
            hi = i
            gap = 0
        else:
            gap += 1
            if gap > max_gap:
                break
        i += 1
    return lo, hi

def _duration_score(ms: float) -> float:
    if ms < 1.5:
        return 0.15
    if ms < 5.0:
        return 0.15 + 0.85 * (ms - 1.5) / 3.5
    if ms <= 300.0:
        return 1.0
    if ms <= 800.0:
        return 1.0 - 0.70 * (ms - 300.0) / 500.0
    return 0.10

def _attack_score(ms: Optional[float]) -> float:
    if ms is None:
        return 0.10
    if ms <= 12.0:
        return 1.0
    if ms <= 80.0:
        return 1.0 - 0.85 * (ms - 12.0) / 68.0
    return 0.10

def analyze(
    wav_path: str | Path,
    window: Optional[Sequence[float]] = None,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
) -> Dict[str, Any]:
    """分析一段录音，返回可解释的声学特征（不含判定结论）。

    window=(2.0, 4.0) 表示只分析“按下按键后 2~4 秒”的文件内区间。
    """
    path = Path(wav_path)
    if not path.is_file():
        raise FileNotFoundError(f"录音文件不存在: {path}")

    samples, rate, channels, width = read_wav(path)
    total_s = len(samples) / float(rate)
    a, b = _resolve_window(window, start_s, end_s, total_s)
    i0 = int(round(a * rate))
    i1 = int(round(b * rate))
    seg = samples[i0:i1]
    if len(seg) < int(MIN_AUDIO_S * rate):
        raise ValueError("裁剪后的音频过短")

    frame_len = max(16, int(round(rate * FRAME_MS / 1000.0)))
    hop_len = max(1, int(round(rate * HOP_MS / 1000.0)))
    if len(seg) < frame_len:
        seg = seg + [0.0] * (frame_len - len(seg))

    starts = list(range(0, len(seg) - frame_len + 1, hop_len))
    if not starts or starts[-1] + frame_len < len(seg):
        starts.append(len(seg) - frame_len)

    rms_db: List[float] = []
    diff_db: List[float] = []
    zcr: List[float] = []
    for st in starts:
        fr = seg[st:st + frame_len]
        energy = sum(v * v for v in fr) / frame_len
        rms_db.append(_db(math.sqrt(energy)))
        d_energy = 0.0
        crossings = 0
        prev = fr[0]
        for v in fr[1:]:
            d = v - prev
            d_energy += d * d
            if (prev < 0.0) != (v < 0.0):
                crossings += 1
            prev = v
        diff_db.append(_db(math.sqrt(d_energy / max(1, frame_len - 1))))
        zcr.append(crossings / float(max(1, frame_len - 1)))

    peak_idx = max(range(len(rms_db)), key=lambda i: rms_db[i])
    peak_dbfs = rms_db[peak_idx]
    noise_dbfs = _percentile(rms_db, 10)
    p90_dbfs = _percentile(rms_db, 90)
    snr_db = max(0.0, peak_dbfs - noise_dbfs)
    contrast_db = max(0.0, peak_dbfs - p90_dbfs)

    hf_peak_dbfs = max(diff_db)
    hf_floor_dbfs = _percentile(diff_db, 10)
    hf_p90_dbfs = _percentile(diff_db, 90)
    hf_snr_db = max(0.0, hf_peak_dbfs - hf_floor_dbfs)
    hf_contrast_db = max(0.0, hf_peak_dbfs - hf_p90_dbfs)

    max_abs = max(abs(v) for v in seg)
    peak_sample_dbfs = _db(max_abs)
    overall_rms = math.sqrt(sum(v * v for v in seg) / len(seg))
    overall_rms_dbfs = _db(overall_rms)
    crest_db = peak_sample_dbfs - overall_rms_dbfs

    digital_silence = max_abs < 1e-6
    clipping_ratio = sum(1 for v in seg if abs(v) >= 0.999) / float(len(seg))

    
    event_gate = (contrast_db >= 5.0) and (snr_db >= 5.0)
    if event_gate:
        thr = max(noise_dbfs + 6.0, peak_dbfs - 12.0)
        mask = [v >= thr for v in rms_db]
        lo, hi = _segment(mask, peak_idx, max_gap=2)
        duration_ms = (hi - lo + 1) * HOP_MS
        attack_thr = max(noise_dbfs + 6.0, peak_dbfs - 10.0)
        first = peak_idx
        for i in range(lo, peak_idx + 1):
            if rms_db[i] >= attack_thr:
                first = i
                break
        attack_ms: Optional[float] = max(0.0, (peak_idx - first) * HOP_MS)
    else:
        duration_ms = 0.0
        attack_ms = None

    zcr_peak = zcr[peak_idx]
    zcr_floor = _percentile(zcr, 10)
    zcr_lift = max(0.0, zcr_peak - zcr_floor)

    contrast_s = _clamp01((contrast_db - 4.0) / 16.0)
    hf_s = _clamp01((hf_contrast_db - 3.0) / 12.0)
    snr_s = _clamp01((snr_db - 5.0) / 20.0)
    level_s = _clamp01((peak_sample_dbfs + 55.0) / 30.0)
    if event_gate:
        duration_s = _duration_score(duration_ms)
        attack_s = _attack_score(attack_ms)
        zcr_s = _clamp01(zcr_lift / 0.20)
    else:
        duration_s = attack_s = zcr_s = 0.0

    score = (
        0.30 * contrast_s
        + 0.22 * hf_s
        + 0.13 * snr_s
        + 0.08 * level_s
        + 0.12 * duration_s
        + 0.10 * attack_s
        + 0.05 * zcr_s
    )

    warnings: List[str] = []
    if digital_silence:
        warnings.append("digital_silence")
    if clipping_ratio > 0.001:
        warnings.append("clipping")
    if peak_sample_dbfs < -55.0 and not digital_silence:
        warnings.append("low_level_check_gain")
    if rate != 16000 or channels != 1:
        warnings.append("nonstandard_format_16k_mono_recommended")

    return {
        "source_wav": str(path.resolve()),
        "sample_rate": rate,
        "channels": channels,
        "sample_width_bits": width * 8,
        "duration_s": round(total_s, 3),
        "window": {"start_s": round(a, 3), "end_s": round(b, 3),
                   "length_s": round(b - a, 3)},
        "frame_ms": FRAME_MS,
        "hop_ms": HOP_MS,
        "n_frames": len(rms_db),

        "peak_dbfs": round(peak_dbfs, 3),
        "noise_floor_dbfs": round(noise_dbfs, 3),
        "p90_dbfs": round(p90_dbfs, 3),
        "snr_db": round(snr_db, 3),
        "transient_contrast_db": round(contrast_db, 3),

        "hf_peak_dbfs": round(hf_peak_dbfs, 3),
        "hf_floor_dbfs": round(hf_floor_dbfs, 3),
        "hf_contrast_db": round(hf_contrast_db, 3),
        "hf_snr_db": round(hf_snr_db, 3),

        "peak_sample_dbfs": round(peak_sample_dbfs, 3),
        "overall_rms_dbfs": round(overall_rms_dbfs, 3),
        "crest_db": round(crest_db, 3),
        "duration_ms": round(duration_ms, 3),
        "attack_ms": None if attack_ms is None else round(attack_ms, 3),
        "event_gate": bool(event_gate),

        "zcr_peak": round(zcr_peak, 4),
        "zcr_floor": round(zcr_floor, 4),
        "zcr_lift": round(zcr_lift, 4),
        "clipping_ratio": round(clipping_ratio, 5),
        "digital_silence": bool(digital_silence),

        "score": round(score, 4),
        "score_components": {
            "contrast": round(contrast_s, 4),
            "hf": round(hf_s, 4),
            "snr": round(snr_s, 4),
            "level": round(level_s, 4),
            "duration": round(duration_s, 4),
            "attack": round(attack_s, 4),
            "zcr": round(zcr_s, 4),
        },
        "warnings": warnings,
    }

def _decide(feat: Dict[str, Any], min_confidence: float) -> Tuple[str, float, str]:

    def undet(conf: float, reason: str) -> Tuple[str, float, str]:
        return "undetermined", round(min(float(conf), 0.49), 3), reason

    if feat["digital_silence"]:
        return undet(
            0.20,
            "整段为数字静音：无法区分‘确实无吸合声’与‘麦克风被静音/未接线’",
        )

    score = float(feat["score"])
    if score >= NORMAL_SCORE:
        conf = 0.5 + 0.49 * (score - NORMAL_SCORE) / (1.0 - NORMAL_SCORE)
        value = "normal"
        reason = (
            "检测到短促宽带瞬态（吸合声 click/clunk）："
            f"能量对比 {feat['transient_contrast_db']} dB，"
            f"高频对比 {feat['hf_contrast_db']} dB，"
            f"持续 {feat['duration_ms']} ms，起振 {feat['attack_ms']} ms"
        )
    elif score <= NO_SOUND_SCORE:
        conf = 0.5 + 0.49 * (NO_SOUND_SCORE - score) / NO_SOUND_SCORE
        value = "no_sound"
        reason = (
            "未检测到短促吸合声瞬态："
            f"能量对比 {feat['transient_contrast_db']} dB，"
            f"高频对比 {feat['hf_contrast_db']} dB，"
            f"峰值 {feat['peak_sample_dbfs']} dBFS"
        )
    else:
        return undet(
            0.40,
            f"置信不足：score={score:.3f} 落在灰区 "
            f"({NO_SOUND_SCORE}~{NORMAL_SCORE})，不硬判",
        )

    if feat["peak_sample_dbfs"] < -70.0 and value == "no_sound":
        return undet(
            0.30,
            f"音频电平极低（{feat['peak_sample_dbfs']} dBFS），可能麦克风未开/未接线，"
            "无法确认无吸合声",
        )
    if "clipping" in feat["warnings"]:
        conf *= 0.90
        reason += "；录音削顶，置信度已下调"
    if "low_level_check_gain" in feat["warnings"]:
        conf = min(conf, 0.80)
        reason += (
            f"；录音电平偏低（峰值 {feat['peak_sample_dbfs']} dBFS），"
            "建议确认麦克风增益/距离"
        )
    if conf < min_confidence:
        return undet(
            conf,
            f"置信度 {conf:.3f} < 门槛 {min_confidence:.2f}，不硬判",
        )
    return value, round(min(conf, 0.99), 3), reason

def load_items(items_path: str | Path | None = None) -> List[Dict[str, Any]]:
    path = Path(items_path) if items_path else DEFAULT_ITEMS_PATH
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise ValueError("audio_items.json 中 items 为空")
    seen = set()
    for it in items:
        missing = [k for k in REQUIRED_ITEM_KEYS if k not in it]
        if missing:
            raise ValueError(f"item {it.get('item_id', '?')} 缺少字段: {missing}")
        if it["item_id"] in seen:
            raise ValueError(f"item_id 重复: {it['item_id']}")
        seen.add(it["item_id"])
        if it["abnormal"] != "no_sound":
            raise ValueError(f"item {it['item_id']} abnormal 应为 no_sound")
    return items

def get_item(item_id: str, items_path: str | Path | None = None) -> Dict[str, Any]:
    for it in load_items(items_path):
        if it["item_id"] == item_id:
            return it
    ids = ", ".join(it["item_id"] for it in load_items(items_path))
    raise KeyError(f"未知 item_id: {item_id}；可选: {ids}")

def judge(
    wav_path: str | Path,
    item: Optional[Dict[str, Any] | str] = None,
    item_id: Optional[str] = None,
    window: Optional[Sequence[float]] = None,
    start_s: Optional[float] = None,
    end_s: Optional[float] = None,
    min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    items_path: str | Path | None = None,
) -> Dict[str, Any]:
    """对一条录音给出统一证据 JSON。

    item 可以是 audio_items.json 里的 dict，也可以是 item_id 字符串；
    也可用 item_id=... 单独传。
    """
    if isinstance(item, str):
        item_id = item
        item = None
    if item is None:
        if item_id is None:
            raise ValueError("judge 需要 item(dict) 或 item_id")
        item = get_item(item_id, items_path)
    else:
        missing = [k for k in REQUIRED_ITEM_KEYS if k not in item]
        if missing:
            raise ValueError(f"item 缺少字段: {missing}")

    feat = analyze(wav_path, window=window, start_s=start_s, end_s=end_s)
    value, confidence, reason = _decide(feat, float(min_confidence))
    if value not in VALID_VALUES:  
        raise AssertionError(value)

    evidence: Dict[str, Any] = {

        "part": item["part"],
        "route": item.get("route") or "",
        "modality": "audio",
        "field": item["field"],
        "value": value,
        "confidence": confidence,
        "evidence": reason.replace("\n", " ")[:200],
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "audio_rules.judge",

        "item_id": item["item_id"],
        "flow_no": item["flow_no"],
        "check_item": item["check_item"],
        "expect": item["expect"],
        "abnormal": item["abnormal"],
        "feature_id": item["feature_id"],
        "window": feat["window"],
        "score": feat["score"],
        "reason": reason,
        "features": feat,
    }
    return evidence

def _print_json(obj: Any) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    print(json.dumps(obj, ensure_ascii=False, indent=2))

def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(description="吸合声判定引擎（audio modality）")
    p.add_argument("--list", action="store_true", help="列出 5 个声音判定项")
    p.add_argument("--wav", help="待分析 wav 文件")
    p.add_argument("--item", help="item_id")
    p.add_argument("--start", type=float, default=None, help="录音窗口起点(s)")
    p.add_argument("--end", type=float, default=None, help="录音窗口终点(s)")
    p.add_argument("--min-confidence", type=float, default=DEFAULT_MIN_CONFIDENCE)
    p.add_argument("--items", default=None, help="audio_items.json 路径")
    args = p.parse_args(argv)

    if args.list:
        for it in load_items(args.items):
            print(f"{it['item_id']:<42} flow={it['flow_no']:<10} "
                  f"part={it['part']:<5} field={it['field']}")
        return 0
    if not args.wav:
        p.error("需要 --wav（或用 --list）")
    if not args.item:
        p.error("需要 --item")
    ev = judge(args.wav, item_id=args.item, start_s=args.start, end_s=args.end,
               min_confidence=args.min_confidence, items_path=args.items)
    _print_json(ev)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
