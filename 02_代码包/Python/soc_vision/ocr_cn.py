"""≤20 个汉字的识别 —— 三条路线对比 + 可运行骨架。

三条路线（详细对比见 `项目_SoC侧AI方案.md` §3）
---------------------------------------------------
A. **模板匹配**（本文件 `TemplateMatcher`）
   零训练、零模型文件、只用 numpy+cv2，当天就能跑。
   适用：字数固定(≤20)、字体固定、相机位置固定、光照可控 —— 正是本项目的场景。
   代价：换字体/换角度/换光照要重做模板；类间相似字（如 日/曰、未/末）需要多张模板。

B. **CRNN + CTC 自训练**（`RknnCrnn` 骨架 + `tools/` 里的训练数据合成思路）
   1~2 M 参数、单模型、固定宽度输入、20 类 + blank，NPU 上 1~3 ms。
   需要 PC 侧 PyTorch 训练 + RKNN-Toolkit2 转换，工作量 1~2 天。
   是本项目"正确率与鲁棒性兼顾"的推荐升级路线。

C. **PP-OCR (det+rec) 转 RKNN**（`PpocrEngine` 骨架，仅接口与文件清单）
   通用性最好（任意文本行、6000+ 汉字），但需要 det+rec 两个模型 + 字典，
   模型转换/量化链路长，低分辨率小字上量化掉点明显。
   只有"要识别的字会变、数量不固定"时才值得上。

推荐：**先用 A 跑通闭环 → 同时用 B 替换识别核 → 除非需求变成"任意文本"否则不做 C**。

关键：无论哪条路线，"切字"都比"认字"更容易出错
----------------------------------------------------
汉字是左右/上下结构，垂直投影法会把"们/树/湖"这类字切成两半。
所以：
* 字数固定、位置固定 -> 用 `split="fixed"`（标定时就登记每个字的框），最稳；
* 位置会漂 -> 用 `split="projection"`，本文件实现了"投影 + 按最小间隙合并到 n_chars"
  的策略（`_merge_to_count`），专门处理左右结构被切开的问题。
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

try:
    import cv2
except Exception:                                           
    cv2 = None                                              

from .config import OcrCfg, OcrItemCfg, ROI, resolve_path

@dataclass
class CharHit:
    ch: str
    score: float
    box: Tuple[int, int, int, int]

    def to_dict(self) -> Dict[str, Any]:
        return {"ch": self.ch, "score": round(float(self.score), 3), "box": list(self.box)}

@dataclass
class OcrItemResult:
    name: str
    text: str
    conf: float
    engine: str
    chars: List[CharHit] = field(default_factory=list)
    ok: bool = True
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "text": self.text, "conf": round(float(self.conf), 3),
                "engine": self.engine, "ok": self.ok, "message": self.message,
                "chars": [c.to_dict() for c in self.chars]}

def to_binary_char(patch_bgr: np.ndarray, size: Tuple[int, int] = (32, 32)) -> np.ndarray:
    """把单字区域归一化成"字=255、底=0"的二值图（size=(w,h)）。"""
    if patch_bgr is None or patch_bgr.size == 0:
        return np.zeros((size[1], size[0]), np.uint8)
    if patch_bgr.ndim == 3:
        g = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY)
    else:
        g = patch_bgr
    g = cv2.resize(g, (int(size[0]), int(size[1])), interpolation=cv2.INTER_AREA)
    g = cv2.GaussianBlur(g, (3, 3), 0)
    try:
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    except Exception:
        _, b = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)

    if float(b.mean()) > 127.0:
        b = 255 - b
    return b

def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    x = a.astype(np.float32).ravel()
    y = b.astype(np.float32).ravel()
    x = x - x.mean()
    y = y - y.mean()
    nx = float(np.sqrt((x * x).sum()))
    ny = float(np.sqrt((y * y).sum()))
    if nx < 1e-6 or ny < 1e-6:
        return 0.0
    return float((x * y).sum() / (nx * ny))

class TemplateMatcher:
    """模板库格式（npz）:
        chars : shape (K,) 字符串数组（每个模板对应的汉字）
        imgs  : shape (K, H, W) uint8，字=255 的二值图
        size  : shape (2,) [w, h]
    用 `tools/make_templates.py` 生成。
    """

    def __init__(self, npz_path: str):
        if not os.path.isfile(npz_path):
            raise FileNotFoundError(
                "模板库不存在: %s\n用 tools/make_templates.py 从标定图生成" % npz_path)
        z = np.load(npz_path, allow_pickle=False)
        self.chars: List[str] = [str(c) for c in z["chars"]]
        self.imgs: np.ndarray = z["imgs"]
        self.size: Tuple[int, int] = (int(z["size"][0]), int(z["size"][1])) \
            if "size" in z.files else (self.imgs.shape[2], self.imgs.shape[1])
        self._gray = None
        if "grays" in z.files:
            self._gray = z["grays"]

    def score(self, ch_bin: np.ndarray, k: int) -> float:
        s1 = _ncc(ch_bin, self.imgs[k])
        if self._gray is None:
            return s1
        s2 = _ncc(cv2.GaussianBlur(ch_bin, (3, 3), 0), self._gray[k])
        return 0.65 * s1 + 0.35 * s2

    def match(self, ch_bin: np.ndarray) -> Tuple[str, float]:
        if not self.chars:
            return "?", 0.0
        scores: Dict[str, float] = {}
        for k, c in enumerate(self.chars):
            v = self.score(ch_bin, k)
            if v > scores.get(c, -2.0):
                scores[c] = v
        best = max(scores.items(), key=lambda kv: kv[1])
        return best[0], float(best[1])

class RknnCrnn:
    """CRNN+CTC 的 RKNN 推理骨架。

    期望模型（rknn_model_zoo 风格）：
      输入  : 1 x H x W x 1  uint8（H=32，W=字符数*16~32，按你的训练配置）
      输出  : 1 x T x (num_classes+1)，num_classes = 字符集大小，最后一个是 blank
    字符集文件 charset_path：一行一个字符（顺序必须与训练时一致）。

    注意：init_runtime 前要保证 /usr/lib/librknnrt.so 版本与 whl 匹配
    （bash install_ai_env.sh 自检里会实测一次）。
    """

    def __init__(self, model_path: str, charset_path: str, input_hw: Tuple[int, int] = (32, 320),
                 npu_core: int = 0):
        from rknnlite.api import RKNNLite            
        self.rknn = RKNNLite(verbose=False)
        if self.rknn.load_rknn(model_path) != 0:
            raise RuntimeError("load_rknn 失败: %s" % model_path)
        core = [RKNNLite.NPU_CORE_0, RKNNLite.NPU_CORE_1,
                RKNNLite.NPU_CORE_2, RKNNLite.NPU_CORE_AUTO][min(3, max(0, npu_core))]
        if self.rknn.init_runtime(core_mask=core) != 0:
            raise RuntimeError("init_runtime 失败（librknnrt 版本或 NPU 驱动问题）")
        with open(charset_path, "r", encoding="utf-8") as f:
            self.charset = [ln.rstrip("\n") for ln in f if ln.rstrip("\n") != ""]
        self.input_hw = input_hw
        self.blank = len(self.charset)

    def infer_line(self, line_bgr: np.ndarray) -> Tuple[str, float, List[float]]:
        """整行图 -> (字符串, 平均置信度, 逐字符置信度)。"""
        h, w = self.input_hw
        if line_bgr.ndim == 3:
            g = cv2.cvtColor(line_bgr, cv2.COLOR_BGR2GRAY)
        else:
            g = line_bgr
        g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)

        g = cv2.normalize(g, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
        if float(g.mean()) > 127.0:
            g = 255 - g
        inp = g.reshape(1, h, w, 1)
        outs = self.rknn.inference(inputs=[inp])
        if not outs:
            return "", 0.0, []
        logits = np.asarray(outs[0])
        if logits.ndim == 3:
            logits = logits[0]
        return self._ctc_greedy(logits)

    def _ctc_greedy(self, logits: np.ndarray) -> Tuple[str, float, List[float]]:

        z = logits.astype(np.float64)
        z = z - z.max(axis=-1, keepdims=True)
        e = np.exp(z)
        p = e / np.maximum(e.sum(axis=-1, keepdims=True), 1e-12)
        ids = p.argmax(axis=-1)
        conf = p.max(axis=-1)
        out: List[str] = []
        cfs: List[float] = []
        prev = -1
        for t, k in enumerate(ids):
            if k != prev and k != self.blank and k < len(self.charset):
                out.append(self.charset[k])
                cfs.append(float(conf[t]))
            prev = int(k)
        text = "".join(out)
        mean = float(np.mean(cfs)) if cfs else 0.0
        return text, mean, cfs

    def release(self) -> None:
        try:
            self.rknn.release()
        except Exception:
            pass

class PpocrEngine:
    """PP-OCR (det + rec) RKNN 骨架 —— 只给接口与文件清单，不做完整实现。

    需要的文件（Rockchip rknn_model_zoo 的 ppocr 例子里有 ONNX + 转换脚本）：
      models/ppocrv4_det.rknn        检测(DB)  输入 1x480x640x3
      models/ppocrv4_rec.rknn        识别(SVTR)输入 1x48x320x3
      models/ppocr_keys_v1.txt       6623 行字典（含中文）
      models/ppocr_rec_meta.json     含 img_shape / mean / std（zoo 的转换脚本会生成）

    流程：
      1. det: resize 到 640x480 -> 归一化 -> 推理 -> 输出概率图 (1,1,H,W)
      2. 二值化(0.3) -> cv2.findContours -> 得到文本框 -> 四点排序
      3. 每个框用 cv2.getPerspectiveTransform + warpPerspective 抠成水平文本行
      4. rec: 每行 resize 到 320x48 -> 归一化 -> 推理 -> (1,T,6626) -> CTC greedy
      5. 用 ppocr_keys_v1.txt 做 id->char 映射（index 0 是 blank）
    """

    REQUIRED = ("models/ppocrv4_det.rknn", "models/ppocrv4_rec.rknn",
                "models/ppocr_keys_v1.txt", "models/ppocr_rec_meta.json")

    def __init__(self, det_path: str, rec_path: str, keys_path: str,
                 meta_path: str = "", npu_core: int = 0):
        self.det_path, self.rec_path, self.keys_path, self.meta_path = \
            det_path, rec_path, keys_path, meta_path
        self.npu_core = npu_core
        self._ready = False

    def prepare(self) -> None:
        missing = [p for p in (self.det_path, self.rec_path, self.keys_path,
                               self.meta_path) if p and not os.path.isfile(p)]
        if missing:
            raise FileNotFoundError(
                "PP-OCR 还缺文件：\n  " + "\n  ".join(missing) +
                "\n获取方式见 项目_SoC侧AI方案.md §3.4（Rockchip rknn_model_zoo 的 "
                "examples/ppocr，需在 Linux 上用 RKNN-Toolkit2 转换）")
        self._ready = True

    def recognize(self, bgr: np.ndarray) -> List[Tuple[str, float, Tuple[int, int, int, int]]]:
        raise NotImplementedError(
            "PP-OCR 的 det+rec 后处理较长，本项目不推荐直接用（见文档 §3 的路线对比）。"
            "若确需通用文本识别，按下述步骤实现："
            "det->findContours->perspective->rec->CTC greedy；"
            "本文件的 to_binary_char / _ncc / RknnCrnn._ctc_greedy 可直接复用。")

def _binarize_roi(roi_bgr: np.ndarray) -> np.ndarray:
    """整块 ROI 二值化，字=255。"""
    if roi_bgr.ndim == 3:
        g = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    else:
        g = roi_bgr
    g = cv2.GaussianBlur(g, (3, 3), 0)
    try:
        _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    except Exception:
        _, b = cv2.threshold(g, 127, 255, cv2.THRESH_BINARY)
    if float(b.mean()) > 127.0:
        b = 255 - b
    return b

def _projection_segments(binimg: np.ndarray, min_col_px: int = 1) -> List[Tuple[int, int]]:
    """垂直投影切出候选字列 [(x0, x1)]。"""
    proj = (binimg > 0).sum(axis=0).astype(np.int32)
    if proj.max() <= 0:
        return []
    col_on = proj > min_col_px
    segs: List[Tuple[int, int]] = []
    s = None
    for x, on in enumerate(col_on):
        if on and s is None:
            s = x
        elif not on and s is not None:
            segs.append((s, x))
            s = None
    if s is not None:
        segs.append((s, len(col_on)))
    return [t for t in segs if t[1] - t[0] >= 2]

def _merge_to_count(segs: List[Tuple[int, int]], n: int) -> List[Tuple[int, int]]:
    """把相邻段按"间隙最小优先"合并，直到剩下 n 段（解决左右结构被切开）。"""
    segs = list(segs)
    while len(segs) > n:
        gaps = [segs[i + 1][0] - segs[i][1] for i in range(len(segs) - 1)]
        i = int(np.argmin(gaps))
        segs[i] = (segs[i][0], segs[i + 1][1])
        del segs[i + 1]
    if len(segs) < n and segs:

        while len(segs) < n:
            widths = [b - a for a, b in segs]
            i = int(np.argmax(widths))
            a, b = segs[i]
            m = (a + b) // 2
            segs[i:i + 1] = [(a, m), (m, b)]
    return segs

def split_fixed(item: OcrItemCfg) -> List[Tuple[int, int, int, int]]:
    """固定格子切分。有 fixed_boxes 用标定框，否则按 roi 宽度等分 n_chars。"""
    _, _, w, h = item.roi
    if item.fixed_boxes:
        return [tuple(int(v) for v in b) for b in item.fixed_boxes]     
    n = max(1, item.n_chars)
    cw = w / float(n)
    return [(int(round(i * cw)), 0, int(round(cw)), h) for i in range(n)]

def split_projection(roi_bgr: np.ndarray, n_chars: int,
                     min_col_px: int = 1) -> List[Tuple[int, int, int, int]]:
    """投影 + 合并到 n_chars 个框。返回 [(x, y, w, h)]（roi 内坐标）。"""
    b = _binarize_roi(roi_bgr)
    h = b.shape[0]

    rows = np.flatnonzero((b > 0).sum(axis=1) > 0)
    if rows.size:
        y0, y1 = int(rows[0]), int(rows[-1]) + 1
    else:
        y0, y1 = 0, h
    b2 = b[y0:y1, :]
    segs = _projection_segments(b2, min_col_px)
    if not segs:
        return []
    segs = _merge_to_count(segs, max(1, n_chars))
    return [(a, y0, b - a, y1 - y0) for a, b in segs]

class CnRecognizer:
    """汉字识别门面：按每个 item 的 engine 选后端。"""

    def __init__(self, cfg: OcrCfg, base_dir: str = ""):
        self.cfg = cfg
        self.base_dir = base_dir or os.getcwd()
        self._tmpl: Optional[TemplateMatcher] = None
        self._crnn: Optional[RknnCrnn] = None
        self._ppocr: Optional[PpocrEngine] = None

    def tmpl(self) -> TemplateMatcher:
        if self._tmpl is None:
            self._tmpl = TemplateMatcher(resolve_path(self.cfg.template_npz, self.base_dir))
        return self._tmpl

    def crnn(self) -> RknnCrnn:
        if self._crnn is None:
            self._crnn = RknnCrnn(resolve_path(self.cfg.rknn_crnn_path, self.base_dir),
                                  resolve_path(self.cfg.charset_path, self.base_dir),
                                  npu_core=self.cfg.npu_core)
        return self._crnn

    def ppocr(self) -> PpocrEngine:
        raise NotImplementedError(self._PPOCR_HINT)

    _PPOCR_HINT = (
        "PP-OCR 路线本项目不推荐直接用（见 项目_SoC侧AI方案.md §3.4）。"
        "若确需通用文本识别：\n"
        "  1) 只在 Linux(x86_64) 上用 RKNN-Toolkit2 2.3.0 转换 det/rec 两个 ONNX；\n"
        "  2) 板上用 rknn_model_zoo/examples/ppocr 的后处理：\n"
        "     det -> findContours -> 四点透视 -> rec -> CTC greedy -> ppocr_keys_v1.txt\n"
        "  3) 本文件的 to_binary_char / _ncc / RknnCrnn._ctc_greedy 可直接复用。")

    def recognize_item(self, bgr: np.ndarray, item: OcrItemCfg) -> OcrItemResult:
        x, y, w, h = item.roi
        H, W = bgr.shape[:2]
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(W, x + w), min(H, y + h)
        if x1 - x0 < 4 or y1 - y0 < 4:
            return OcrItemResult(item.name, "", 0.0, item.engine, ok=False,
                                 message="ROI 越界或太小")
        roi = bgr[y0:y1, x0:x1]

        boxes: List[Tuple[int, int, int, int]]
        if item.split == "fixed":
            boxes = split_fixed(item)
        else:
            boxes = split_projection(roi, item.n_chars)
        if not boxes:
            return OcrItemResult(item.name, "", 0.0, item.engine, ok=False,
                                 message="切字失败：ROI 里没有文字像素（阈值/ROI 不对？）")

        engine = item.engine
        try:
            if engine == "template":
                return self._recognize_template(roi, boxes, item)
            if engine == "rknn_crnn":
                return self._recognize_crnn(roi, boxes, item)
            if engine == "ppocr":
                raise NotImplementedError(self._PPOCR_HINT)
        except FileNotFoundError as e:
            return OcrItemResult(item.name, "", 0.0, engine, ok=False, message=str(e))
        except Exception as e:                              
            return OcrItemResult(item.name, "", 0.0, engine, ok=False,
                                 message="%s: %s" % (type(e).__name__, e))
        return OcrItemResult(item.name, "", 0.0, engine, ok=False,
                             message="未知 engine: %s" % engine)

    def _recognize_template(self, roi: np.ndarray, boxes, item: OcrItemCfg) -> OcrItemResult:
        tm = self.tmpl()
        hits: List[CharHit] = []
        for (bx, by, bw, bh) in boxes:
            patch = roi[max(0, by):by + bh, max(0, bx):bx + bw]

            cb = to_binary_char(patch, tm.size)
            ch, sc = tm.match(cb)
            if sc < item.threshold:
                ch = "?"
            hits.append(CharHit(ch, sc, (bx, by, bw, bh)))
        text = "".join(h.ch for h in hits)
        conf = float(np.mean([h.score for h in hits])) if hits else 0.0
        msg = ""
        if item.fixed_chars and len(item.fixed_chars) == len(text):
            wrong = [i for i, (a, b) in enumerate(zip(text, item.fixed_chars)) if a != b]
            if wrong:
                msg = "与 fixed_chars 不符的位: %s" % wrong
        return OcrItemResult(item.name, text, conf, "template", hits, True, msg)

    def _recognize_crnn(self, roi: np.ndarray, boxes, item: OcrItemCfg) -> OcrItemResult:
        """CRNN 用"整行"输入：把盒子首尾连成一条水平带，按 pitch 归一化宽度。"""
        eng = self.crnn()
        x_start = min(b[0] for b in boxes)
        x_end = max(b[0] + b[2] for b in boxes)
        y_start = min(b[1] for b in boxes)
        y_end = max(b[1] + b[3] for b in boxes)
        line = roi[y_start:y_end, x_start:x_end]
        if line.size == 0:
            return OcrItemResult(item.name, "", 0.0, "rknn_crnn", ok=False,
                                 message="行区域为空")
        text, conf, cfs = eng.infer_line(line)
        hits = [CharHit(c, (cfs[i] if i < len(cfs) else conf), (0, 0, 0, 0))
                for i, c in enumerate(text)]
        return OcrItemResult(item.name, text, conf, "rknn_crnn", hits, True)

    def recognize(self, bgr: np.ndarray) -> List[OcrItemResult]:
        return [self.recognize_item(bgr, it) for it in self.cfg.items]

def draw_result(bgr: np.ndarray, cfg: OcrCfg, results: Sequence[OcrItemResult]) -> np.ndarray:
    if cv2 is None:                                         
        return bgr
    out = bgr.copy()
    by_name = {it.name: it for it in cfg.items}
    for r in results:
        it = by_name.get(r.name)
        if it is None:
            continue
        x, y, w, h = it.roi
        cv2.rectangle(out, (x, y), (x + w, y + h), (255, 128, 0), 2)
        label = "%s: %s (%.2f)" % (r.name, r.text, r.conf)
        cv2.putText(out, label, (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255, 128, 0), 2)
    return out

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="汉字识别（模板匹配路线）单图调试")
    ap.add_argument("--config", required=True, help="JSON 配置")
    ap.add_argument("--image", required=True, help="一张图")
    ap.add_argument("--item", help="只跑某个 item（默认全部）")
    ap.add_argument("--draw", help="标注结果写到这个 png")
    a = ap.parse_args(argv)

    from .config import AppCfg
    with open(a.config, "r", encoding="utf-8") as f:
        app = AppCfg.from_dict(json.load(f))
    img = cv2.imread(a.image, cv2.IMREAD_COLOR)
    if img is None:
        print("读不到图: %s" % a.image)
        return 1
    rec = CnRecognizer(app.ocr, os.path.dirname(os.path.abspath(a.config)))
    items = [it for it in app.ocr.items if (a.item is None or it.name == a.item)]
    res = [rec.recognize_item(img, it) for it in items]
    print(json.dumps([r.to_dict() for r in res], ensure_ascii=False, indent=2))
    if a.draw:
        cv2.imwrite(a.draw, draw_result(img, app.ocr, res))
        print("标注图 -> %s" % a.draw)
    return 0 if all(r.ok for r in res) else 2

if __name__ == "__main__":                                  
    raise SystemExit(main())
