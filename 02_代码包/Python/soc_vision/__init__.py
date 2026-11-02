"""AFH03 (RK3576 / Debian 12 / Python 3.11) SoC 侧视觉 + AI 运行时。

模块map：
    config        配置（标定值都放 JSON）
    video_source  取帧（V4L2 YUYV/NV12 / 文件 / 图片 / GStreamer / 合成测试图）
    fpga_status   解 FPGA 塞在 CSI-2 首行的状态字（魔数 0xA5C35A00），PCIe BAR 备选
    led_detect    LED 亮灭判定（软件兜底 + 与 FPGA 判决融合）
    scope_wave    示波器波形 -> 频率(Hz) / 峰峰值(Vpp)
    ocr_cn        ≤20 汉字识别（模板匹配可跑 / CRNN-RKNN 骨架 / PP-OCR 接口）
    result_sink   结果输出（stdout JSON / 文件 / 串口 / UDP）
    main_runtime  主循环（可直接 python3 -m soc_vision.main_runtime 运行）

依赖：numpy + opencv(cv2) 必需；rknnlite 只在用到 NPU 时导入。
安装：bash install_ai_env.sh
"""

__version__ = "1.0.0"
