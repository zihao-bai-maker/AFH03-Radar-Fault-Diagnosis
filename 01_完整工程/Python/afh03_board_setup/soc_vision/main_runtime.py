#!/usr/bin/env python3
"""AFH03 SoC 侧运行时主循环：取帧 -> (FPGA 状态字) -> LED 判定 -> 波形识别 -> 汉字识别 -> 输出/显示。

用法（在板子上）：
    cd /home/rock/afh03_board_setup
    python3 -m soc_vision.main_runtime --config config/example_config.json
    python3 -m soc_vision.main_runtime --config config/example_config.json --no-display
    python3 -m soc_vision.main_runtime --config config/cfg.json --source /dev/video51 --duration 30
    python3 -m soc_vision.main_runtime --config config/cfg.json --calibrate-led 30 \
            --write-baseline config/led_baseline.json      # LED 全灭时采基线

设计取舍
--------
* 每帧只做 LED（便宜）；波形与汉字按 `scope_every_n` / `ocr_every_n` 隔帧跑，省 CPU。
* 任一模块报错不会终止主循环，错误进 `err` 字段（现场调试时最容易出的就是路径/ROI 写错）。
* FPGA 首行状态字只要拿得到原始 YUYV 就每帧解，解不出只记 `fpga.present=false`。
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from typing import Any, Dict, List, Optional

import numpy as np

try:
    import cv2
except Exception as e:                                      
    print("需要 cv2：先跑 bash install_ai_env.sh   (%s)" % e)
    raise SystemExit(1)

from .config import AppCfg, load_config, resolve_path
from .fpga_status import FpgaStatus, scan_raw_yuyv
from .led_detect import LedBaseline, LedDetector
from .ocr_cn import CnRecognizer, draw_result as draw_ocr
from .result_sink import ResultSink
from .scope_wave import ScopeResult, analyze_scope_frame, draw_result as draw_scope
from .scpi_scope import check_scope
from .video_source import VideoSource, guess_fpga_node, list_video_nodes

_STOP = {"flag": False, "signum": 0}

def _on_signal(signum, _frame) -> None:
    _STOP["flag"] = True
    _STOP["signum"] = signum
    print("\n[RUN] 收到信号 %d：准备停止取流并释放设备..." % signum)

def _install_signal_handlers() -> None:
    for s in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(s, _on_signal)
        except (ValueError, OSError):     
            pass

def _write_led_indicator(path: str, scpi_verdict, on_pass: bool, prev) -> int:
    """把判定结果写到板载 LED 亮度文件（PASS -> 亮）。返回当前状态 1/0/-1(未用)。

    只在状态变化时写文件（/sys 写多了没必要；也避免每帧刷同一个值）。
    """
    if not path:
        return -1
    if scpi_verdict is None or not getattr(scpi_verdict, "ok", False):
        state = 0                      
    else:
        passed = (scpi_verdict.verdict == "PASS")
        state = 1 if (passed == on_pass) else 0
    if state != prev:
        try:
            with open(path, "w") as f:
                f.write("1" if state else "0")
        except OSError as e:
            print("[WARN] 写板载 LED 失败 %s: %s" % (path, e))
            return -1
    return state

def overlay(bgr: np.ndarray, cfg: AppCfg, fps: float, led_states,
            scope_res: Optional[ScopeResult], ocr_results, fpga: Optional[FpgaStatus],
            err: str = "", scpi_verdict=None) -> np.ndarray:
    out = bgr

    verdict = ""
    label = ""
    if scpi_verdict is not None:
        verdict, label = scpi_verdict.verdict, scpi_verdict.label
    elif scope_res is not None and scope_res.verdict:
        verdict, label = scope_res.verdict, scope_res.label
    if verdict:
        col = {"PASS": (0, 255, 0), "FAIL": (0, 0, 255)}.get(verdict, (0, 165, 255))
        txt = "%s / %s" % (verdict, label or "-")
        if scpi_verdict is not None and scpi_verdict.ok:
            txt += "   f=%s  Vpp=%.3fV  (%+.2f%%)" % (
                scpi_verdict.freq_hz / 1e6 if scpi_verdict.freq_hz >= 1e6
                else scpi_verdict.freq_hz,
                scpi_verdict.vpp_v, scpi_verdict.freq_dev_pct)
        cv2.rectangle(out, (0, 0), (out.shape[1], 46), col, -1)
        cv2.putText(out, txt, (10, 33), cv2.FONT_HERSHEY_SIMPLEX, 0.95, (0, 0, 0), 2)

    for i, (it, st) in enumerate(zip(cfg.led.items, led_states or [])):
        x, y, w, h = it.roi
        color = (0, 255, 0) if st.on else (0, 0, 255)
        cv2.rectangle(out, (x, y), (x + w, y + h), color, 2)
        cv2.putText(out, "%s %s" % (it.name, "ON" if st.on else "OFF"),
                    (x, max(16, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    if scope_res is not None:
        out = draw_scope(out, cfg.scope, scope_res)
    if ocr_results:
        out = draw_ocr(out, cfg.ocr, ocr_results)
    if fpga is not None and fpga.present:
        cv2.putText(out, "FPGA lit=%s" % ("".join("1" if b else "0" for b in fpga.lit_bits())),
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 200, 0), 2)
    cv2.putText(out, "FPS %.1f" % fps, (10, out.shape[0] - 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    if err:
        cv2.putText(out, err[:90], (10, 52), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (0, 0, 255), 2)
    return out

def run(cfg: AppCfg, args: argparse.Namespace) -> int:
    base_dir = os.path.dirname(os.path.abspath(args.config))

    use_scpi = (cfg.scope.source in ("scpi", "both")) and bool(cfg.scope.scpi_host)
    src = VideoSource(cfg.video)
    if not cfg.video.enabled:

        
        video_ok = False
        print("[INIT] video.enabled=false：不打开任何视频设备（纯 SCPI 模式）")
    else:
        video_ok = src.open()
    if not video_ok:
        if use_scpi or not cfg.video.enabled:
            if cfg.video.enabled:
                print("[WARN] 打不开视频源 %s —— SCPI 主判据模式继续运行（本次无图像/无 OCR）"
                      % cfg.video.source)
                print("       （预期情况：没插相机 / FPGA 还没换 bit 时，波形判定仍可用）")
        else:
            print("[ERR] 打不开视频源 %s" % cfg.video.source)
            nodes = [d for d, _ in list_video_nodes()]
            print("      板上现有节点: %s" % (nodes or "(无)"))
            print("      试试: --source %s" % (guess_fpga_node() or "/dev/video22"))
            print("      纯 SCPI 模式: --scope-source scpi --scope-host <示波器IP> --no-video")
            return 1
    print("[INIT] 视频源 %s  pixfmt=%s%s" % (cfg.video.source, cfg.video.pixfmt,
                                             "" if video_ok else "  (未打开)"))
    if video_ok and cfg.video.source.startswith("/dev/video"):
        print("[INIT] 实际协商 %dx%d" % (cfg.video.width, cfg.video.height))

    scpi_verdict = None
    nominal = cfg.scope.nominal_list()
    if use_scpi:
        print("[INIT] SCPI 主判据: %s:%d CH%d 白名单=%s 容差=±%.3g%% 每 %d 帧查一次"
              % (cfg.scope.scpi_host, cfg.scope.scpi_port, cfg.scope.scpi_ch,
                 ", ".join("%g" % v for v in nominal), cfg.scope.expect_hz_tol_pct,
                 cfg.scope.scpi_every_n))
    elif cfg.scope.source in ("scpi", "both"):
        print("[WARN] scope.source=%s 但没配 scpi_host，退回图像法" % cfg.scope.source)

    led_ind_path = cfg.led_indicator_path or ""
    if led_ind_path and not os.path.exists(led_ind_path):
        print("[WARN] 板载 LED 指示文件不存在: %s（跳过指示）" % led_ind_path)
        led_ind_path = ""
    if led_ind_path:
        print("[INIT] 板载 LED 指示: %s（PASS -> %s）"
              % (led_ind_path, "亮" if cfg.led_indicator_on_pass else "灭"))

    baseline = None
    bl_path = args.baseline or ""
    if bl_path and os.path.isfile(bl_path):
        with open(bl_path, "r", encoding="utf-8") as f:
            baseline = LedBaseline.from_json(json.load(f))
        print("[INIT] LED 基线 <- %s" % bl_path)
    led = LedDetector(cfg.led, baseline) if cfg.led.enabled else None
    if led is not None:
        print("[INIT] LED ROI %d 个: %s" %
              (len(cfg.led.items), ", ".join(i.name for i in cfg.led.items)))

    ocr = CnRecognizer(cfg.ocr, base_dir) if cfg.ocr.enabled else None
    if ocr is not None:
        print("[INIT] OCR item %d 个, engine=%s" %
              (len(cfg.ocr.items),
               ",".join(sorted({i.engine for i in cfg.ocr.items}))))
        for it in cfg.ocr.items:
            if it.engine == "template":
                p = resolve_path(cfg.ocr.template_npz, base_dir)
                if not os.path.isfile(p):
                    print("       [WARN] 模板库不存在: %s（先用 tools/make_templates.py 生成）" % p)

    sink = ResultSink(cfg.sink)
    print("[INIT] 输出: stdout=%s file=%s serial=%s udp=%s" %
          (cfg.sink.stdout_json, cfg.sink.file_path or "-",
           cfg.sink.serial_dev or "-",
           ("%s:%d" % (cfg.sink.udp_host, cfg.sink.udp_port)) if cfg.sink.udp_host else "-"))

    win = "AFH03 Vision"
    display = cfg.display and not args.no_display
    if display:
        try:
            cv2.namedWindow(win, cv2.WINDOW_NORMAL)
            cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_AUTOSIZE)
        except Exception as e:
            print("[WARN] 打不开显示窗口(%s)，转为无界面模式" % e)
            display = False

    if args.calibrate_led > 0 and led is not None:
        print("[CAL] 采 %d 帧 LED 基线（请确认所有目标 LED 已熄灭）..." % args.calibrate_led)
        frames: List[np.ndarray] = []
        for _ in range(args.calibrate_led):
            ok, fr = src.read()
            if ok and fr is not None:
                frames.append(fr.bgr)
            time.sleep(0.05)
        if frames:
            bl = led.calibrate(frames)
            print("[CAL] " + json.dumps(bl.to_json(), ensure_ascii=False))
            if args.write_baseline:
                with open(args.write_baseline, "w", encoding="utf-8") as f:
                    json.dump(bl.to_json(), f, ensure_ascii=False, indent=2)
                print("[CAL] 基线已写 %s" % args.write_baseline)
        else:
            print("[CAL] 没采到帧，跳过")

    t0 = time.time()
    last = t0
    frames = 0
    fps = 0.0
    fail = 0
    err = ""
    scope_res: Optional[ScopeResult] = None
    ocr_results = []
    led_states = []
    fpga: Optional[FpgaStatus] = None
    n_err = 0

    led_ind_state = None
    _install_signal_handlers()
    print("[RUN] 开始，Ctrl+C 退出\n")
    try:
        while True:
            if _STOP["flag"]:
                print("[RUN] 收到信号，退出循环")
                break
            fr = None
            if video_ok:
                ok, fr = src.read()
                if not ok or fr is None:
                    fail += 1
                    if src.need_reopen():
                        print("[WARN] 连续 %d 帧失败，重开设备..." % fail)
                        if not src.reopen():
                            print("[ERR] 重开失败，退出")
                            break
                        fail = 0
                    time.sleep(0.02)
                    continue
                fail = 0
            else:

                time.sleep(0.2)
            frames += 1

            if use_scpi and (frames == 1 or frames % cfg.scope.scpi_every_n == 0):
                try:
                    scpi_verdict = check_scope(
                        host=cfg.scope.scpi_host, port=cfg.scope.scpi_port,
                        ch=cfg.scope.scpi_ch, nominal_list=nominal,
                        tol_pct=cfg.scope.expect_hz_tol_pct,
                        timeout=cfg.scope.scpi_timeout_s, retries=cfg.scope.scpi_retries,
                        repeat=cfg.scope.scpi_repeat, read_wave=cfg.scope.scpi_read_wave)
                except Exception as e:
                    n_err += 1
                    scpi_verdict = None
                    err = "scpi: %s: %s" % (type(e).__name__, e)

            if fr is None:

                now = time.time()
                if now - last >= 0.5:
                    fps = frames / max(1e-6, now - t0)
                    last = now
                res: Dict[str, Any] = {"ts": round(now, 3), "frame": frames,
                                       "fps": round(fps, 2), "vision": False}
                if scpi_verdict is not None:
                    res["scope_scpi"] = scpi_verdict.to_dict()
                    res["verdict"] = scpi_verdict.verdict
                    res["label"] = scpi_verdict.label
                res["led_indicator"] = _write_led_indicator(
                    led_ind_path, scpi_verdict, cfg.led_indicator_on_pass, led_ind_state)
                if err:
                    res["err"] = err
                sink.emit(res)
                if args.duration > 0 and (now - t0) >= args.duration:
                    print("[RUN] 到达 --duration %.1fs，退出" % args.duration)
                    break
                continue

            if cfg.video.raw_status and fr.raw:
                try:
                    fpga = scan_raw_yuyv(fr.raw)
                except Exception as e:
                    fpga = None
                    err = "fpga_status: %s" % e

            try:
                if led is not None:
                    led_states = led.detect(fr.bgr, fpga)
            except Exception as e:
                n_err += 1
                err = "led: %s: %s" % (type(e).__name__, e)

            if cfg.scope.enabled and frames % cfg.scope_every_n == 0:
                try:
                    scope_res = analyze_scope_frame(fr.bgr, cfg.scope)
                except Exception as e:
                    n_err += 1
                    err = "scope: %s: %s" % (type(e).__name__, e)

            if ocr is not None and frames % cfg.ocr_every_n == 0:
                try:
                    ocr_results = ocr.recognize(fr.bgr)
                except Exception as e:
                    n_err += 1
                    err = "ocr: %s: %s" % (type(e).__name__, e)

            now = time.time()
            if now - last >= 0.5:
                fps = (frames - 0) / max(1e-6, now - t0)
                last = now

            res: Dict[str, Any] = {
                "ts": round(now, 3), "frame": frames, "fps": round(fps, 2),
                "led": {s.name: bool(s.on) for s in led_states},
                "led_score": {s.name: round(float(s.score), 1) for s in led_states},
                "led_source": (led_states[0].source if led_states else ""),
            }
            if scope_res is not None:
                res["scope"] = scope_res.to_dict()
            if ocr_results:
                res["ocr"] = {r.name: r.text for r in ocr_results if r.ok}
                res["ocr_conf"] = {r.name: round(float(r.conf), 3) for r in ocr_results if r.ok}
            if fpga is not None and fpga.present:
                res["fpga"] = {"frame_cnt": fpga.frame_cnt, "n_lit": fpga.n_lit,
                               "lit": fpga.lit_bits(), "layout": fpga.layout}

            if scpi_verdict is not None:
                res["scope_scpi"] = scpi_verdict.to_dict()
                res["verdict"] = scpi_verdict.verdict
                res["label"] = scpi_verdict.label
            elif scope_res is not None and (scope_res.verdict or scope_res.label):

                res["verdict"] = scope_res.verdict
                res["label"] = scope_res.label
                res["verdict_source"] = "image"
            res["led_indicator"] = _write_led_indicator(
                led_ind_path, scpi_verdict, cfg.led_indicator_on_pass, led_ind_state)
            led_ind_state = res["led_indicator"]
            if err:
                res["err"] = err
            sink.emit(res)

            if display:
                vis = overlay(fr.bgr, cfg, fps, led_states, scope_res, ocr_results, fpga,
                              err, scpi_verdict)
                if cfg.display_scale and cfg.display_scale != 1.0:
                    vis = cv2.resize(vis, None, fx=cfg.display_scale, fy=cfg.display_scale)
                try:
                    cv2.imshow(win, vis)
                    k = cv2.waitKey(1) & 0xFF
                    if k == ord("q"):
                        break
                    if k == ord("s") and args.save_dir:
                        os.makedirs(args.save_dir, exist_ok=True)
                        p = os.path.join(args.save_dir, "frame_%06d.png" % frames)
                        cv2.imwrite(p, fr.bgr)
                        print("[SAVE] %s" % p)
                except cv2.error as e:
                    print("[WARN] 显示失败，转无界面: %s" % e)
                    display = False

            if args.save_every > 0 and frames % args.save_every == 0 and args.save_dir:
                os.makedirs(args.save_dir, exist_ok=True)
                p = os.path.join(args.save_dir, "auto_%06d.png" % frames)
                cv2.imwrite(p, fr.bgr)

            if cfg.fps_limit > 0:
                dt = 1.0 / cfg.fps_limit - (time.time() - now)
                if dt > 0:
                    time.sleep(dt)
            if args.duration > 0 and (time.time() - t0) >= args.duration:
                print("[RUN] 到达 --duration %.1fs，退出" % args.duration)
                break
    except KeyboardInterrupt:
        print("\n[RUN] Ctrl+C 退出")
    finally:

        src.release()
        time.sleep(0.3)          
        sink.close()
        if led_ind_path:
            try:                 
                with open(led_ind_path, "w") as f:
                    f.write("0")
            except OSError:
                pass
        if display:
            try:
                cv2.destroyAllWindows()
            except Exception:
                pass

    print("[EXIT] 共 %d 帧，%.1fs，模块内异常 %d 次" % (frames, time.time() - t0, n_err))
    return 0

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="AFH03 SoC 侧视觉/AI 运行时")
    ap.add_argument("--config", required=True, help="JSON 配置（见 config/example_config.json）")
    ap.add_argument("--source", help="覆盖视频源，例如 /dev/video22 或 /dev/video51")
    ap.add_argument("--pixfmt", help="覆盖像素格式 YUYV/NV12")
    ap.add_argument("--no-display", action="store_true", help="不开窗口（headless）")
    ap.add_argument("--duration", type=float, default=0.0, help="跑多少秒后自动退出（0=一直跑）")
    ap.add_argument("--save-dir", default="", help="按 s 或 --save-every 存原始帧的目录")
    ap.add_argument("--save-every", type=int, default=0, help="每 N 帧存一张原始帧")
    ap.add_argument("--calibrate-led", type=int, default=0, metavar="N",
                    help="采 N 帧 LED 全灭基线")
    ap.add_argument("--baseline", default="", help="读取已保存的 LED 基线 JSON")
    ap.add_argument("--write-baseline", default="", help="把本次标定的 LED 基线写到这里")

    ap.add_argument("--scope-source", choices=["image", "scpi", "both"],
                    help="波形判据来源：scpi=示波器直读（推荐）/ image=相机图像法 / both")
    ap.add_argument("--scope-host", default="", help="示波器 IP（SCPI，TCP 5555）")
    ap.add_argument("--scope-port", type=int, default=0, help="SCPI 端口，默认 5555")
    ap.add_argument("--scope-ch", type=int, default=0, choices=[0, 1, 2], help="示波器通道")
    ap.add_argument("--scope-nominal", default="",
                    help="正常频点白名单，逗号分隔，如 20000000,40000000")
    ap.add_argument("--scope-tol-pct", type=float, default=0.0, help="频率容差 %%（默认 1）")
    ap.add_argument("--no-led-indicator", action="store_true",
                    help="不写板载 LED 指示（/sys/class/leds/work/brightness）")
    ap.add_argument("--no-video", action="store_true",
                    help="完全不打开视频设备（纯 SCPI 模式，自启动低负载）")
    return ap

def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print("[ERR] 读配置失败: %s" % e)
        return 1
    if args.source:
        cfg.video.source = args.source
    if args.pixfmt:
        cfg.video.pixfmt = args.pixfmt.upper()
    if args.no_display:
        cfg.display = False

    if args.scope_source:
        cfg.scope.source = args.scope_source
    if args.scope_host:
        cfg.scope.scpi_host = args.scope_host
        if not args.scope_source and cfg.scope.source == "image":
            cfg.scope.source = "scpi"          
    if args.scope_port:
        cfg.scope.scpi_port = args.scope_port
    if args.scope_ch:
        cfg.scope.scpi_ch = args.scope_ch
    if args.scope_nominal:
        vals = []
        for p in args.scope_nominal.replace(";", ",").split(","):
            p = p.strip()
            if p:
                try:
                    vals.append(float(p))
                except ValueError:
                    print("[WARN] 忽略无法解析的频点: %s" % p)
        if vals:
            cfg.scope.expect_hz_list = vals
    if args.scope_tol_pct:
        cfg.scope.expect_hz_tol_pct = args.scope_tol_pct
    if args.no_led_indicator:
        cfg.led_indicator_path = ""
    if args.no_video:
        cfg.video.enabled = False
    return run(cfg, args)

if __name__ == "__main__":                                  
    raise SystemExit(main())
