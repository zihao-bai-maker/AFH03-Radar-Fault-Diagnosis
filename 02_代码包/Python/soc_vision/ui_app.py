#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ui_app.py —— AFH03 **面板 LED 判定界面**（按用户收敛后的规格：拍一张 → 大字结论 + 一行依据）。

给用户的输出只有两样（其余都是后台保障）
----------------------------------------
```
        ✅ 正常                      或者        ❌ 故障
        依据：3 颗灯全亮 → 供电正常               依据：控制灯不亮 → 供电差错
```
* 大字结论：`✅ 正常` / `❌ 故障` / `⚠ 未判定`（三态，**未标定/证据不足绝不伪装成"正常"或"故障"**）
* 一行依据（如"控制灯不亮"、"故障红灯亮"、"ROI 未标定 → 无法判定"）

保留的准确性保障（**不是复杂度**，全部在后台）
----------------------------------------------
* 按**部件类型**套规则（`config/led_rules.json`，红灯在不同部件语义相反）
* **防误检门**：ROI 越界/半径超界/灯数与规则不符/未标定 → 未判定
* **过曝 + 颜色联合判据**：点亮 LED 会过曝偏白，用"各通道相对暗环的增量"判色
* **按钮≠灯**：`通`/`断` 方按钮/拨杆自发光弱且形状非圆 → 排除
* **朝向归一**：横拍（宽>高）自动右转 90°（真值照片 4 张如此，且**无 EXIF**）
* **迟滞 + 时间去抖**；**FPGA 状态字优先**（软件值并列）；**"未标定→未判定"**

用法
----
    # 板端实时界面（相机 + 触摸；拍照按钮存图与判定）
    python3 -m soc_vision.ui_app --part PS_KONG --calib config/led_calib.json
    # 无相机自检（把一张照片当画面渲染出界面 PNG，用于验证版式与结论）
    python3 -m soc_vision.ui_app --self-test /data/local/tmp/led_truth/IMG_x.jpg --part PS_KONG --out /tmp/ui.png
    # 纯离线判一张照片（打印结论）
    python3 -m soc_vision.ui_app --judge /path/photo.jpg --part PS_KONG
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np                                                   

try:
    import cv2
except Exception:                                                    
    cv2 = None

from soc_vision.cjk_text import draw_text, backend as cjk_backend, install_cv2_puttext_patch  
from soc_vision import led_panel as LP                                                
from soc_vision.led_panel import Calib, PanelDetector, fit_long, orient_normalize      
from soc_vision.led_rules import RuleBook, VERDICT_OK, VERDICT_BAD, VERDICT_UNK         

C_BG = (28, 30, 34)
C_CARD = (44, 47, 52)
C_OK = (80, 200, 90)
C_BAD = (60, 60, 230)
C_UNK = (170, 170, 170)
C_TXT = (238, 238, 238)
C_DIM = (165, 168, 175)
C_ACC = (255, 190, 70)

class Touch:
    """读 /dev/input/event3（1024×600 电阻/电容屏），只关心 ABS_X/ABS_Y + BTN_TOUCH/ABS_PRESSURE。"""

    EV_ABS, EV_KEY, EV_SYN = 3, 1, 0
    ABS_X, ABS_Y, ABS_PRESSURE = 0, 1, 24
    BTN_TOUCH = 330
    STRUCT = "llHHi"                       

    def __init__(self, dev: str = "/dev/input/event3", max_x: int = 1024, max_y: int = 600,
                 win_w: int = 1024, win_h: int = 600):
        self.dev = dev
        self.max_x, self.max_y = max_x, max_y
        self.win_w, self.win_h = win_w, win_h
        self.fd = -1
        self.x = self.y = -1
        self.touching = False
        self._ev = []

    def open(self) -> bool:
        try:
            self.fd = os.open(self.dev, os.O_RDONLY | os.O_NONBLOCK)
            return True
        except OSError as e:
            print("[touch] 打不开 %s：%s（用 --no-touch 进入离线模式）" % (self.dev, e))
            return False

    def poll(self):
        """返回本轮"点击抬指"的屏幕坐标 (x,y) 或 None。"""
        if self.fd < 0:
            return None
        click = None
        try:
            data = os.read(self.fd, 24 * 64)
        except (BlockingIOError, OSError):
            return None
        n = len(data) // 24
        for i in range(n):
            _s, _us, typ, code, val = struct.unpack(self.STRUCT, data[i * 24:(i + 1) * 24])
            if typ == self.EV_ABS and code == self.ABS_X:
                self.x = int(val)
            elif typ == self.EV_ABS and code == self.ABS_Y:
                self.y = int(val)
            elif typ == self.EV_KEY and code == self.BTN_TOUCH:
                if val == 1:
                    self.touching = True
                elif val == 0 and self.touching:
                    self.touching = False
                    if self.x >= 0 and self.y >= 0:
                        click = (int(self.x * self.win_w / max(1, self.max_x)),
                                 int(self.y * self.win_h / max(1, self.max_y)))
        return click

def _card(img, x0, y0, x1, y1, color=C_CARD, alpha: float = 0.88):
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(img.shape[1], int(x1)), min(img.shape[0], int(y1))
    if x1 <= x0 or y1 <= y0:
        return
    roi = img[y0:y1, x0:x1].astype(np.float32)
    img[y0:y1, x0:x1] = (roi * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)

def verdict_style(v: str):
    if v == VERDICT_OK:
        return C_OK, "✅"
    if v == VERDICT_BAD:
        return C_BAD, "❌"
    return C_UNK, "⚠"

def draw_panel(W: int, H: int, frame_bgr, vobj, info: dict, lamp_rows: list,
               scope: dict, meta: dict, btn_rect, toast: str = "") -> "np.ndarray":
    """画整块界面：顶部大字结论 + 一行依据；左侧画面；右侧灯明细；底部拍照按钮。"""
    img = np.full((H, W, 3), C_BG, np.uint8)
    col, icon = verdict_style(vobj.get("verdict", VERDICT_UNK))

    _card(img, 0, 0, W, 96, color=col, alpha=0.22)
    draw_text(img, "%s %s" % (icon, vobj.get("verdict", VERDICT_UNK)), (22, 74), scale=2.5,
              color=col, th=2)
    draw_text(img, meta.get("clock", ""), (W - 250, 36), scale=0.62, color=C_DIM)
    draw_text(img, "第 %d 帧" % meta.get("frame", 0), (W - 250, 66), scale=0.62, color=C_DIM)
    draw_text(img, (vobj.get("reason") or "(无依据)")[:46], (22, 126), scale=0.78, color=C_TXT)

    px0, py0, px1, py1 = 16, 142, int(W * 0.60), H - 96
    _card(img, px0 - 4, py0 - 4, px1 + 4, py1 + 4, color=(20, 22, 26), alpha=1.0)
    if frame_bgr is not None:
        fh, fw = frame_bgr.shape[:2]
        k = min((px1 - px0) / max(1, fw), (py1 - py0) / max(1, fh))
        disp = cv2.resize(frame_bgr, (max(1, int(fw * k)), max(1, int(fh * k))), interpolation=cv2.INTER_AREA)
        oy = py0 + ((py1 - py0) - disp.shape[0]) // 2
        ox = px0 + ((px1 - px0) - disp.shape[1]) // 2
        img[oy:oy + disp.shape[0], ox:ox + disp.shape[1]] = disp
        work_long = max(fw, fh)
        for row in lamp_rows:
            if row.get("x", -1) < 0:
                continue
            c = C_OK if row.get("on") else (C_UNK if row.get("on") is None else (90, 90, 96))
            cx = int(ox + row["x"] * k); cy = int(oy + row["y"] * k); rr = max(4, int(row.get("r", 8) * k))
            cv2.circle(img, (cx, cy), rr, c, 2)
            draw_text(img, "%s %s" % (row["name"][:6], "ON" if row.get("on") else
                                      ("?" if row.get("on") is None else "OFF")),
                      (cx - rr, cy - rr - 4), scale=0.42, color=c)

    rx0, ry0 = int(W * 0.62), 142
    _card(img, rx0 - 8, ry0 - 4, W - 12, ry0 + 24 * (max(1, len(lamp_rows)) + 1) + 44,
          color=C_CARD, alpha=0.75)
    draw_text(img, "灯明细（%d 颗）" % len(lamp_rows), (rx0, ry0 + 20), scale=0.6, color=C_ACC)
    y = ry0 + 46
    for r in lamp_rows:
        st = "ON" if r.get("on") else ("未判定" if r.get("on") is None else "OFF")
        c = C_OK if r.get("on") else (C_UNK if r.get("on") is None else C_DIM)
        src = r.get("source", "sw")
        draw_text(img, "%-10s %-6s Δ%6.1f  %s" % (str(r.get("name"))[:10], st,
                                                  float(r.get("delta", 0.0)), src),
                  (rx0, y), scale=0.5, color=c)
        y += 24
    if not lamp_rows:
        draw_text(img, "无灯数据", (rx0, y), scale=0.5, color=C_DIM)

    sy = ry0 + 24 * (max(1, len(lamp_rows)) + 1) + 64
    _card(img, rx0 - 8, sy, W - 12, sy + 58, color=C_CARD, alpha=0.75)
    sv = (scope or {}).get("verdict", "ERROR")
    sc = C_OK if sv == "PASS" else (C_BAD if sv == "FAIL" else C_UNK)
    draw_text(img, "波形 %s" % sv, (rx0, sy + 26), scale=0.62, color=sc)
    sm = (scope or {}).get("message") or "未接示波器"
    draw_text(img, str(sm)[:44], (rx0, sy + 50), scale=0.42, color=C_DIM)

    _card(img, 0, H - 78, W, H, color=(18, 20, 24), alpha=1.0)
    draw_text(img, str(meta.get("status", ""))[:70], (16, H - 30), scale=0.5, color=C_DIM)
    draw_text(img, "中文:%s" % cjk_backend(), (16, H - 8), scale=0.42, color=(130, 132, 138))
    bx0, by0, bx1, by1 = btn_rect
    cv2.rectangle(img, (bx0, by0), (bx1, by1), C_ACC, -1)
    draw_text(img, "📷 拍 照 判 定", (bx0 + 34, by0 + 44), scale=1.0, color=(20, 20, 20), th=2)
    if toast:
        draw_text(img, toast[:52], (bx0 - 420, by0 + 44), scale=0.6, color=C_OK)
    return img

def judge(bgr, part: str, book: RuleBook, calib, det: PanelDetector, fpga_lit=None,
          allow_auto: bool = False):
    """一张图 -> (vobj, info)。朝向归一 + 标定/自动两条路径都在这里。

    **默认要求标定**（lead 规格第 3 条）：没有 ROI 就输出「未判定」，绝不硬判，避免广视角假阳性；
    `--auto` 才允许无标定自动判定（用于演示与离线复现真值）。
    """
    bgr2, rotated = orient_normalize(bgr)
    bgr2 = fit_long(bgr2, LP.WORK_LONG)
    if not part:
        return {"verdict": VERDICT_UNK, "reason": "未指定部件（用 --part 或先做丝印识别）→ 未判定",
                "bad_lamps": [], "lamps": []}, {"rotated": rotated, "rows": []}
    if not calib and not allow_auto:
        return ({"verdict": VERDICT_UNK,
                 "reason": "未标定（没有该部件的 ROI）→ 未判定；先跑 tools/led_calibrate.py 标定，或用 --auto 演示",
                 "bad_lamps": [], "lamps": []},
                {"rotated": rotated, "rows": [], "gate": {"ok": False,
                                                          "reason": "无标定 ROI（默认拒绝出判定）"}})
    v, info = LP.analyze(bgr2, book, part, calib, fpga_lit=fpga_lit, det=det)
    d = v.to_dict()
    d["reason"] = v.reason
    d["banner"] = v.banner()
    rows = []
    for st in d.get("lamps", []):
        rows.append({"name": st["name"], "on": st["on"], "delta": st["delta"],
                     "source": st["source"], "x": st.get("x", -1), "y": st.get("y", -1),
                     "r": st.get("r", 0), "reason": st.get("reason", "")})

    if not any(r["x"] >= 0 for r in rows):
        for i, c in enumerate((info.get("candidates") or [])[:8]):
            rows.append({"name": "灯%d" % (i + 1), "on": True, "delta": c["delta"],
                         "source": "sw", "x": c["x"], "y": c["y"], "r": c["r"], "reason": "自动检出"})
    info["rows"] = rows
    info["rotated"] = rotated
    return d, info

def scpi_verdict(args) -> dict:
    host = str(getattr(args, "scope_host", "") or "").strip()
    if not host:
        return {"verdict": "ERROR", "message": "未配置示波器（--scope-host / AFH03_SCOPE_HOST）"}
    try:
        from soc_vision import scpi_scope
        nominal = [float(x) for x in str(args.scope_nominal).replace(";", ",").split(",") if x.strip()]
        v = scpi_scope.check_scope(host=host, port=int(args.scope_port), ch=1,
                                   nominal_list=nominal or [20e6, 40e6],
                                   tol_pct=float(args.scope_tol_pct))
        return {"verdict": v.verdict, "label": v.label, "freq_hz": v.freq_hz,
                "freq_dev_pct": v.freq_dev_pct, "vpp_v": v.vpp_v,
                "message": v.reason if not v.ok else
                "%.6g Hz  偏差%+.3f%%  Vpp %.3f V" % (v.freq_hz, v.freq_dev_pct, v.vpp_v)}
    except Exception as e:                                             
        return {"verdict": "ERROR", "message": "SCPI 异常：%s" % e}

def build_parser():
    ap = argparse.ArgumentParser(description="AFH03 面板 LED 判定界面（拍一张 → 正常/故障 + 依据）")
    ap.add_argument("--part", default=os.environ.get("AFH03_PART", ""), help="部件 id（规则表里的 id）")
    ap.add_argument("--config", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                                     "config", "example_config.json"))
    ap.add_argument("--rules", default="")
    ap.add_argument("--calib", default=os.environ.get("AFH03_CALIB", ""), help="标定 JSON（推荐；没有则自动模式）")
    ap.add_argument("--auto", action="store_true",
                    help="无标定也走自动判定（**演示/离线复现用**）；默认无 ROI 一律输出「未判定」")
    ap.add_argument("--device", default="/dev/video22")
    ap.add_argument("--win-w", type=int, default=1024)
    ap.add_argument("--win-h", type=int, default=600)
    ap.add_argument("--touch", default="/dev/input/event3")
    ap.add_argument("--touch-max-x", type=int, default=1024)
    ap.add_argument("--touch-max-y", type=int, default=600)
    ap.add_argument("--no-touch", action="store_true")
    ap.add_argument("--no-camera", action="store_true")
    ap.add_argument("--shots-dir", default="/userdata/afh03_shots")
    ap.add_argument("--window", default="AFH03-LED")
    ap.add_argument("--auto-save-every", type=float, default=0.0,
                    help=">0 时每隔 N 秒自动判定并存一次（连拍自动判定）")
    ap.add_argument("--scope-host", default=os.environ.get("AFH03_SCOPE_HOST", ""))
    ap.add_argument("--scope-port", type=int, default=int(os.environ.get("AFH03_SCOPE_PORT", "5555")))
    ap.add_argument("--scope-nominal", default=os.environ.get("AFH03_SCOPE_NOMINAL", "20000000,40000000"))
    ap.add_argument("--scope-tol-pct", type=float, default=float(os.environ.get("AFH03_SCOPE_TOL_PCT", "1.0")))
    ap.add_argument("--self-test", default="", help="把这张照片当画面渲染界面 PNG（不需要相机）")
    ap.add_argument("--judge", default="", help="只判这一张照片，打印结论")
    ap.add_argument("--out", default="/tmp/afh03_ui.png", help="--self-test 的输出 PNG")
    ap.add_argument("--duration", type=float, default=0.0, help="实时模式跑 N 秒后退出（0=一直跑）")
    return ap

def save_shot(shots_dir: str, frame, annot, vobj, info, scope) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    d = os.path.join(shots_dir, ts)
    os.makedirs(d, exist_ok=True)
    if frame is not None:
        cv2.imwrite(os.path.join(d, "full.jpg"), frame)
    if annot is not None:
        cv2.imwrite(os.path.join(d, "annot.jpg"), annot)
    meta = {"ts": ts, "verdict": vobj.get("verdict"), "reason": vobj.get("reason"),
            "bad_lamps": vobj.get("bad_lamps"), "part": vobj.get("name"),
            "lamps": vobj.get("lamps"), "scope": scope,
            "gate": (info or {}).get("gate"), "rotated": (info or {}).get("rotated"),
            "cjk_backend": cjk_backend()}
    with open(os.path.join(d, "verdict.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return d

def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    install_cv2_puttext_patch()
    book = RuleBook.load(a.rules or None)
    calib = Calib.load(a.calib) if a.calib and os.path.isfile(a.calib) else None
    det = PanelDetector(calib)
    part = a.part or (next(iter(calib.parts), "") if calib else "")

    print("[ui_app] 启动: 部件=%s 标定=%s 中文后端=%s 相机=%s 自动模式=%s 拍照目录=%s"
          % (part or "<未指定>", (a.calib if calib else "<无(未标定)>"), cjk_backend(),
             ("关" if a.no_camera else a.device), bool(a.auto), a.shots_dir), flush=True)

    if a.judge:
        bgr = cv2.imread(a.judge, cv2.IMREAD_COLOR)
        if bgr is None:
            print("读不到图 %s" % a.judge)
            return 1
        v, info = judge(bgr, part, book, calib, det, allow_auto=a.auto)
        print("%s\n依据：%s" % (("✅ 正常" if v["verdict"] == VERDICT_OK else
                                "❌ 故障" if v["verdict"] == VERDICT_BAD else "⚠ 未判定"), v["reason"]))
        print(json.dumps({k: v.get(k) for k in ("verdict", "bad_lamps", "confidence")},
                         ensure_ascii=False))
        for r in info["rows"]:
            print("   %-12s on=%-5s delta=%7.1f src=%s" % (r["name"], r["on"], r["delta"], r["source"]))
        return 0

    if a.self_test:
        bgr = cv2.imread(a.self_test, cv2.IMREAD_COLOR)
        if bgr is None:
            print("读不到图 %s" % a.self_test)
            return 1
        v, info = judge(bgr, part, book, calib, det, allow_auto=a.auto)
        canvas = draw_panel(a.win_w, a.win_h, bgr, v, info, info["rows"], scpi_verdict(a),
                            {"clock": time.strftime("%Y-%m-%d %H:%M:%S"), "frame": 1,
                             "status": "自检渲染（照片：%s）" % os.path.basename(a.self_test)},
                            btn_rect=(a.win_w - 320, a.win_h - 66, a.win_w - 16, a.win_h - 10))
        cv2.imwrite(a.out, canvas)
        print("已写出界面 PNG: %s" % a.out)
        print("结论: %s\n依据: %s" % (v["verdict"], v["reason"]))
        return 0

    cap = None
    if not a.no_camera:
        cap = cv2.VideoCapture(a.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            print("[warn] 打不开相机 %s（用 --no-camera 只渲染界面）" % a.device)
            cap = None
    touch = None
    if not a.no_touch:
        touch = Touch(a.touch, a.touch_max_x, a.touch_max_y, a.win_w, a.win_h)
        if not touch.open():
            touch = None
    btn = (a.win_w - 320, a.win_h - 66, a.win_w - 16, a.win_h - 10)
    n_frames = 0
    toast, toast_until = "", 0.0
    v, info = {"verdict": VERDICT_UNK, "reason": "等待画面…", "lamps": []}, {"rows": []}
    scope = {"verdict": "ERROR", "message": "未查询"}
    t0, last_scope, last_auto = time.time(), 0.0, 0.0
    win = a.window
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    try:
        cv2.resizeWindow(win, a.win_w, a.win_h)
    except Exception:                                                  
        pass
    while True:
        frame = None
        if cap is not None:
            ok, frame = cap.read()
            if not ok:
                frame = None
        if frame is None:
            frame = np.full((a.win_h, a.win_w, 3), 20, np.uint8)
            if not getattr(a, "_warned_no_frame", False):
                print("[warn] 相机 %s 没给出帧（被别的服务占用？用 tools/afh03_video22_lock.sh status 查），"
                      "界面继续以黑底渲染" % a.device, flush=True)
                a._warned_no_frame = True
        n_frames += 1
        if n_frames % 5 == 1 or not info.get("rows"):
            v, info = judge(frame, part, book, calib, det, allow_auto=a.auto)
        now = time.time()
        if now - last_scope > 5.0:
            scope = scpi_verdict(a)
            last_scope = now
        clock = time.strftime("%Y-%m-%d %H:%M:%S")
        canvas = draw_panel(a.win_w, a.win_h, frame if cap is not None else None, v, info,
                            info.get("rows", []), scope,
                            {"clock": clock, "frame": n_frames,
                             "status": "%s | %s | %s" % (part or "未指定部件",
                                                         (info.get("gate") or {}).get("reason", "")[:40],
                                                         "已标定" if calib else "未标定(自动模式)")},
                            btn_rect=btn, toast=(toast if now < toast_until else ""))
        cv2.imshow(win, canvas)
        key = cv2.waitKey(1) & 0xFF
        click = touch.poll() if touch else None
        do_cap = (click is not None and btn[0] <= click[0] <= btn[2] and btn[1] <= click[1] <= btn[3])
        if key in (27, ord("q")):
            break
        if key in (ord(" "), ord("c"), ord("s")):
            do_cap = True
        if a.auto_save_every > 0 and (now - last_auto) >= a.auto_save_every:
            do_cap, last_auto = True, now
        if do_cap:
            d = save_shot(a.shots_dir, frame if cap is not None else None, canvas, v, info, scope)
            toast = "已保存 %s（%s）" % (d, v.get("verdict"))
            toast_until = now + 4.0
            print("[shot] %s  结论=%s  依据=%s" % (d, v.get("verdict"), v.get("reason")))
        if a.duration > 0 and (now - t0) >= a.duration:
            break
    if cap is not None:
        cap.release()
    cv2.destroyAllWindows()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
