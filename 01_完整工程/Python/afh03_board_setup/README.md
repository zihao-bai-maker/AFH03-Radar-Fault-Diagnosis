# afh03_board_setup —— RK3576(Debian 12) 侧视觉/AI 落地包

> 目标板：AFH03 / MLK-AFC03（RK3576 + PH1A90），Debian 12，kernel 6.1.99，**Python 3.11.2**，
> RKNPU 用户态已装（`/usr/lib/librknnrt.so`），GStreamer 1.22.9，XFCE 桌面（DSI-1 800×1280）。
> 出厂系统**没有** numpy / opencv / rknnlite，**连 pip 都没有** —— 本包负责离线装齐并跑起来。

## 当前状态（两行分开写，别混）

| 项 | 状态 | 证据 |
|---|---|---|
| **模拟验收（示波器模拟器闭环）** | ✅ **已过** | PC `PASS=53 FAIL=0`；板端 `PASS=52 FAIL=0`（`afh03_work\soc\log_scpi_sim.txt`） |
| **真机验收（真 DS2302A）** | ⏳ **待验**（用户身边暂时没有示波器） | 步骤见下面「真机验收」一节，断言不用改 |

其余已实测通过：板端环境安装、`verify_env.sh` 全绿、**板端离线自测 95/95**、`/dev/video22` **真实画面**抓帧存证、
DSI 屏 `cv2.imshow` 开窗+截屏、NPU 实机 `init_runtime`。

## 30 秒上手

```bash
# 0) 把厂家 07_异构方案 里的 7 个 whl 拷到板子 /home/rock/whls/
#    （出厂镜像没有 pip，先用本包自带的离线 wheel 安装器把 pip 铺进去，见下）

# 1) 装环境（离线，自带 sha256 校验；装完自动自检 + NPU 实测）
sudo bash install_ai_env.sh --wheel-dir /home/rock/whls

# 2) 自检（装了什么、NPU 通不通、有哪些视频节点、显示有没有）
bash verify_env.sh --model /home/rock/yolo/yolov5s_relu.rknn

# 3) 抓一帧看看（FPGA 走 /dev/video22 YUYV；imx415 走 /dev/video51 NV12）
bash capture_probe.sh -d /dev/video22 --raw   # 会打印 [REAL]/[DUMMY] 判据

# 4) 波形判定：主判据 = 直接读示波器（LAN/SCPI）
python3 -m soc_vision.scpi_scope --host 192.168.1.100 --nominal 20000000,40000000 --tol-pct 1
#   不知道示波器 IP 就自动找：
python3 -m soc_vision.scpi_scope --scan 192.168.1.0/24

# 5) 主循环（无界面 / 带 DSI 窗口显示）
python3 -m soc_vision.main_runtime --config config/example_config.json --no-display --duration 30
python3 -m soc_vision.main_runtime --config config/example_config.json     # XFCE 里开窗口
```

## 波形判定的判据（用户明确要求）

* 信号：**雷达 → RIGOL DS2302A**，波形是**方波**
* 规则：**20 MHz 与 40 MHz = 正常 → `PASS`/`NORMAL`；其余 Hz = 不正常 → `FAIL`/`ABNORMAL`**
* 读取方式：**直接读示波器数据（LAN/SCPI，TCP 5555）为主判据**；
  相机拍屏的 `scope_wave.py` 图像法**降级为交叉校验/离线能力**（代码与自测都保留，没改坏）
* 容差写在 `config` 里：`scope.expect_hz_list = [20000000, 40000000]`、`expect_hz_tol_pct = 1.0`
* 读不到（网线没插 / 示波器不在线 / 超时 / 示波器自己测不出频率）→ **`ERROR`/`UNKNOWN`**，
  既不会静默当 PASS，也不会把"连不上"混进"频率不对"

## 文件地图

| 文件 | 干什么 |
|---|---|
| `install_ai_env.sh` | 离线装 numpy/opencv/rknnlite（含 whl sha256 校验、PEP668 处理、apt 系统库、装后自检） |
| `verify_env.sh` | 只读自检：python 包 / librknnrt / NPU 实机 init_runtime / 视频节点 / GStreamer / 显示 / GPIO / PCIe |
| `capture_probe.sh` | 列视频节点与格式、抓一帧存 png、抓原始 YUYV；**全部套 timeout**，并给 `[REAL]/[DUMMY]` 判据 |
| `soc_vision/scpi_scope.py` | ★**主判据**：RIGOL SCPI 直读（纯标准库）+ 白名单判定 + 波形回读交叉校验 + 网段自动发现 |
| `soc_vision/scope_wave.py` | 图像法：波形像素 → 频率(Hz)/Vpp + PASS/FAIL（现为交叉校验/离线能力） |
| `soc_vision/config.py` | 配置 schema（ROI、时基、V/div、HSV 阈值、**正常频点白名单**、SCPI 参数） |
| `soc_vision/video_source.py` | 取帧（V4L2 YUYV/NV12、文件、图片、GStreamer、合成测试图） |
| `soc_vision/fpga_status.py` | 解 FPGA 塞在 CSI-2 首行的状态字（魔数 `0xA5C35A00`）；另含 PCIe `devmem` 备选 |
| `soc_vision/led_detect.py` | LED 亮灭判定（HSV/亮度 + 迟滞 + 时间去抖；与 FPGA 判决融合） |
| `soc_vision/ocr_cn.py` | ≤20 汉字识别（模板匹配可跑通；CRNN+CTC / PP-OCR 接口骨架） |
| `soc_vision/result_sink.py` | 结果输出：stdout JSONL / 文件 / 串口 / UDP |
| `soc_vision/main_runtime.py` | 主循环（SCPI 主判据 → 取帧 → FPGA状态 → LED → 图像法 → 汉字 → 输出/显示/板载 LED 指示） |
| `tools/offline_wheel_install.py` | ★**不依赖 pip 的离线 wheel 安装器**（出厂镜像没有 pip 时用它先铺 pip） |
| `tools/scope_sim.py` | ★**DS2302A 模拟器**（TCP 5555 裸 socket SCPI 服务器，纯标准库，支持故障注入） |
| `tools/scpi_sim_selftest.py` | ★**一键模拟验收**（真实 TCP 栈 + 白名单断言 + 容错断言，退出码 0=全过） |
| `tools/selftest_offline.py` | 离线自测：不需要相机，用合成图验证全部算法 + **随机正确率**（**板端 95 项全过**） |
| `tools/make_templates.py` | 从标定图生成汉字模板库 `.npz`（支持数据增强） |
| `tools/calib_scope_grid.py` | 示波器网格标定：测 px/div、排查"5 小格"歧义、用已知频率验证链路 |
| `tools/rigol_scpi_probe.py` | SCPI 真值探针（早期骨架；主判据已由 `soc_vision/scpi_scope.py` 承担） |
| `tools/eth_scope_setup.sh` | 板端以太网打通 + 自动找示波器（配静态 IP → ARP/ICMP → 扫 5555 → `ping` 留证） |
| `tools/xwd2png.py` | 把 `xwd` 截屏转 PNG（板子没有 scrot/ImageMagick，用它留显示证据） |
| `tools/roi_stats.py` | **标定辅助**：在任意一张图上量各 ROI 的原始统计量（LED/颜色的 V·HSV·色域命中、汉字 ROI 的 Otsu/连通域、波形 ROI 的掩膜占比） |
| `tools/v4l2_poll_snap.py` | ★**自 poll 取帧**（纯标准库 + ctypes）：超时自己 `STREAMOFF+close`，**永不依赖外部 kill** —— 根治"`timeout` kill 正在取流的进程 → CSI 收尾不干净 → SoC 卡死" |
| `tools/frame_forensics.py` | ★**对已抓到的帧文件做一次性离线取证**（不碰设备，抓帧/分析分工的标准交接命令）：0xFF 占比·灰阶·`[REAL]\|DUMMY`、魔数 `0xA5C35A00` 判位流版本、`scan_raw_yuyv` 解码、两张 PNG 帧间差、各 ROI 统计 |
| `tools/dtb_inspect.py` | 解析 **DTB / U-Boot FIT / Android boot.img**（含 `/images/*/hash` 校验节），不用上板就能判断一份镜像配的哪块屏 |
| `tools/rkimg_inspect.py` | 解析 **RKFW 整镜像（update.img）/ GPT 分区表**，分段读、内存安全（4.78 GB 镜像实测通过） |
| `tools/ocr_rate_test.py` | **真汉字识别率测试**：从标定页建模板 → 15 种退化变体 → 逐字比对出准确率（见 3b 节） |
| `soc_vision/cjk_text.py` | ★**中文渲染**（乱码根治）：PangoCairo 优先 → PIL → **ASCII 兜底（绝不输出乱码）**；`install_cv2_puttext_patch()` 一行让全程序的 `cv2.putText` 都能画中文（见 §14） |
| `tools/font_coverage.py` | **字体逐字验证**：纯标准库解析 TTF/OTF 的 cmap，检查界面用字是否都有字形（防豆腐块，先验再上板） |
| `tools/afh03_video22_lock.sh` | `/dev/video22` **互斥工具**（`status/take/release/with`）：优雅 `systemctl stop/start` `afh03-forensics.service`，解决"服务常占相机 → 别人取帧 0 字节"（见 §14.6） |
| `systemd/afh03-forensics-scope.conf` | **drop-in 模板**：给屏上 UI 注入 `AFH03_SCOPE_HOST` 等环境变量（不用改 ExecStart）即可显示真波形判定 |
| `config/example_config.json` | 配置模板（已按 DS2302A + 20/40 MHz 白名单填好默认值） |
| `config/service_config.json` | **纯 SCPI 自启动配置**（`video.enabled=false`，不开相机、低负载） |
| `systemd/` | 自启动：`afh03-vision.service`（系统服务，无界面）/ `.desktop`（XFCE 会话自启，带窗口） |

---

# 实测记录（全部是板上原始输出，不是"应该可以"）

## 1. 环境安装（板端实测）

出厂镜像的现实：**没有任何 pip**，而且新版 `get-pip.py` 改成"去 PyPI 下载 pip"，
离线板子上必然失败（实测 5 次 `NameResolutionError: Failed to resolve 'pypi.org'`）。
解决路径（可复现）：

```bash
# PC 侧下载纯 Python 的 pip wheel，推到板上
#    pip-26.2.1-py3-none-any.whl  setuptools-84.0.0-py3-none-any.whl
#    wheel-0.48.0-py3-none-any.whl  packaging-26.3-py3-none-any.whl
# 板上用本包自带的离线安装器把 pip 自己"铺"进 site-packages（按 PEP427 处理 .data 目录）
python3 tools/offline_wheel_install.py --site /usr/local/lib/python3.11/dist-packages \
        /data/local/tmp/pywhl/pip-26.2.1-py3-none-any.whl
```

| 项 | 实测结果 |
|---|---|
| 离线安装器落盘文件数 vs wheel 内 `RECORD` | **476/476、343/343、20/20、29 条** 完全一致 |
| `python3 -m pip --version` | `pip 26.2.1 from /usr/local/lib/python3.11/dist-packages/pip (python 3.11)` |
| `python3 -m pip check` | `No broken requirements found.` |
| 7 个厂家 whl（103,040,691 B） | 全部 sha256 校验通过、7/7 安装 OK |
| 装后版本 | `numpy 2.2.6` / `opencv 5.0.0 \| GUI: True` / `rknnlite import OK` / `ruamel.yaml 0.19.1` / `psutil 7.2.2` |
| **NPU 实机 `init_runtime`** | **OK** — `API: 2.3.0 (c949ad889d@2024-11-07T11:35:33)`、**`DRV: 0.9.8`** |
| `librknnrt.so` / 模型 | 7,259,064 B（version 2.3.0）/ `yolov5s_relu.rknn` 8,331,192 B |

> **版本疑点关闭**：所谓 "RKNPU v0.9.8" 是**驱动**版本（`RKNN Driver Information, version: 0.9.8`），
> 用户态 `librknnrt.so` 是 **2.3.0**，与 `rknn-toolkit-lite2 2.3.0` 完全匹配。

## 2. `verify_env.sh`（0 个 FAIL）

`结论：自检通过（0 个 FAIL）`。同时还测到：

| 项 | 实测 |
|---|---|
| 系统 | Debian GNU/Linux 12 (bookworm)，kernel 6.1.99 aarch64，`rockchip,rk3576-evb1-v10` |
| 解释器 | `/usr/bin/python3` = Python 3.11.2；uid=0(root)；内存 3901 MB |
| `opencv GUI 支持` | 有；`cv2` 在 `/usr/local/lib/python3.11/dist-packages/cv2/__init__.py`；**GUI 后端 = QT5 (5.15.19)**，GTK 无 |
| 显示 | `DISPLAY=:0`；**DSI-1 800×1280 connected**；HDMI-1 / DP-1 **disconnected** |
| 板载 LED | `/sys/class/leds/work` ← **gpio-12** |
| MIPI 使能 | `mipi-en` = **gpio-56 (gpio1_D0) out lo**（与 DTS 一致，推流时被驱动拉高） |
| I2C | `/dev/i2c-1,2,3,5,8,9,10,11` |
| 视频节点 | 73 个 `/dev/video*`；`/dev/video22` = `platform:rkcif-mipi-lvds3`（**FPGA 路**，与 DTS `csi2_dphy3→mipi3_csi2→rkcif_mipi_lvds3` 对齐） |
| GStreamer | 1.22.9 |
| 内存（`/proc/meminfo`，与语言无关） | **3902 MB total, 3410 MB available** |
| 已知冲突自检 | **TCP 5555 已被 `adbd` 占用**（`LISTEN *:5555 users:(("adbd",pid=1235,fd=12))`）→ 本机起模拟器请换端口；`无 /dev/watchdog`（本镜像未启用看门狗，印证崩溃取证结论） |

## 3. 板端离线自测：**PASS=95 FAIL=0**（最高优先级验收项）

```bash
cd /home/rock/afh03_board_setup && python3 tools/selftest_offline.py --keep
# -> PASS=95  FAIL=0
```

板上是 **numpy 2.2.6 + OpenCV 5.0.0.93**，与 PC 侧当年验证用的 numpy 1.15.1 + OpenCV 4.5.4
**不是同一套**，现在两套都过。原始输出：`afh03_work\soc\log_selftest_board.txt`。
（从 64 项扩到 **95 项**，新增雷达白名单/高频工况/SCPI 逻辑 26 项 + LED/颜色正确率 5 项。）摘录：

| 用例 | 实测数字 |
|---|---|
| 波形 4 组工况（不同时基/V/div/探头） | 频率误差 **0.00 ~ 0.04%**（容差 3%）、Vpp 误差 **0.2 ~ 0.8%**（容差 6%）、conf=1.00 |
| 三估计器一致性 | fft/ac/zc 相对差 <0.9%（如 `200.00 / 201.07 / 200.00` px） |
| 网格 px/div 自动估计 | **100 px/div**、**80 px/div** 全中；不给 px_per_div 也能出结果（-0.7% 内） |
| 纯噪声 | `ok=False conf=0.00`（不误报） |
| 周期估计单测 | 自相关 **137.2 px**、过零 **137 px**、过零间隔 cv=**0.0000** |
| **白名单 20 MHz** | `PASS/NORMAL`，实测 1.99997e7 Hz，偏差 **-0.002%** |
| **白名单 40 MHz** | `PASS/NORMAL`，偏差 **-0.000%** |
| 白名单 25 MHz（非正常） | `FAIL/ABNORMAL`，偏差 **+24.999%** |
| 白名单 12.5 MHz（非正常） | `FAIL/ABNORMAL`，偏差 **-37.953%** |
| **真实高频工况**（DS2302A 14 大格、1000 px 宽 = 71 px/div、**20 ns/div**） | 20 MHz：周期 **177.5 px**、偏差 **-0.871%** → PASS，conf=1.00<br>40 MHz：周期 **88.8 px**、偏差 **-0.620%** → PASS，conf=1.00 |
| LED 基线标定 / 噪声 | `{led0:26.0, led1:25.0, led2:25.8}` / σ = `{0.0, 0.0, 0.0}` |
| LED 亮灭 + 时间迟滞 | 全灭→全 OFF；亮0/灭1/亮2 → `ON/OFF/ON`，分数 `[211.0, 2.0, 211.3]`；单帧跳变不翻转 |
| **LED 亮灭正确率**（随机 100 组 × 3 ROI = **300 次判定**，含随机增益 0.75~1.25、σ7 噪声、偶发模糊、每组 6 帧走去抖） | **100.00%（300/300）** |
| **颜色判定正确率**（红/绿/蓝各配一个 HSV 窗，ROI 随机取"目标色/别的色/熄灭"，**300 次判定**） | **100.00%（300/300）**；单色：red 22/22、green 22/22、blue 20/20 全 100% || FPGA 状态字 | `condensed`/`register` 两种布局 × 小端/大端 + 一致性失败自动回落，全过 |
| 汉字（模板匹配） | 原图 `日川口十三` conf=**1.000**；抖动+噪声+变亮后仍正确 conf=**0.788**；投影切字合并到 5 段、中心偏差 **0.5 px**；空白 ROI → `?????` |
| SCPI 判定纯逻辑 | 14 项（白名单命中、容差边界 0.9%/1.2%、分位数、方波回读解算） |

### 3b. 真汉字识别率（`tools/ocr_rate_test.py`，零取流）

自测里用的是**几何图元**伪汉字（为了不依赖 CJK 字体）。这里用 **Windows 微软雅黑渲染的 17 个真汉字**
标定页（1700×140，每格 100 px），在同一页上生成 15 种退化变体测**真汉字**准确率：

```bash
python3 tools/ocr_rate_test.py --sheet calib_cn.png --config config/ocr_calib_config.json \
    --labels 北京欢迎你杭州西湖美丽中国科技强国 --augment 8
```

| 切字方式 | 总准确率（238 字） | 表现 |
|---|---|---|
| **`split=fixed`（推荐，固定机位）** | **230/238 = 96.64%** | 15 个变体里 **13 个 100%**：clean / σ8 / σ16 噪声 / 3×3 / 5×5 模糊 / ±30 亮度 / 0.6 对比度 / gamma1.5 / 0.9 缩放 / JPEG q55 / 噪声+模糊+亮度 全对；0.2% 剪切也 100%；只有**整页 2% 剪切**掉到 52.9% |
| `split=projection`（修复后） | 224/238 = 94.12% | 0.2% 剪切 94.1%、2% 剪切 23.5% |

**这两条数字同时暴露并修掉了一个真 bug**：`tools/make_templates.py` 原来**无条件用 `split_fixed` 建模板**，
所以只要识别端配 `split=projection`，模板字框（含格子留白）和识别字框（紧贴墨迹）就不一致，
**实测准确率直接从 96% 掉到 0%（全输出 `?`）**。已修成"建模板与识别用同一种切分"
（`boxes_for_item()`），修完 projection 从 **0% → 94.12%**。

**结论**：固定机位就用 **`split=fixed` + 标定框**（96.64%，抗光照/噪声/模糊/JPEG 很强）；
模板匹配的**真正弱点只有一个——整体几何形变**（整页 2% 剪切即 1700 px 宽右端位移 34 px，
fixed 52.9% / projection 23.5%）。对策：① 固定机位别动相机 ② 用 `fixed_boxes` 登记每个字的真实框
③ 形变大就上 CRNN 路线（`ocr_cn.py` 里接口已留）。原始输出：`afh03_work\soc\log_ocr_rate.txt`、
`log_ocr_rate_proj2.txt`。

## 4. `/dev/video22` 真实画面存证

```bash
bash capture_probe.sh -d /dev/video22 --raw
```

| 判据 | 实测 |
|---|---|
| 原始 YUYV | **4,147,200 B**（=1920×1080×2，BPL 3840，Size Image 4147200） |
| **0xFF 占比** | **0.00%**（0/4147200）；不同字节值 **188** → `[REAL]` |
| OpenCV 帧 | 1920×1080；灰度 **min=29 max=254 均值=165.2 标准差=76.4 灰阶=223 纯白=27.95%** → `[REAL]` |
| **画面是活的** | 连抓 5 帧，相邻帧 `\|差\|>4` 的像素占 **63.12%**，最大差 69，平均差 4.49 |
| 场景粗分析 | 主色 B224G224R224 占 35.9%；HSV H=46.6 S=40.6 V=195.7；高饱和(S>80) 11.2%；Canny 边缘 2.00% |
| **FPGA 状态字** | `scan_raw_yuyv` → `present=False`；魔数 `0xA5C35A00` 整帧出现 **0 次**；首 32 字节 `449a4b81 46994b83 469d517d …` |

> 当前 bit 是厂家 `mipi_rk.bit`（**不含** ROI 状态字），所以 `present=False` 是**预期**结果 ——
> 它同时证明了"无状态字"这条解码路径不会误报。等 `fpga-roi-accel` 换上带状态字的 bit 后重抓，
> 就能验证"有状态字"路径与帧数递增。

PNG 存证：`afh03_work\soc\frame_real_video22.png`、`frame_real_video22_b.png`；
日志：`afh03_work\soc\log_capture_probe.txt`、`log_real_frame.txt`。

### 这张真实帧上量出来的 ROI 统计（`tools/roi_stats.py`，零设备负载）

```bash
python3 tools/roi_stats.py -c config/example_config.json -i <真实帧.png>
```
图整体：1920×1080，BGR 均值 (157.5, 172.0, 155.0)。

| ROI | 实测（真实传感器数据） |
|---|---|
| led0 [200,300,60,60] | BGR(215.1,250.9,219.2) gray 237.4±10.4 H=53.1 S=38.1 V=250.9±8.7 色域命中 0.00% |
| led1 [300,300,60,60] | gray 243.4±13.8 H=31.6 S=18.7 V=249.9±8.4 色域命中 0.61% |
| led2 [400,300,60,60] | gray 253.5±1.9 V=254.2±1.4（**接近饱和**：该 ROI 正对高光） |
| led5 [700,300,60,60] | gray 184.6±9.2 H=71.0 S=55.4 V=200.7±13.1 |
| led7 [900,300,60,60] | gray 83.2±21.6 H=77.4 S=71.6 V=93.0±24.9（画面最暗的 ROI） |
| text0 [300,860,1400,120] | gray 205.2±55.2，Otsu 前景(白)占比 64.0%，连通域 165 个，最大面积 42336/27855/23470 |
| scope [1120,240,640,480] | BGR(70.0,80.5,62.0) H=71.1 S=72.8 V=82.2，波形色域命中 0.20% |

> 这些数字的用处：现场把目标 LED 面板/文本放到镜头前之后，同一张表就能告诉你阈值该往哪调
> （例如 led2 已经 saturate 到 V=254，说明该处要么过曝要么是白墙，不该拿来当 LED 判据）。

### 完整管线在真实帧上跑一遍（图像文件源，零设备负载）

```bash
timeout 40 python3 -u -m soc_vision.main_runtime --config config/example_config.json \
    --source img:<真实帧.png> --no-display --duration 4 --no-led-indicator
# -> [EXIT] 共 18 帧，4.4s，模块内异常 0 次
```
* LED 判定出数（led2~led6 ON、led0/led1/led7 OFF，`led_score` 65.5~158.6）——**注意**这里的阈值是给
  "LED 面板"用的，画面里并没有目标面板，所以这些 ON/OFF 只证明**链路通**，不代表现场正确率；
* **图像法明确拒绝出数**：`scope.ok=false`、`message="波形像素太少: 有效列 6.9% < 35.0%（检查 ROI/波形颜色/曝光…）"`
  —— 在**不是示波器画面**的图上，它给出的是可读的原因，而**不是编一个频率**（这条负向证据很重要）；
* OCR 因为还没有现场模板库（`models/cn_templates.npz`）而跳过，符合预期。

## 5. 示波器 SCPI 主判据

### 5.1 模拟验收（已过）

```bash
python3 tools/scpi_sim_selftest.py --log afh03_work/soc/log_scpi_sim.txt
# PC  : PASS=53  FAIL=0
# 板端: PASS=52  FAIL=0   （板端少 1 项：本机没有非 loopback IPv4，A2 段按设计跳过）
```

| 输入 | 判定 | 备注 |
|---|---|---|
| 20 MHz | **PASS/NORMAL** | 偏差 -0.000% |
| 40 MHz | **PASS/NORMAL** | 偏差 -0.000% |
| 20.18 MHz（+0.900%） | **PASS** | 容差内 |
| 20.24 MHz（+1.200%） | **FAIL/ABNORMAL** | 容差外 |
| 40.30 MHz（+0.750%） | **PASS** | 容差内 |
| 39.50 MHz（-1.250%） | **FAIL/ABNORMAL** | 容差外 |
| 13.5 MHz | **FAIL/ABNORMAL** | 偏差 -32.5% |
| 1 kHz | **FAIL/ABNORMAL** | 偏差 -99.995% |

容错（都实测了耗时，全部**不挂死、不崩、不静默**）：

| 场景 | 结果 | 耗时 |
|---|---|---|
| 端口没监听 | `ERROR` / 明确原因（示波器不在线 / IP 不对 / 被防火墙挡） | **1.01 s** |
| 不回话（`--drop-after 0`，timeout=0.8 s） | `ERROR/timeout`，且**没有被误判成 FAIL** | **0.80 s** |
| 每次延迟 300 ms + timeout 3 s | 仍 **PASS**（证明超时可调） | — |
| 延迟 1.5 s + timeout 0.5 s | `ERROR/timeout` | ~0.5 s |
| 不可达 IP `192.0.2.1` | `ERROR`（网络类原因） | **1.01 s** |
| 示波器自己测不出（回 `9.9E+37`） | `ERROR` / **`no-signal`** | — |
| 对端不是 RIGOL（`AGILENT…`） | `ERROR` / **`not-rigol`** | — |
| errno → 人话原因 映射 | `ECONNREFUSED→conn-refused`、`ETIMEDOUT→timeout`、`ENETUNREACH→net-unreachable`、`EHOSTUNREACH→host-unreachable`、`ENETDOWN→no-interface` | — |
| Vpp 交叉校验 | 示波器读数 **3.3000 V** vs `:WAVeform:DATA?` 本地解算 **3.2941 V** → 偏差 **-0.18%** | — |

原始输出：`afh03_work\soc\log_scpi_sim.txt`（板端 9453 字节）。

### 5.2 真机验收（待验，等用户上机）

```bash
# 1) 把示波器 LAN 口用网线接到板子网口
# 2) 配 IP 并自动找示波器（不需要事先知道它的 IP）
sudo bash tools/eth_scope_setup.sh                 # 自动挑 carrier=1 的网口，配 192.168.1.50/24，扫 5555
sudo bash tools/eth_scope_setup.sh --status        # 只读看状态
# 3) 拿到 IP 后直接判定（与模拟验收同一套断言）
python3 -m soc_vision.scpi_scope --host <示波器IP> --nominal 20000000,40000000 --tol-pct 1 --repeat 5
python3 tools/scpi_sim_selftest.py                 # 把里面的 127.0.0.1 换成真机 IP 再跑一遍
```

> 当前板子 `end0`/`end1` **carrier 都是 0**（网线没插），脚本会给**明确退出码 2** 并提示
> "底板 ETH0 → 系统 end1、底板 ETH1 → 系统 end0"，不会静默失败。

## 6. 显示与板载指示

* **`cv2.imshow` 在 DSI 屏上实测开窗成功**：`opencv 5.0.0` + Qt5，
  `xwininfo -root -tree` 看到窗口 **`0x2e00006 "afh03-disp-test" 800x1280+0+0`**（全屏铺满 DSI-1）。
* 截图留证：`python3 tools/xwd2png.py --grab /tmp/afh03_disp.png`（板子没有 scrot/ImageMagick，用 `xwd` + 自写转换器）。
  程序化验证截图内容（不靠人眼）：800×1280、**红块 35901 px、绿块 42684 px、黄字 5359 px**、非黑 99.77%。
* **板载 LED 指示**：`main_runtime` 会把判定结果写到 `/sys/class/leds/work/brightness`
  （PASS → 1，FAIL/读不到 → 0），只在状态变化时写；退出时自动灭掉。
* `main_runtime` 的判定横幅：顶部按 PASS/FAIL 上色，显示 `PASS / NORMAL  f=…  Vpp=…  (+…%)`。

### 显示现状（2026-04-27 板端**只读**实测）

| 项 | 实测值 | 结论 |
|---|---|---|
| DSI-1 | `connected`、模式 **800×1280**、dclk 71,428,572 Hz、`final DSI-Link bandwidth: 476193 x 4 Kbps` | DRM 侧一切正常 |
| 背光 | `brightness=200/255`、`actual_brightness=200`（面板 3.3V 已使能） | 背光已开 |
| X 会话 | `Monitors: 2` → `HDMI-1 1080x1920`、`DSI-1 800x1280` | 两块屏都在输出 |
| **面板配置（关键）** | boot 分区 FIT 里 `/images/fdt` @+2048、291,704 B，sha256 **`9a311aa4f5a7122a…`** —— 与**官方 `mlk-AFC03-debian-v1.2.2` 整镜像内的 DTB 完全相同**，也与该 FIT 自带 `/images/fdt/hash` 一致（自校验通过）→ **10 寸 800×1280@72 MHz、init 244 条** | ✅ **已裁定：面板实为 7 寸 1024×600，本"配置匹配"判据作废**；正确处置 = 刷厂家 7 寸 `boot.img`（`04665b29…`，已实测通过 → DSI 点亮）。详见下方「✅ 已裁定」 |
| **现象** | DSI（厂家屏，**实为 7 寸**）与 HDMI（用户 5.5 寸 1080P）**当时都黑屏** | **DSI ✅ 已结案**（刷 7 寸 boot.img）；**HDMI ✅ 已点亮**（独立供电 + 关 DSI）；详见下两段 |

#### ★ HDMI/DSI 双路显示根因：VOP 欠载（POST_BUF_EMPTY）
| 项 | 实测 |
|---|---|
| 只开 DSI（当前默认）时 | HDMI vp0 上出现 **10 次** `rockchip-vop2 ... [drm:vop3_vp_isr] *ERROR* POST_BUF_EMPTY_INTR irq err at vp0` |
| **把 DSI 关掉让 HDMI 独占后**（Lead 实测 `xrandr --output DSI-1 --off`） | **欠载错误 = 0** |
| 结论 | 黑屏极可能是 **VOP 同时驱动 HDMI 1080P + DSI 800×1280 两路时带宽/时序不够 → 显示缓冲欠载 → PHY 有信号但画面是空的**，**不是屏的兼容性问题** |
| 待确认 | 用户确认"关掉 DSI 后 HDMI 屏是否恢复正常"；确认后做成**开机自动生效**（开机即关 DSI + 只上 HDMI） |
| 旁证 | X 把 1080P 屏报成 **1080×1920 竖屏**（模式选择也值得一起核对） |

> ✅ **已裁定（2026-10-03，用户实测确认）—— 本段原判据作废，正确处置见下**
>
> 这一段是从"SoC 侧只读日志"里发现的，**没有改任何 DTS/分区**；但**原结论"配置匹配 → 不要刷 boot"是误判**。
> * **误判链**：把"活 DTB 是 10 寸"当成"屏是 10 寸" ＋ 采信厂家接线图 `屏幕接线图.jpg/png` 对型号
>   `HYY7BIPS27A-40` 的**错标（标成 10 寸）** ＋ 用户早期口述"厂家给的是 10 寸"。
> * **用户实测裁定：面板就是 7 寸 1024×600**（7 寸≈15.4 cm 对角线 vs 10 寸≈25.4 cm）。
> * **正确处置 = 刷厂家现成的 7 寸 `boot.img`**（U-Boot FIT 45.8 MB，装得进 67.1 MB 的 boot 分区）：
>   **交叉复核方已实测刷入（sha256 `04665b29…`，读回校验一致、重启 6 s 回）→ DSI 点亮** ✔
> * **板端复验待接回板子**：接回后只需**只读**确认 DSI 是否已正常；**若正常就不要重复刷**。
> * `dmesg` 那条 `panel-simple-dsi: Expected bpc in {6,8} but got: 0`：该属性在厂家 **7 寸/10 寸 dtsi 里本来就没有**，
>   属此 BSP 的常见告警，**不是根因**。
> * HDMI 那条 `vop3_vp_isr *ERROR* POST_BUF_EMPTY_INTR`（只开 DSI 时 10 次、关掉 DSI 后 0 次）与 "屏独立供电后
>   HDMI 点亮" 一起，构成 **HDMI 黑屏 = 面板需独立 5 V + 双路显示 VOP 欠载** 的结论（与 DSI 的 7/10 寸问题相互独立）。
> * 只读排查工具：`tools/dtb_inspect.py`（解析 DTB / U-Boot FIT，读 `/images/*/hash` 校验节）、
>   `tools/rkimg_inspect.py`（解析 RKFW 整镜像 / GPT）。只读提取产物（**未写任何分区**）：
>   `/tmp/live_fdt_trunc.dtb`（板上活的 DTB）、`/tmp/boot_fit_dtb.dtb`（boot 分区里 FIT 的 DTB）。

> **✅ 结案要素（保留来源与哈希，便于复核）**
>
> | 项 | 值 |
> |---|---|
> | **原厂/10 寸那份 DTB**（我方 10/3 上午在 boot 分区 FIT 里读到的，**已被替换**） | sha256 `9a311aa4f5a7122a88f96a1fed4651fba9e9d069415b35ee968cfd86a24f7bf1`（= 官方 `mlk-AFC03-debian-v1.2.2` 内那份 = 800×1280@72 MHz / init 244 条） |
> | **实刷入的 7 寸件**（交叉复核方） | sha256 **`04665b29…`**，读回校验一致，重启 6 s 回，**DSI 点亮** ✔ |
> | 板子当时活 DTB（10 寸期） | `051c8dff92bebf7a242defaf78045666087eece4ecf4dafa59059be7e7e3e8ea` |
> | 分区 | boot = `/dev/mmcblk0p3`，**67.1 MB**；7 寸 FIT = 45,787,648 B → **装得下** |
> | **备份与回滚（留档，非本次执行）** | 板上 `boot_backup_10inch_20261003_190256.img`；<br>`adb shell "dd if=/home/rock/boot_backup_10inch_20261003_190256.img of=/dev/disk/by-partlabel/boot bs=4M conv=fsync"`（**逐字核对路径 + 需 lead 批准**）。交接包内另有一份副本（`08_进展与变更\证据_20261003\boot_backup\`），但**不要当作唯一备份**——板上原件与包内副本**双份留存**才安全 |
> | **我方纪律** | 本次**只改文档、不做任何刷写**；板子接回后**只做只读复验**（DSI 正常则不重复刷） |


## 7. 自启动

```bash
sudo bash systemd/install_service.sh system      # systemd 系统服务（无界面，推荐）
bash systemd/install_service.sh autostart         # XFCE 会话自启（要 DSI 窗口显示）
sudo bash systemd/install_service.sh status       # 看状态 + journal
```

关键改动（与"以 SCPI 为主判据"配套）：

* `ExecStartPre` **不再因缺少视频节点而失败** —— 波形判定只需要网线到示波器，没相机也要能起；
* `KillSignal=SIGTERM` + `TimeoutStopSec=15`：让 `main_runtime` 走**优雅停止**（见下）；
* 判据来源/示波器 IP/白名单都放 `config`（`scope.source` / `scpi_host` / `expect_hz_list`）；
* **两种配置可选**（`AFH03_CONFIG` 决定）：
  * `config/example_config.json` 完整版（SCPI + 相机 LED/颜色/汉字）
  * `config/service_config.json` **纯 SCPI 版**（`video.enabled=false`，**连视频设备都不打开**，低负载）。
    要写 `/sys/class/leds` 需要 root，所以系统服务用 `AFH03_USER=root`。

### 板端实测（零取流，2026-04-27）

```bash
AFH03_USER=root AFH03_CONFIG=config/service_config.json sudo bash systemd/install_service.sh system
```

| 项 | 实测结果 |
|---|---|
| 服务状态 | `is-enabled = enabled`、`is-active = active`（启动成功），日志里 `[INIT] video.enabled=false：不打开任何视频设备（纯 SCPI 模式）` |
| 判定链路 | 服务以 root 运行、`SCPI 主判据: 127.0.0.1:15555 CH1 白名单=2e+07, 4e+07 容差=±1%`、`板载 LED 指示: /sys/class/leds/work/brightness（PASS -> 亮）` |
| **20 MHz（白名单内）** | journal 里 **74 次 `"verdict":"PASS"`**，`freq_hz` 19999960~20000030、`freq_dev_pct` **-0.0002%~+0.00015%**、`vpp_v 3.3`（波形回读 3.29412、交叉偏差 **-0.178%**）→ **`led_indicator:1`（板载 LED 亮）** |
| **25 MHz（白名单外）** | journal 里 **126 次 `"verdict":"FAIL"`、`"label":"ABNORMAL"`**，`freq_dev_pct +25.0001%` → **`led_indicator:0`（板载 LED 灭）** |
| 示波器不在线时 | 30 次 `"verdict":"ERROR"`、`"kind":"timeout"` → `led_indicator:0`（**不假装正常**） |
| 服务关键选项被正确识别 | `Restart=always`、`KillSignal=15`(SIGTERM)、`TimeoutStopUSec=15s`、`StartLimitIntervalUSec=1min`、`StartLimitBurst=6` |
| XFCE 会话自启 | 已装 `/home/linaro/.config/autostart/afh03-vision.desktop`（属主 `linaro:linaro`，`Exec` 已渲染成绝对路径），`X-GNOME-Autostart-enabled=true` |
| **相机取流次数** | **0**（全程 `video.enabled=false`/`--no-video`） |

> 注：真正的"断电重上电后自动起来"端到端测试需要 lead 批准（一断电 FPGA 配置就丢），
> 目前证据是"`enabled` + 服务实际启动成功并产出正确判定"。原始输出：`afh03_work\soc\log_autostart.txt`、`log_service_opts.txt`。

> **优雅停止为什么重要**：直接 `SIGTERM/SIGKILL` 掉一个正在 V4L2 取流的进程，
> 可能让 rkcif 驱动的 streamoff 走不干净（现场"`pkill -f v4l2-ctl` 触发内核 oops"是同一类问题）。
> `main_runtime` 现在把 SIGTERM/SIGINT 变成"置标志位 → 跳出循环 → `release()` → sleep 0.3 s"，
> 保证 `cap.release()` 一定被调用。

## 8. 现场踩过的坑（都已在代码里处理）

1. **`v4l2-ctl --stream-mmap` 在没有帧时永久阻塞**。第一版做法是外面套 `timeout`，但——
   **"套 `timeout`" 与"绝不中途 kill"在无帧场景下本质冲突**：`timeout` 到点会把正在取流的 `v4l2-ctl`
   **SIGTERM 掉**，而"无帧时被 kill 的取流进程"会让 CSI streamoff 走不干净，**实测多次把 SoC 拖到卡死/复位**
   （lead 踩过两次、我也踩过两次）。`rc=124 就中止` 只是**事后**止损。
   **根治办法：`tools/v4l2_poll_snap.py`** —— 自己 `REQBUFS/QBUF/STREAMON` + `select.poll(timeout)`，
   超时**自己** `STREAMOFF + munmap + close` 干净退出，**全程不需要任何外部 kill**。
   `capture_probe.sh` 保留 `timeout ${AFH03_V4L2_TIMEOUT:-8}` 作为"最后一道安全网"，
   但**首选** `v4l2_poll_snap.py`。**绝不要 `pkill -f v4l2-ctl`**。
   自检（不碰设备，PC 上也能跑）：`python3 tools/v4l2_poll_snap.py --selfcheck`
   （校验 ctypes 结构体尺寸/偏移与 Linux 64 位 ABI 一致：`v4l2_format`=208 且 `fmt` 在**偏移 8**、
   `v4l2_buffer`=88、`VIDIOC_S_FMT`=0xC0D05605 …）；空跑：`--dry-run`。
2. **`0xFF` 全白帧 = 假出帧**：FPGA 没有配置时 rkcif 给的是 **dummy buffer**，能"抓到 4,147,200 字节"
   但内容全是 `0xFF`。→ `capture_probe.sh` 现在自动算 **0xFF 占比 / 灰阶数**，给出 `[DUMMY]`/`[REAL]`。
3. **`100%` 的 0xFF 换成 OpenCV 会得到"纯白画面"**，容易被当成"相机曝光过度"。判据要用字节统计。
4. **Debian 12 的 PEP668**：系统 python 必须 `--break-system-packages`（脚本已自动处理）。
5. **出厂镜像没有 pip 且无网络**：`get-pip.py` 已失效 → 用 `tools/offline_wheel_install.py` 铺 pip。
6. **板上 `free -m` 是中文本地化**，`awk '/Mem:/'` 取不到内存行（`verify_env.sh` 里已知的小瑕疵，不影响结论）。
7. **板子的 `adbd` 自己占着 TCP 5555**（`ss -ltnp` → `LISTEN *:5555 users:(("adbd",pid=1235,fd=12))`），
   而这正是 DS2302A 的 SCPI 端口。**不影响连真示波器**（那是出向连接、本地用临时端口），
   但在板上**本机起 SCPI 服务器**（模拟器）会 `OSError: [Errno 98] Address already in use` →
   换端口即可：`python3 tools/scope_sim.py --port 15555`。`tools/scpi_sim_selftest.py` 的 `pick_port()`
   已经会自动让开 5555。
8. **systemd 的 `StartLimitIntervalSec`/`StartLimitBurst` 属于 `[Unit]` 段**，写在 `[Service]` 会被
   `Unknown key ... ignoring`（服务仍能起，但限速策略不生效）。已修正，并用
   `systemctl show ... -p StartLimitIntervalUSec -p StartLimitBurst` 验证到 `1min/6`。
9. **把常驻进程的 stdout 重定向到文件时必须显式 flush**：`tools/scope_sim.py` 的 banner 一开始
   因为块缓冲在 `> log &` 后一直不出现（`timeout` 杀掉后缓冲区直接丢），已改成行缓冲 + 显式 `flush`。
10. **中断信号要优雅处理**：直接把正在 V4L2 取流的进程 SIGTERM/SIGKILL 掉，CSI 流可能收尾不干净。
   `main_runtime` 现在把 SIGTERM/SIGINT 变成"跳出循环 → `release()` → sleep 0.3 s"（见第 7 节）。
10b. **🚫 铁律：无超时的取流命令 = 高危（默认禁止）**。`v4l2-ctl --stream-mmap` **没有内部超时**，
   无帧时**永久阻塞**；外部 `timeout` 到点会 SIGTERM 掉它 → CSI 收尾不干净 → **SoC 卡死/复位**（已复现多次）。
   因此：**默认禁止任何无超时的取流命令**；一律先"让别人抓好 raw → `--file` 解"，
   要自己抓就用 `tools/v4l2_poll_snap.py`（自 poll，超时自己 `STREAMOFF+close`）。
   `soc_vision/fpga_status.py --dump-dev` 已按此改造：**默认走自 poll 安全路径**，抓不到就
   `rc=3` 干净退出；只有显式 `--allow-blocking-dump` **且**设了 `AFH03_I_KNOW_IT_MAY_HANG=1`
   才会退回 `v4l2-ctl`（并在输出里打三重高危警告）。
   （原件已存档可回滚：`afh03_work\soc\rollback\fpga_status.py.orig`，md5 `CFFCB626AD593EE3FF605A4C44413FBC`。）
11. **⚠️ 通电状态下热插拔 DSI 排线会把 SoC 拖死** —— 实测**两次**复现：一拔一排线，`adb` 掉线、
    `transport_id` 变化、`adb shell` 卡死，**只能断电重上电恢复**。换屏/插拔 DSI 排线**必须先断 DC-12V**。
    由此合并出**取流三条纪律**：① 所有 `v4l2-ctl` 都套 `timeout`；② 抓帧命令**一次跑完**，
    绝不中途 `kill`/`pkill`；③ **第一路抓帧若 `rc=124`（超时）就立即中止、不要连环重试** ——
    连环 kill 正在取流的进程是"CSI 收尾不干净 → SoC 复位"的根因（已复现多次）。
12. **换 DSI 屏必须连 DTB 一起换**：7 寸 = 1024×600 @52 MHz / init 88 条，10 寸 = 800×1280 @72 MHz / init 244 条，
    两块屏是**不同控制器**、初始化序列完全不同 → 配错必然黑屏（而 SoC 侧一切"正常"：DSI connected、背光亮、X 在画）。
    两个 dtsi 靠 `MLK-RK03.dtsi` 里一行 `#include "rk03-screen-7.dtsi"|"rk03-screen-10.dtsi"` 切换。
    ⚠️ **`boot.img` 是 U-Boot FIT**（含 `kernel`+`fdt`+`resource`+sha256 校验节），所以
    **不能只把一颗裸 DTB 丢进 boot 分区**：要么直接用厂家完整 `boot.img`，要么 `mkimage` 重新打包完整 FIT。
    只读排查工具：`python3 tools/dtb_inspect.py <xxx.dtb|boot.img>`（纯标准库，**不用上板就能判断一份镜像配的哪块屏**）
    + `sha256sum /sys/firmware/fdt` 对比（板子实测跑 10 寸：`d74767cf…`=10寸 / `0c358ab2…`=7寸）。

## 9. 崩溃/复位记录（诚实记录，用于定责"换电源"还是"修驱动"）

在 2026-04-27 的联调中出现过 **SoC USB 掉线两次**：

| 观测 | 原始证据 |
|---|---|
| 第 1 次：端到端测试刚启动就掉线 | `adb: error: device '85a13e42b16e31c0' not found`；回来后 **`transport_id` 2→3**（USB 重新枚举） |
| **确实重启过** | `uptime` = up 2 min、`/proc/uptime` = **121.85**、`boot_id` 改变；`last -x` 里有 `crash` 与 `shutdown system down` 记录 |
| 第 2 次：恢复约 2 分钟后再次掉线 | 连续监测 60 s 一直 `List of devices attached`（空） |
| Lead 侧独立观测 | SoC USB（`VID_2207`）消失、只剩 FPGA JTAG；**更早还看到过一次内核 oops（`---[ end trace … ]---`）** → **至少有一次是真崩溃** |
| 重启那一轮 journal 尾部 | 只见 ntpd DNS 报错，**未见 oops**（该次检查被第 2 次掉线打断，未跑完） |

**第一嫌疑：供电瞬态。** 那一刻同时有 ① FPGA 已配置（dphy3 `data_rate_mbps 1000`）
② IMX415 相机出流 ③ OpenCV 1920×1080 取帧 ④ CPU 跑 SCPI/模拟器 —— 弱 12V 适配器容易欠压复位。
次要嫌疑：`timeout` 对正在取流的 Python 发 SIGTERM 导致 streamoff 不干净（已按第 7 节加固）。

**结论/影响**：SoC 单独复位**不会**丢 FPGA 配置（FPGA 有自己的供电与配置 SRAM），所以复位后
`/dev/video22` 仍是真实画面；**只有拔掉 DC-12V 整机断电**才会丢配置、并且 SPI FLASH 自加载失败
（这是另一个已确认的现象）。**不要擅自断电/重启**。

### 结案（Lead 确认 + 我的取证互相印证）

| 假设 | 证据 | 结论 |
|---|---|---|
| 内核 panic/oops 自动重启 | 日志里只有 `WARNING: CPU: 4 PID: 1 ... _regulator_put.part.0+0x158/0x160`（**开机后 7 秒**，PID 1/swapper/0，regulator 引用计数不平衡）；搜遍所有启动**没有** `Unable to handle kernel`/`Internal error: Oops`/`Kernel panic`；`/sys/fs/pstore/` 空；且 `panic_on_oops = 0`、`panic = 0` | ❌ **排除**（这台板子上 Oops/WARNING 不会自动重启） |
| 看门狗复位 | `ls /dev/watchdog*` → **不存在**；`/sys/class/watchdog/` 空；日志无 `watchdog bite` | ❌ **排除** |
| 系统内软挂死 | 无 `soft lockup` / `hung task` / `rcu stall` | ❌ **排除** |
| 整机欠压掉电 | 复位后 FPGA **仍有配置**（`0xFF=0.00%`、182 灰阶）→ 说明 FPGA 一直有电；电源读数 `vcc12v_dcin=12.000 V`、`vcc5v0_*=5.000 V`、`vdd_*=0.750 V`，温度 37.9~38.8 °C | ⚠️ **显著降级/基本排除** |
| **SoC 被外部复位** | 上面全排除后剩下的解释：**只有 SoC 复位、FPGA 有电** | ✅ **确认** |

**最终归因（Lead 确认）**：那两次是 **Lead 自己跑的 `adb reboot`**（用于清掉他自己中断抓帧留下的、
卡在不可中断（D）状态的 `v4l2-ctl`），所以 `last -x` 里有**干净关机**记录；另有一次是用户按 lead
要求**拔插 DC-12V** 做断电重上电（整机断电，FPGA 配置因此丢）。
→ **不用换电源、不用修驱动**；教训是：**抓帧命令一次跑完，不要中途 `kill` 正在取流的进程**。


## 10. 未过项 / 待验项（不藏）

| 项 | 状态 | 原因 / 下一步 |
|---|---|---|
| FPGA 首行状态字的**真实排布与字节序** | ⏳ 待验 | 当前厂家 bit 不含状态字（`present=False`、魔数 0 次）。等 `fpga-roi-accel` 换 bit 后重抓 |
| **真机 DS2302A** SCPI（`*IDN?`/FREQ/Vpp/探头/时基） | ⏳ 待验 | 用户身边暂时没有示波器 + 板子网口 carrier=0；模拟器闭环已过，真机步骤见 5.2 |
| 板端**开机自启动**"断电重上电"端到端验证 | 部分 | 已实测：服务 `enabled` + 启动成功 + 20 MHz→PASS/LED 亮、25 MHz→FAIL/LED 灭、示波器不在线→ERROR/LED 灭、XFCE 自启文件已装。**真正的断电重上电测试需要 lead 同意**（一断电 FPGA 配置就丢） |
| 汉字识别率 | ✅ **已测（真汉字）** | `split=fixed` **96.64%**（15 变体中 13 个 100%）、`split=projection` 94.12%；唯一弱点是整体几何形变（2% 剪切 → 52.9%）。见 3b 节 |
| 汉字**现场相机**文本（反光/摩尔纹/透视） | ⏳ 待验 | 需要真实文本目标在镜头前；算法与退化容错已用真汉字验证，`tools/ocr_rate_test.py` 可直接复用到现场拍的照片 |
| LED/颜色 的**目标面板**正确率 | ⏳ 待验 | 算法板端 95/95 全过（LED 亮灭 300/300、颜色 300/300） + 真实帧 ROI 统计已量（第 4 节）；缺"目标 LED 面板真的在镜头前" |
| 波形 Hz/Vpp 的**真机**误差 | ⏳ 待验 | SCPI 模拟闭环已过（20/40 MHz 偏差 -0.0002%~+0.00015%、Vpp 交叉校验 -0.18%、25 MHz→FAIL）；真机需用户接上 DS2302A |
| `scope_wave.py` 图像法频率与真机的**逐帧对比** | ⏳ 待验 | 需要真机波形上屏（`rigol_scpi_probe.py` 已备好逐次对比功能） |
| 2G 内存版长期运行稳定性 | 未测 | 本机是 3901 MB 版；厂家另有 2G 版机型 |
| 串口输出 UART 是否与 console 冲突 | 未测 | 需现场按 `cat /proc/cmdline` + `ls /dev/ttyS*` 选非 console 的那个 |

## 11. 与 FPGA 侧（task-1）的接口

* RK3576 与 PH1A90 之间**只有 MIPI CSI3 差分线**（见 `RK3576J_PH1A90SEG324_MIPI交互管脚定义表.xlsx`），
  没有寄存器总线。FPGA 把 8 个 ROI 的判亮结果塞进 **CSI-2 首行的前若干个 32bit 字**，
  魔数 `0xA5C35A00`；SoC 侧 `soc_vision/fpga_status.py` 负责解出。
* 配置里 `led.items` 的**顺序**必须与 FPGA 的 ROI 编号一致（第 i 个 = ROI_i）。
* LED 判定策略：FPGA 有结果就**以 FPGA 为准**（`led_source="fpga"`），软件结果同时保留在
  `led_score` 里做交叉验证 —— 两边不一致会立刻在 JSON 里看出来。
* 现场核对命令（**按安全顺序；不要用无超时的取流命令**）：
  ```bash
  # ① 首选：让抓帧的人先抓好，再解文件（零设备风险）
  python3 -m soc_vision.fpga_status --file /tmp/x.raw

  # ② 要自己抓就用"自 poll"工具（超时自己 STREAMOFF+close，永不外部 kill）
  python3 tools/v4l2_poll_snap.py -d /dev/video22 --out /tmp/x.raw --report
  python3 -m soc_vision.fpga_status --file /tmp/x.raw

  # ③ --dump-dev 现在默认也走 ② 的那条安全路径；抓不到就干净退出（rc=3），不会卡死板子
  python3 -m soc_vision.fpga_status --dump-dev /dev/video22 --timeout-ms 3000

  # ④ ⚠️ 高危逃生门，**默认拒绝**：v4l2-ctl 没有内部超时，无帧时永久阻塞，
  #    被 timeout/SIGKILL 杀掉会让 CSI 收尾不干净、把 SoC 拖到卡死/复位。
  #    只有在"已确认会出帧"且外部套了 timeout 时，才同时设这个环境变量使用：
  # AFH03_I_KNOW_IT_MAY_HANG=1 timeout 8 v4l2-ctl -d /dev/video22 \
  #     --set-fmt-video=width=1920,height=1080,pixelformat=YUYV \
  #     --stream-mmap=4 --stream-count=1 --stream-to=/tmp/x.raw
  ```

## 12. 结果长什么样

每帧一行 JSON（SCPI 主判据 + 图像法交叉校验 + 板载 LED 指示）：

```json
{"ts":1710000000.123,"frame":45,"fps":14.6,
 "led":{"led0":true,"led1":false,"led2":true},"led_score":{"led0":182.4,"led1":1.2,"led2":179.8},
 "led_source":"fpga",
 "scope_scpi":{"ok":true,"verdict":"PASS","label":"NORMAL","freq_hz":20000012.0,
   "nominal_hz":20000000.0,"freq_dev_pct":0.00006,"tol_pct":1.0,"vpp_v":3.3,
   "probe":10.0,"time_per_div_s":2e-08,"source":"scpi_meas","reason":"PASS/NORMAL …"},
 "verdict":"PASS","label":"NORMAL","led_indicator":1,
 "scope":{"ok":true,"freq_hz":19982580.0,"freq_dev_pct":-0.087,"verdict":"PASS","label":"NORMAL"},
 "ocr":{"text0":"北京欢迎你"},"ocr_conf":{"text0":0.94},
 "fpga":{"frame_cnt":8811,"n_lit":2,"lit":[true,false,true,false,false,false,false,false],
         "layout":"condensed"}}
```

## 13. 没有相机/没有示波器也想先验算法

```bash
python3 tools/selftest_offline.py --keep          # 板端 95 项全过（合成图 + 随机正确率）
python3 tools/scope_sim.py --freq 20e6 &          # 起一个 DS2302A 模拟器
python3 tools/scpi_sim_selftest.py                # 模拟验收一键跑完
python3 tools/eth_scope_setup.sh --status         # 看网口/示波器发现状态
```

## 14. 屏上 UI：中文不再乱码 + LED 亮灭/波形真接入（2026-10-03）

### 14.1 屏幕上那个 UI 是哪个？
**`afh03-forensics.service` → `tools/afh03_forensics.py`**（1024×600 触摸 UI，常驻占用 `/dev/video22`）。
> 实测确认：`afh03-vision-gui.service`（`soc_vision.main_runtime` 的窗口）当时是 **disabled/inactive**，
> 用户看到的"点进去就乱码、空壳子"的界面是**前者**。

### 14.2 乱码根因（**不是字体缺失，也不是 locale**）
| 项 | 实测 |
|---|---|
| `fc-list :lang=zh` | **非空**：`/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc`（文泉驿正黑 16.8 MB）→ **板子本来就有中文字体** |
| locale | `LANG=zh_CN.UTF-8`；`locale` 全项 `zh_CN.UTF-8`；X 会话（`xfce4-session`/`xfwm4`）同样是 `zh_CN.UTF-8` |
| **真根因** | 界面用 **`cv2.putText`** 画字，而它用的 Hershey 字体 **只支持 ASCII** → 中文必然乱码 |

**修法**：新增 `soc_vision/cjk_text.py`，把 `cv2.putText` **打补丁**成"含非 ASCII 时走真字体渲染"：

| 顺序 | 后端 | 本板实测 |
|---|---|---|
| 1 | **PangoCairo**（`python3-gi` + `python3-cairo`，系统自带，fontconfig 自动选 CJK 字体） | ✅ **可用**（`backend=pango`） |
| 2 | PIL/Pillow（需装；轮子已备 `afh03_work/soc/whl_pillow/`） | 未装（非必需） |
| 3 | **纯 ASCII 兜底**（术语表 + 逐字表，全角标点转半角） | ✅ 保证**永不输出乱码**（最差是可读英文） |
| — | `cv2.freetype`（OpenCV 自带 FreeType） | ❌ 本板 `cv2 5.0.0.93` **没有** freetype 模块 |

**硬指标（板端实测，非目视）**：`unknown_glyphs=0`（Pango 报告"字体里找不到字形"的字数）、
每行 ink 3151~5413 像素、宽 339~698 px → **真的画出了汉字，不是豆腐块**。

### 14.3 换/加字体的步骤（当前不需要，板子已有）
```bash
# 板子已有 wqy-zenhei 就不必装。若要换思源/Noto：
sudo mkdir -p /usr/share/fonts/truetype/afh03
sudo cp SourceHanSansSC-Regular.otf /usr/share/fonts/truetype/afh03/
sudo fc-cache -f && fc-list :lang=zh | head
# ⚠️ 必须用 **SC（简体）** 子集：实测 Source Han Sans **JP** 子集缺 58 个常用简体字
#    （值/帧/时/汉/灭/电/线/绿/蓝/错/频/验…）→ 会变豆腐块！
python3 tools/font_coverage.py <字体文件>     # 逐字验证 cmap 覆盖，**先验再上板**
```
* 指定字体：`AFH03_CJK_FONT=/path/xx.ttf`（PIL）或 `AFH03_CJK_FONT_DESC="WenQuanYi Zen Hei 18"`（Pango）
* 关闭补丁：`AFH03_NO_CV2_TEXT_PATCH=1`（退回原生 `cv2.putText`）

### 14.4 LED 亮灭：从"空壳"到真判定 + **防误检门**
改造前是 `led = {"led0": False} if self.a_demo_led() else {}` → **永远空**。
现在走 `soc_vision.led_detect`（HSV/亮度 + 迟滞 + 时间去抖）+ **防误检门**：
* 门判据：`led.enabled`、`led.items` 非空、每个 ROI **宽高合法 / 面积≥16px / ≤画面 25% / 完全在画面内**；
  `require_all_rois=True`（默认）时**必须全部有效**；
* **门不过就拒绝出判定**：每个 LED 标 `valid=False` + 原因，界面显示灰色"未判定"，
  **绝不把"没标定"显示成"灯是灭的"**；
* 有 FPGA 状态字时**以 FPGA 为准**（`source=fpga`），软件值并列保留（`sw_on`/`score`/`dv`）做交叉校验；
* 新增配置字段（`led` 段）：`require_all_rois` / `min_valid_rois` / `max_roi_area_frac` /
  `baseline_json`（`led_detect --out-baseline` 产出的"全灭"基线）。

### 14.5 波形：从"未启用"到**网线 SCPI 真判定**
改造前 meta 里写死 `"scope": {"ok": False, "message": "取证模式未启用波形判定"}`。
现在走 `soc_vision.scpi_scope.check_scope`（RIGOL DS2302A，SCPI over TCP），界面显示
**实测 Hz + 偏差% + Vpp + PASS/FAIL/ERROR**；没配/不在线/不回话都给**明确 ERROR + 原因**（不是空白）。
结论按 `--scope-ttl`（默认 5 s）缓存，避免每帧都查 SCPI。

给服务注入示波器地址（**不用改 ExecStart**：CLI 默认值读同名环境变量）：
```bash
sudo mkdir -p /etc/systemd/system/afh03-forensics.service.d
sudo cp systemd/afh03-forensics-scope.conf /etc/systemd/system/afh03-forensics.service.d/scope.conf
sudo sed -i 's/^Environment=AFH03_SCOPE_HOST=.*/Environment=AFH03_SCOPE_HOST=192.168.1.50/' \
     /etc/systemd/system/afh03-forensics.service.d/scope.conf
sudo systemctl daemon-reload && sudo systemctl restart afh03-forensics.service
```
网线侧先跑 `sudo bash tools/eth_scope_setup.sh`（挑 carrier=1 网口、配静态 IP、扫 5555）。

### 14.6 ⚠️ `/dev/video22` 互斥（**现场必须知道**）
`afh03-forensics.service` **常驻开着 video22** → 后到者取帧会拿到 **0 字节/超时**。用新增的互斥工具
（只做**优雅** `systemctl stop/start`，绝不 `kill -9`）：
```bash
sudo bash tools/afh03_video22_lock.sh status     # 看谁占着（只读）
sudo bash tools/afh03_video22_lock.sh take       # 停服务并等到设备真正空闲
#   ... 用自 poll 工具抓帧 ...
sudo bash tools/afh03_video22_lock.sh release    # 拉回服务
sudo bash tools/afh03_video22_lock.sh with -- python3 tools/v4l2_poll_snap.py -d /dev/video22 --out /tmp/f.raw --report
```

### 14.7 端到端验证数据（2026-10-03 板端实测）
| 项 | 结果 |
|---|---|
| 启动日志 | `[UI-PATCH v1] 中文后端=pango \| LED 判定=开 \| 波形 SCPI host=<未配置>` |
| **记录 JSON 对比** | 改造前 3 份记录：`led=0 条`、`scope="取证模式未启用波形判定"`；**改造后本次**：`led=8 条`（`on/valid/score/dv/source/fpga` 齐全）+ `led_gate={ok:true,8/8,"ROI 校验通过"}` + `scope={ERROR,NOT-CONFIGURED,"示波器未配置：请用 --scope-host <IP>"}` |
| **防误检门** | 同帧缩到 160×90 → 8 个 ROI 全部越界 → `ok=false`、每个 state `valid=False`、`led_conf=0`（**拒绝出判定**） |
| **FPGA 交叉** | 伪造 `lit=[1,0,1,1,0,0,0,0]` → `on` 跟随 FPGA、`source=fpga`，软件值保留在 `sw_on` |
| **SCPI 真读** | 连本地模拟器：**PASS/NORMAL f=20000030 Hz dev=+0.00015% Vpp=3.300 V** |
| SCPI 未监听 | **ERROR / conn-refused** + "拒绝连接（对端不是示波器，或 SCPI/socket 服务没开）" |
| 中文渲染 | `unknown_glyphs=0`；状态行画上 12512 彩色像素；截屏 `afh03_work/soc/ui_screen_patched.png`（1024×600） |
| 标注图留证 | `/userdata/afh03_forensics/2026-04-27/20260427_200745_444_annot.jpg` |

### 14.8 回滚
补丁集中在 `tools/afh03_forensics.py`（8 处 `[AFH03-UI-PATCH v1]` 标记）。板端原件已备份：
```bash
cp -a /home/rock/afh03_board_setup/tools/afh03_forensics.py.orig_before_ui_patch \
      /home/rock/afh03_board_setup/tools/afh03_forensics.py   # md5 325701575d468080fb66384f12bc7eba
systemctl restart afh03-forensics.service
```
`soc_vision/` 侧改动**纯新增/向后兼容**（`cjk_text.py` 新增；`led_detect.py` 只加 `valid/reason/gate`；
`config.py` 只加 4 个带默认值字段）→ 不回滚也不会破坏旧行为。

