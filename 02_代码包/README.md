# AFH03 全部代码（TD + Python）

本包按两个可独立打开的工程组织，RAR 根目录为 `AFH03_all_code/`。

## 01_FPGA_TD/MIPI_RK_abc

- 安路 TD 工程：`fpga_prj.al`；源码 `uisrc/`、IP `al_ip/`、工具 `tools/`、约束/脚本、`fpga_prj_Runs/phy_1/` 工程描述。
- A+B+C 位流：`fpga_prj.bit`（4,850,310 B，MD5 `8FC876D87CD7DF97FF51DDB9B3C2EE5F`）；压缩版 `fpga_prj_compress.bit`（3,213,672 B，MD5 `20FEB1F5F2262FEA6A834A8ACFEA8DAF`）。
- 用安路 Tang Dynasty 打开 `fpga_prj.al`；位流只下载 SRAM，不烧 FLASH。

## 02_Python

- `soc_vision/`：kiosk UI、部位识别、灯/七段码/屏幕/问答判定。
- `engine/`：视觉规则、灯斑块、七段码、部位识别、总结。
- `engine_data/`：判据/题库/流程/视觉绑定/故障库/波形判据。
- `config/`、`ml/`、`tools/`、`systemd/`：配置、numpy MLP、工具、systemd 参考。
- 关键文件：
  - `soc_vision/ui_kiosk.py`
  - `soc_vision/g18_seg7.py`
  - `engine/vision_rules.py`
  - `engine/seg7_read.py`
  - `engine/part_recognizer.py`

## 运行环境

- RK3576 Debian 12（Python 3.11）；依赖见 `02_Python/requirements.txt`。
- 板端部署路径：`/home/rock/afh03_board_setup`、`/userdata/work2/engine`。
- 详细部署、回滚与实测证据见交接包 v4；本包不含相机原图、现场截图、交接包和大型数据集。
