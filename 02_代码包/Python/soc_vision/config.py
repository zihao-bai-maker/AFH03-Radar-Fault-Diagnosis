"""AFH03 SoC 侧视觉/AI 运行时的公共配置。

设计原则
--------
* 所有"现场相关"的数字（ROI、时基、V/div、HSV 阈值、模板路径）都放在
  JSON 配置文件里，代码里不写死，方便现场标定后只改 JSON。
* 每个 dataclass 都有 `from_dict`，缺字段就用默认值，不会因为配置少一项就崩。

配合文件：config/example_config.json
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROI = Tuple[int, int, int, int]          

def _get(d: Dict[str, Any], key: str, default: Any) -> Any:
    v = d.get(key, default)
    return default if v is None else v

def _roi(v: Any, default: ROI) -> ROI:
    if v is None:
        return default
    if len(v) != 4:
        raise ValueError("ROI 必须是 [x, y, w, h]，收到 %r" % (v,))
    return (int(v[0]), int(v[1]), int(v[2]), int(v[3]))

@dataclass
class VideoCfg:
    """视频源。

    source 取值：
      * "/dev/video22"   -> V4L2 设备（FPGA 经 MIPI，YUYV）
      * "/dev/video51"   -> V4L2 设备（imx415 -> rkisp，NV12）
      * "file:/path/x.mp4" 或直接给存在的文件路径
      * "img:/path/x.png"
      * "gst:<pipeline>"   -> 交给 OpenCV 的 GStreamer 后端
    """
    source: str = "/dev/video22"
    pixfmt: str = "YUYV"          
    width: int = 1920
    height: int = 1080
    fps: int = 30
    buffersize: int = 1
    raw_status: bool = True       
    warmup_frames: int = 5        
    reopen_after_fails: int = 30  
    enabled: bool = True          

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "VideoCfg":
        d = d or {}
        return VideoCfg(
            source=_get(d, "source", "/dev/video22"),
            pixfmt=str(_get(d, "pixfmt", "YUYV")).upper(),
            width=int(_get(d, "width", 1920)),
            height=int(_get(d, "height", 1080)),
            fps=int(_get(d, "fps", 30)),
            buffersize=int(_get(d, "buffersize", 1)),
            raw_status=bool(_get(d, "raw_status", True)),
            warmup_frames=int(_get(d, "warmup_frames", 5)),
            reopen_after_fails=int(_get(d, "reopen_after_fails", 30)),
            enabled=bool(_get(d, "enabled", True)),
        )

@dataclass
class ScopeCfg:
    """示波器波形识别标定。

    标定来源（必填 3 项，其余可自动估）：
      time_per_div_s : 示波器面板上的时基，例如 1ms/div -> 0.001
      volt_per_div_v : 垂直档位，例如 0.5V/div  -> 0.5
      probe_atten    : 探头衰减，×1 -> 1.0，×10 -> 10.0
    其余：
      h_div / v_div  : 屏幕格数（通常 10 x 8）
      px_per_div_x/y : 每格像素数；None 时用 roi 宽高 / 格数
      gnd_y_px       : 0V 基准线在 roi 内的像素 y（None -> 用波形均值当基准）
      wave_hsv_lo/hi : 波形颜色 HSV 范围（黄/青/品红），用于把波形从网格里分离
    """
    roi: ROI = (100, 100, 800, 600)
    enabled: bool = True
    model: str = ""                     
    time_per_div_s: float = 1e-3
    volt_per_div_v: float = 0.5
    probe_atten: float = 1.0
    h_div: float = 10.0
    v_div: float = 8.0
    grid_h_div_hint: Optional[float] = None   
    grid_subdiv: int = 1                      
    px_per_div_x: Optional[float] = None
    px_per_div_y: Optional[float] = None
    gnd_y_px: Optional[float] = None
    wave_hsv_lo: Tuple[int, int, int] = (20, 90, 120)     
    wave_hsv_hi: Tuple[int, int, int] = (40, 255, 255)
    invert_wave: bool = False      
    robust_percentile: bool = True  
    min_valid_col_ratio: float = 0.35
    bright_fallback: bool = True   

    

    

    expect_hz: Optional[float] = None         
    expect_hz_list: List[float] = field(default_factory=list)   
    expect_hz_tol_pct: float = 2.0            
    expect_hz_table: List[float] = field(default_factory=list)  

    

    
    source: str = "image"
    scpi_host: str = ""               
    scpi_port: int = 5555
    scpi_ch: int = 1
    scpi_timeout_s: float = 3.0
    scpi_retries: int = 2
    scpi_repeat: int = 1              
    scpi_read_wave: bool = True       
    scpi_every_n: int = 15            

    def nominal_list(self) -> List[float]:
        """生效的"正常频点"列表：白名单优先，其次单值，都没有则空。"""
        if self.expect_hz_list:
            return [float(v) for v in self.expect_hz_list if v]
        if self.expect_hz and self.expect_hz > 0:
            return [float(self.expect_hz)]
        return []

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "ScopeCfg":
        d = d or {}
        tbl = d.get("expect_hz_table", []) or []

        wl = (d.get("expect_hz_list") or d.get("normal_hz") or d.get("normal_hz_list") or [])
        if not isinstance(wl, (list, tuple)):
            wl = [wl]
        return ScopeCfg(
            roi=_roi(d.get("roi"), (100, 100, 800, 600)),
            enabled=bool(_get(d, "enabled", True)),
            model=str(_get(d, "model", "")),
            time_per_div_s=float(_get(d, "time_per_div_s", 1e-3)),
            volt_per_div_v=float(_get(d, "volt_per_div_v", 0.5)),
            probe_atten=float(_get(d, "probe_atten", 1.0)),
            h_div=float(_get(d, "h_div", 10.0)),
            v_div=float(_get(d, "v_div", 8.0)),
            grid_h_div_hint=(None if d.get("grid_h_div_hint") in (None, 0)
                             else float(d["grid_h_div_hint"])),
            grid_subdiv=max(1, int(_get(d, "grid_subdiv", 1))),
            px_per_div_x=(None if d.get("px_per_div_x") in (None, 0) else float(d["px_per_div_x"])),
            px_per_div_y=(None if d.get("px_per_div_y") in (None, 0) else float(d["px_per_div_y"])),
            gnd_y_px=(None if d.get("gnd_y_px") is None else float(d["gnd_y_px"])),
            wave_hsv_lo=tuple(_get(d, "wave_hsv_lo", (20, 90, 120))),
            wave_hsv_hi=tuple(_get(d, "wave_hsv_hi", (40, 255, 255))),
            invert_wave=bool(_get(d, "invert_wave", False)),
            robust_percentile=bool(_get(d, "robust_percentile", True)),
            min_valid_col_ratio=float(_get(d, "min_valid_col_ratio", 0.35)),
            bright_fallback=bool(_get(d, "bright_fallback", True)),
            expect_hz=(None if d.get("expect_hz") in (None, 0) else float(d["expect_hz"])),
            expect_hz_list=[float(v) for v in wl if v not in (None, 0, "")],
            expect_hz_tol_pct=float(_get(d, "expect_hz_tol_pct", 2.0)),
            expect_hz_table=[float(v) for v in tbl],
            source=str(_get(d, "source", "image")).lower(),
            scpi_host=str(_get(d, "scpi_host", "") or ""),
            scpi_port=int(_get(d, "scpi_port", 5555)),
            scpi_ch=max(1, int(_get(d, "scpi_ch", 1))),
            scpi_timeout_s=float(_get(d, "scpi_timeout_s", 3.0)),
            scpi_retries=max(0, int(_get(d, "scpi_retries", 2))),
            scpi_repeat=max(1, int(_get(d, "scpi_repeat", 1))),
            scpi_read_wave=bool(_get(d, "scpi_read_wave", True)),
            scpi_every_n=max(1, int(_get(d, "scpi_every_n", 15))),
        )

@dataclass
class LedItemCfg:
    """一个 LED 的判定配置。

    mode:
      "bright"  : 只看亮度（V 通道）相对基线的抬升 —— 白/黄/绿/红都可用，最稳
      "color"   : 只看指定的 HSV 色域命中比例 —— 适合"红/绿"区分
      "mixed"   : 亮度抬升 且 色域命中（默认）
    """
    name: str = "led0"
    roi: ROI = (100, 100, 40, 40)
    mode: str = "mixed"
    hsv_lo: Tuple[int, int, int] = (0, 0, 0)
    hsv_hi: Tuple[int, int, int] = (179, 255, 255)
    on_thr: float = 25.0        
    off_thr: float = 15.0       
    min_color_ratio: float = 0.15
    expect: Optional[bool] = None   

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LedItemCfg":
        return LedItemCfg(
            name=str(_get(d, "name", "led0")),
            roi=_roi(d.get("roi"), (100, 100, 40, 40)),
            mode=str(_get(d, "mode", "mixed")).lower(),
            hsv_lo=tuple(_get(d, "hsv_lo", (0, 0, 0))),
            hsv_hi=tuple(_get(d, "hsv_hi", (179, 255, 255))),
            on_thr=float(_get(d, "on_thr", 25.0)),
            off_thr=float(_get(d, "off_thr", 15.0)),
            min_color_ratio=float(_get(d, "min_color_ratio", 0.15)),
            expect=(None if d.get("expect") is None else bool(d["expect"])),
        )

@dataclass
class LedCfg:
    enabled: bool = True
    items: List[LedItemCfg] = field(default_factory=list)
    baseline_frames: int = 20     
    debounce_n: int = 3           
    use_fpga_status: bool = True  
    software_fallback: bool = True

    require_all_rois: bool = True     
    min_valid_rois: int = 1           
    max_roi_area_frac: float = 0.25   
    baseline_json: str = ""           

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "LedCfg":
        d = d or {}
        return LedCfg(
            enabled=bool(_get(d, "enabled", True)),
            items=[LedItemCfg.from_dict(x) for x in _get(d, "items", [])],
            baseline_frames=int(_get(d, "baseline_frames", 20)),
            debounce_n=int(_get(d, "debounce_n", 3)),
            use_fpga_status=bool(_get(d, "use_fpga_status", True)),
            software_fallback=bool(_get(d, "software_fallback", True)),
            require_all_rois=bool(_get(d, "require_all_rois", True)),
            min_valid_rois=int(_get(d, "min_valid_rois", 1)),
            max_roi_area_frac=float(_get(d, "max_roi_area_frac", 0.25)),
            baseline_json=str(_get(d, "baseline_json", "") or ""),
        )

@dataclass
class OcrItemCfg:
    """一个文本区域。

    engine:
      "template"  : 模板匹配（本机可跑，不依赖任何模型文件）—— 推荐先用
      "rknn_crnn" : CRNN+CTC 的 rknn 模型（推荐升级路线）
      "ppocr"     : PP-OCR det+rec（通用文本，最重）
    切分方式 split:
      "fixed"     : 按 fixed_chars 的等间距/标定框切分（≤20 字固定位置，最稳）
      "projection": 投影 + 连通域合并切分（位置不固定时用）
    """
    name: str = "text0"
    roi: ROI = (0, 0, 800, 120)
    engine: str = "template"
    split: str = "fixed"
    n_chars: int = 20
    fixed_boxes: List[List[int]] = field(default_factory=list)   
    fixed_chars: str = ""        
    char_size: Tuple[int, int] = (32, 32)   
    threshold: float = 0.55      

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "OcrItemCfg":
        return OcrItemCfg(
            name=str(_get(d, "name", "text0")),
            roi=_roi(d.get("roi"), (0, 0, 800, 120)),
            engine=str(_get(d, "engine", "template")).lower(),
            split=str(_get(d, "split", "fixed")).lower(),
            n_chars=int(_get(d, "n_chars", 20)),
            fixed_boxes=[list(map(int, b)) for b in _get(d, "fixed_boxes", [])],
            fixed_chars=str(_get(d, "fixed_chars", "")),
            char_size=(int(_get(d, "char_size", [32, 32])[0]), int(_get(d, "char_size", [32, 32])[1])),
            threshold=float(_get(d, "threshold", 0.55)),
        )

@dataclass
class OcrCfg:
    enabled: bool = True
    items: List[OcrItemCfg] = field(default_factory=list)
    template_npz: str = "models/cn_templates.npz"
    rknn_crnn_path: str = "models/crnn_ctc_20.rknn"
    charset_path: str = "models/charset_20.txt"
    ppocr_det_path: str = "models/ppocrv4_det.rknn"
    ppocr_rec_path: str = "models/ppocrv4_rec.rknn"
    ppocr_keys_path: str = "models/ppocr_keys_v1.txt"
    npu_core: int = 0            

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "OcrCfg":
        d = d or {}
        return OcrCfg(
            enabled=bool(_get(d, "enabled", True)),
            items=[OcrItemCfg.from_dict(x) for x in _get(d, "items", [])],
            template_npz=_get(d, "template_npz", "models/cn_templates.npz"),
            rknn_crnn_path=_get(d, "rknn_crnn_path", "models/crnn_ctc_20.rknn"),
            charset_path=_get(d, "charset_path", "models/charset_20.txt"),
            ppocr_det_path=_get(d, "ppocr_det_path", "models/ppocrv4_det.rknn"),
            ppocr_rec_path=_get(d, "ppocr_rec_path", "models/ppocrv4_rec.rknn"),
            ppocr_keys_path=_get(d, "ppocr_keys_path", "models/ppocr_keys_v1.txt"),
            npu_core=int(_get(d, "npu_core", 0)),
        )

@dataclass
class SinkCfg:
    stdout_json: bool = True
    file_path: str = ""                 
    serial_dev: str = ""                
    udp_host: str = ""                  
    udp_port: int = 5005
    print_every_n: int = 1              

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "SinkCfg":
        d = d or {}
        return SinkCfg(
            stdout_json=bool(_get(d, "stdout_json", True)),
            file_path=_get(d, "file_path", ""),
            serial_dev=_get(d, "serial_dev", ""),
            udp_host=_get(d, "udp_host", ""),
            udp_port=int(_get(d, "udp_port", 5005)),
            print_every_n=int(_get(d, "print_every_n", 1)),
        )

@dataclass
class AppCfg:
    video: VideoCfg = field(default_factory=VideoCfg)
    scope: ScopeCfg = field(default_factory=ScopeCfg)
    led: LedCfg = field(default_factory=LedCfg)
    ocr: OcrCfg = field(default_factory=OcrCfg)
    sink: SinkCfg = field(default_factory=SinkCfg)
    display: bool = True
    display_scale: float = 0.5
    scope_every_n: int = 3       
    ocr_every_n: int = 5
    fps_limit: float = 0.0       
    fpga_magic: int = 0xA5C35A00

    led_indicator_path: str = "/sys/class/leds/work/brightness"
    led_indicator_on_pass: bool = True   

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "AppCfg":
        d = d or {}
        return AppCfg(
            video=VideoCfg.from_dict(d.get("video", {})),
            scope=ScopeCfg.from_dict(d.get("scope", {})),
            led=LedCfg.from_dict(d.get("led", {})),
            ocr=OcrCfg.from_dict(d.get("ocr", {})),
            sink=SinkCfg.from_dict(d.get("sink", {})),
            display=bool(_get(d, "display", True)),
            display_scale=float(_get(d, "display_scale", 0.5)),
            scope_every_n=max(1, int(_get(d, "scope_every_n", 3))),
            ocr_every_n=max(1, int(_get(d, "ocr_every_n", 5))),
            fps_limit=float(_get(d, "fps_limit", 0.0)),
            fpga_magic=int(_get(d, "fpga_magic", 0xA5C35A00)),
            led_indicator_path=str(_get(d, "led_indicator_path",
                                        "/sys/class/leds/work/brightness")),
            led_indicator_on_pass=bool(_get(d, "led_indicator_on_pass", True)),
        )

def load_config(path: str) -> AppCfg:
    """读 JSON 配置。路径不存在时抛 FileNotFoundError（不要静默用默认值）。"""
    if not os.path.isfile(path):
        raise FileNotFoundError("配置文件不存在: %s" % path)
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    return AppCfg.from_dict(raw)

def resolve_path(path: str, base_dir: str = "") -> str:
    """相对路径按 base_dir 解析（默认取当前工作目录）。"""
    if not path or os.path.isabs(path):
        return path
    base = base_dir or os.getcwd()
    return os.path.normpath(os.path.join(base, path))
