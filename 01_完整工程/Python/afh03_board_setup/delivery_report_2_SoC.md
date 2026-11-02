# AFH03 异构板项目交付报告（第 2 部分：SoC / RK3576 侧）

> 本部分是**三部分交付报告中的第 2 部分**，只覆盖 **瑞芯微 RK3576（SoC）侧**的工作：
> 板端运行环境、四类识别算法、波形判定、显示与自启动、以及现场排查的一手数据。
> 第 1 部分（FPGA / PH1A90 侧）与第 3 部分（整机联调）由其他同事出具。
>
> **读者假设**：你**没有参与**本项目。所有命令都可以照抄复现；所有数字都来自板卡原始输出，
> 并在文末给出证据文件路径。**未经验证的项一律显式标注「待验」，不做推测性陈述。**

## 1 本部分范围与负责人

| 项 | 内容 |
|---|---|
| 负责范围 | RK3576（Debian 12）侧：运行环境安装、视觉/AI 算法落地、波形判定、结果显示/自启动、显示通路只读取证 |
| 交付物根目录 | `D:\xuexishengshou\afh03_board_setup\`（板端部署到 `/home/rock/afh03_board_setup/`） |
| 工作记录/证据 | `D:\xuexishengshou\afh03_work\soc\`（全部为板卡/PC 原始输出） |
| 与其它部分的分界 | 涉及 **JTAG / SPI FLASH / FPGA 位流** 的动作**不在本部分**，由 FPGA 侧同事负责 |
| 硬件使用纪律 | 本部分独占 `adb`；不使用 JTAG；未经批准不 `reboot`、不断电 |

## 2 目标与需求

### 2.1 板卡与系统（实测）

| 项 | 实测值 | 来源 |
|---|---|---|
| 主芯片 | **RK3576** + PH1A90SEG324（异构板 AFH03 / MLK-AFC03） | `/proc/device-tree/compatible` = `rockchip,rk3576-evb1-v10 rockchip,rk3576` |
| 板卡名 | `Rockchip RK3576 EVB1 V10 Board` | 设备树 `model` |
| 系统 / 内核 | **Debian GNU/Linux 12 (bookworm)**（`/etc/debian_version` = 12.15）/ **Linux 6.1.99 aarch64**（`#2 SMP Mon Sep 21 09:28:08 CST 2026`，`uname -a`） | 板端 |
| Python | **3.11.2**（`/usr/bin/python3`，GCC 12.2.0 构建） | 板端 |
| 内存 / 权限 | 3902 MB total / 3410 MB available（`/proc/meminfo`）；root（`adb shell` 即 uid=0） | 板端 |
| 显示 | DSI-1 `800×1280` connected；另有 HDMI 输出 | `xrandr` / DRM |
| NPU | `/usr/lib/librknnrt.so`（7,259,064 B），`/usr/bin/rknn_server` 存在 | 板端 |
| 相机通路 | FPGA 经 MIPI CSI3 → `/dev/video22`（`platform:rkcif-mipi-lvds3`），1920×1080 YUYV | `v4l2-ctl --all` |

### 2.2 需求清单

| # | 需求 | 状态 |
|---|---|---|
| 1 | 板端离线安装 AI 运行环境（出厂无 pip / 无网络） | ✅ 已完成并实测 |
| 2 | 四类识别：① 指定位置 LED 亮/灭 ② 指定位置颜色 ③ ≤20 汉字 ④ 示波器波形频率(Hz)与振幅(Vpp) | ✅ 算法与板端自测完成；真实目标场景数据 **待验**（见 §6） |
| 3 | **波形判定的需求变更**（用户后来明确）：被测信号 = 雷达 → RIGOL DS2302A，波形为**方波**；**20 MHz 与 40 MHz = 正常，其余 Hz = 不正常**；且**改为直接读示波器数据（LAN/SCPI）为主判据** | ✅ 已实现 + 模拟闭环验收通过；真机 **待验** |
| 4 | 结果显示（JSONL）+ 桌面窗口 + 板载 LED 指示 | ✅ 已完成并实测 |
| 5 | 开机自启动 | ✅ 服务已装并实跑验证；"断电重上电"端到端 **待批准** |

## 3 做了什么（含关键决策与试错）

### 3.1 决策一：离线自举 pip（因为出厂镜像连 pip 都没有）

**实测事实**：`python3 -m pip --version` → `No module named pip`；`python3 -m ensurepip` → 同样没有；
`apt-cache policy` 无包列表、板子**只有 lo 无外网**；新版 `get-pip.py` 已改成"去 PyPI 下载 pip"，
实测 5 次全部 `NameResolutionError: Failed to resolve 'pypi.org'` → **离线必然失败**。

**方案**：自己写一个**不依赖 pip 的离线 wheel 安装器** `tools/offline_wheel_install.py`
（纯 Python 标准库，按 PEP 427 处理 `purelib/platlib/scripts/data/headers` 的落盘位置，
保留 zip 里的可执行位），先把 **pip 自己**铺进 `site-packages`，之后再用 pip 正常装 7 个厂家 whl。

**交叉校验**（关键）：落盘文件数与 wheel 内 `RECORD` 条目数**完全一致** → 476/476、343/343、20/20。

### 3.2 决策二：波形判定改为 SCPI 直读（主判据），图像法降级为交叉校验

用户明确"20/40 MHz 正常、其余不正常"，并要求直接读示波器数据。
- **新增** `soc_vision/scpi_scope.py`（**纯标准库**，PC/板子都能跑）：SCPI 客户端（TCP 5555）、
  **多标称白名单判定**（命中任一即 PASS，输出最接近标称与偏差%）、`:WAVeform:DATA?` 波形回读做
  频率/Vpp **交叉校验**、`--scan` 网段自动发现（不知道示波器 IP 时用）。
- **保留** `soc_vision/scope_wave.py`（相机图像法）并支持同一套白名单，作为**交叉校验/离线能力**，
  自测没有改坏。
- **量化产出** `soc_vision/main_runtime.py`：SCPI 结论写成 `verdict/label`，并驱动**板载 LED**
  （PASS→亮、FAIL/读不到→灭，**不假装正常**）。

### 3.3 决策三：给"没有示波器"造一个模拟器，做闭环验收

用户身边暂时没有示波器，所以：
- `tools/scope_sim.py`：**纯标准库的 RIGOL DS2302A 模拟器**（TCP 5555 裸 socket SCPI 服务器），
  支持客户端实际用到的全部命令 + 设值命令（`*RST`、`:CHAN1:PROB 10`、`:TIM:MAIN:SCAL 20ns`），
  以及**故障注入**（`--delay ms` 不稳定的慢、`--drop-after N` 不回话、`--close-after N` 断连）。
- `tools/scpi_sim_selftest.py`：一键验收（真实 TCP 栈 + 白名单断言 + 容错断言 + JSON 取证），退出码 0 = 全过。

### 3.4 决策四：抓帧纪律的"根治"（本部分最贵的一条经验）

现象：`v4l2-ctl --stream-mmap` **没有内部超时**，设备不出帧时永久阻塞。现场做法是外面套 `timeout`，
但 **`timeout` 到点会 SIGTERM 掉正在取流的进程**，而"无帧时被 kill 的取流进程"会让 CSI streamoff
走不干净，**多次把 SoC 拖到卡死/复位**（FPGA 侧与 SoC 侧同事各踩两次）。

结论（认识上的修正）：**"套 `timeout`" 与 "绝不中途 kill" 在无帧场景下本质冲突**，
`rc=124 就中止` 只是**事后**止损。**根治** = 自己 poll：
`tools/v4l2_poll_snap.py`（`REQBUFS/QBUF/STREAMON` → `select.poll(timeout)` →
超时**自己** `STREAMOFF + munmap + close` 干净退出，**全程不需要任何外部 kill**）。
该工具的 ABI 层已在 PC 上自检通过（见 §4.9），**板端验证待做**。

### 3.5 试错记录（写在这里避免后人重踩）

- 一开始用 `capture_probe.sh` 里的 `v4l2-ctl` 抓帧，**没有任何 timeout**，且抓到的"4,147,200 字节"
  其实可能是**全 0xFF 的 dummy 帧**（FPGA 未配置时 rkcif 的行为）→ 已补 timeout + `[REAL]/[DUMMY]` 判据。
- 板上 `free -m` 是**中文本地化**输出，`awk '/Mem:/'` 取不到内存 → 改用 `/proc/meminfo`；
  **`adbd` 自己占着 TCP 5555**（= DS2302A 的 SCPI 端口）——**连真示波器不受影响**（出向连接、
  本地用临时端口），但在板上本机起 SCPI 服务器必须换端口；`systemd` 的
  `StartLimitIntervalSec`/`StartLimitBurst` 属于 `[Unit]` 段，写在 `[Service]` 会被忽略。

## 4 实测数据

### 4.1 环境安装（板端原始输出）

| 项 | 实测 |
|---|---|
| 离线自举 pip | `pip 26.2.1 from /usr/local/lib/python3.11/dist-packages/pip (python 3.11)` |
| `pip check` | `No broken requirements found.` |
| 落盘数 vs wheel `RECORD` | **476/476、343/343、20/20、29 条** 完全一致 |
| 7 个厂家 whl | 共 **103,040,691 B**，sha256 全部通过，**7/7 安装 OK** |
| 装后版本 | `numpy 2.2.6` / `opencv 5.0.0`（`GUI: True`，GUI 后端 **Qt5 5.15.19**）/ `rknnlite import OK` / `ruamel.yaml 0.19.1` / `psutil 7.2.2` |
| **NPU 实机 `init_runtime`** | **OK** —— `API: 2.3.0 (c949ad889d@2024-11-07T11:35:33)`，**`DRV: 0.9.8`** |
| 模型加载 | `yolov5s_relu.rknn`（8,331,192 B）`load_rknn OK` |

> **版本关系澄清**：现场一度把 "v0.9.8" 当成用户态库版本。实测 `librknnrt.so` 用户态是 **2.3.0**，
> **0.9.8 是 RKNPU 内核驱动版本**；用户态 2.3.0 与 `rknn-toolkit-lite2 2.3.0` 匹配，**版本疑点关闭**。

### 4.2 `verify_env.sh`：**0 个 FAIL**

同时测到：内存 3902/3410 MB；`DSI-1 800×1280 connected`；板载 LED `work` ← **gpio-12**；
MIPI 使能 `mipi-en` = **gpio-56 (gpio1_D0)**；GStreamer **1.22.9**；
**TCP 5555 已被 `adbd` 占用**；**无 `/dev/watchdog`**（本镜像未启用看门狗）。

### 4.3 板端离线自测：**PASS=95 FAIL=0**

```bash
cd /home/rock/afh03_board_setup && python3 tools/selftest_offline.py --keep
# -> PASS=95  FAIL=0
```

板上是 **numpy 2.2.6 + OpenCV 5.0.0.93**，与开发时用的 numpy 1.15.1 + OpenCV 4.5.4 **不是同一套环境**，
两套都通过。摘录：

| 用例 | 实测数字 |
|---|---|
| 波形 4 组工况（不同时基/V/div/探头） | 频率误差 **0.00~0.04%**（容差 3%）、Vpp 误差 **0.2~0.8%**（容差 6%）、conf=1.00 |
| 三估计器一致性 | FFT/自相关/过零相对差 <0.9% |
| 网格 px/div 自动估计 / 纯噪声 / 周期单测 | 100、80 px/div 全中；纯噪声 `ok=False conf=0.00`（不误报）；自相关 **137.2 px**、过零 **137 px**、cv=**0.0000** |
| **白名单 20 MHz / 40 MHz**（应正常） | 均 **PASS/NORMAL**，偏差 **-0.002% / -0.000%** |
| 白名单 25 MHz / 12.5 MHz（应不正常） | 均 **FAIL/ABNORMAL**，偏差 **+24.999% / -37.953%** |
| 真实高频工况（DS2302A 14 大格、71 px/div、**20 ns/div**） | 20 MHz：周期 **177.5 px**、偏差 **-0.871%** → PASS，conf=1.00；40 MHz：周期 **88.8 px**、偏差 **-0.620%** → PASS，conf=1.00 |
| **LED 亮灭正确率**（随机 100 组 × 3 ROI = **300 次判定**；随机增益 0.75~1.25 + σ7 噪声 + 偶发模糊 + 每组 6 帧去抖） | **100.00%（300/300）** |
| **颜色判定正确率**（红/绿/蓝各一个 HSV 窗，ROI 随机取"目标色/别的色/熄灭"，**300 次判定**） | **100.00%（300/300）**；单色 red 22/22、green 22/22、blue 20/20 |
| LED 基线/迟滞 | 基线 `{26.0, 25.0, 25.8}`、σ `{0,0,0}`；全灭→OFF；ON/OFF/ON 分数 `[211.0, 2.0, 211.3]`；单帧跳变不翻转 |
| FPGA 首行状态字解码 | `condensed`/`register` 两种布局 × 小端/大端 + 一致性失败自动回落，全过；全零帧 `present=False` |
| 汉字模板匹配（几何图元） | 原图 conf **1.000**；抖动+噪声+变亮后仍正确 conf **0.788**；投影切字 5 段、中心偏差 **0.5 px**；空白 ROI → `?????` |

### 4.4 波形判定（SCPI 主判据）——模拟闭环验收

```bash
python3 tools/scpi_sim_selftest.py --log afh03_work/soc/log_scpi_sim.txt
# PC  : PASS=53  FAIL=0
# 板端: PASS=52  FAIL=0   （板端少 1 项：本机没有非 loopback IPv4，该段按设计跳过）
```

**白名单与容差边界**（容差 ±1%）：

| 输入 | 判定 | 偏差 |
|---|---|---|
| 20 MHz / 40 MHz | 均 **PASS/NORMAL** | -0.000% / -0.000% |
| 20.18 MHz / 40.30 MHz | 均 **PASS**（容差内） | +0.900% / +0.750% |
| 20.24 MHz / 39.50 MHz | 均 **FAIL/ABNORMAL**（容差外） | +1.200% / -1.250% |
| 13.5 MHz / 1 kHz | 均 **FAIL/ABNORMAL** | -32.5% / -99.995% |

**异常处理**（每条都实测了耗时，要求"明确原因、不挂死、不崩、不静默"）：

| 场景 | 结果 | 耗时 |
|---|---|---|
| 端口没监听 | `ERROR` + 明确原因（示波器不在线 / IP 不对 / 被防火墙挡） | **1.01 s** |
| 不回话（`timeout=0.8 s`） | `ERROR/timeout`，且**没有被误判成 FAIL** | **0.80 s** |
| 延迟 300 ms + `timeout 3 s` → 仍 **PASS**（证明超时可调）；延迟 1.5 s + `timeout 0.5 s` → `ERROR/timeout` | 见左 | ~0.5 s |
| 不可达 IP `192.0.2.1` | `ERROR`（网络类原因） | **1.01 s** |
| 示波器测不出频率（回 `9.9E+37`） | `ERROR` / **`no-signal`** | — |
| 对端不是 RIGOL | `ERROR` / **`not-rigol`** | — |
| **Vpp 交叉校验** | 示波器读数 **3.3000 V** vs `:WAVeform:DATA?` 本地解算 **3.2941 V** → 偏差 **-0.18%** | — |

### 4.5 汉字识别率（真汉字，离线）

用 **Windows 微软雅黑渲染的 17 个真汉字**标定页（1700×140，每格 100 px），
在同一页上生成 **15 种退化变体**（σ8/σ16 噪声、3×3/5×5 模糊、±30 亮度、0.6 对比度、gamma1.5、
0.2% 与 2% 剪切、0.9 缩放、JPEG q55、噪声+模糊+亮度）后逐字比对：

| 切字方式 | 总准确率（238 字） | 说明 |
|---|---|---|
| **`split=fixed`（固定机位推荐）** | **230/238 = 96.64%** | 15 个变体里 **13 个 100%**；唯一失败：整页 2% 剪切 → 52.9% |
| `split=projection`（修复后） | 224/238 = 94.12% | 0.2% 剪切 94.1%、2% 剪切 23.5% |

> 修复的真缺陷：`tools/make_templates.py` 原来**无条件用 `split_fixed` 建模板**，
> 于是配 `split=projection` 识别时（字框紧贴墨迹 vs 模板含格子留白）不一致，
> **实测准确率从 96% 直接掉到 0%（全输出 `?`）**；改为"建模板与识别用同一种切分"后恢复到 **94.12%**。

### 4.6 开机自启动 + 板载 LED 指示（**全程零相机取流**）

用"纯 SCPI 低负载配置"（`config/service_config.json`，`video.enabled=false`）安装并实跑：

| 输入 | 服务实测输出 | 板载 LED |
|---|---|---|
| **20 MHz** | journal 里 **74 次 `"verdict":"PASS"`**，`freq_dev_pct` **-0.0002%**、Vpp 交叉校验 -0.18% | **1（亮）** |
| **25 MHz** | **126 次 `"verdict":"FAIL"`、`"label":"ABNORMAL"`**，偏差 +25.0001% | **0（灭）** |
| 示波器不在线 | 30 次 `"verdict":"ERROR"`（`kind=timeout`） | **0（灭，不假装正常）** |

服务状态 `enabled`；`systemctl show` 验证到 `Restart=always`、`KillSignal=15`(SIGTERM)、
`TimeoutStopUSec=15s`、`StartLimitIntervalUSec=1min`、`StartLimitBurst=6`。
XFCE 会话自启文件已装 `/home/linaro/.config/autostart/afh03-vision.desktop`。

### 4.7 相机真实画面存证（`/dev/video22`）

| 判据 | 实测 |
|---|---|
| 原始 YUYV | **4,147,200 B**（=1920×1080×2，BPL 3840） |
| **0xFF 占比** | **0.00%**；不同字节值 **188** → `[REAL]` |
| OpenCV 帧 | 1920×1080；灰度 min=29 max=254 **均值 165.2 σ76.4**，灰阶 223，纯白 27.95% |
| **画面是活的** | 连抓 5 帧，相邻帧 `\|差\|>4` 像素占 **63.12%**，最大差 69，平均差 4.49 |
| 场景粗分析 / 真实帧 ROI | 主色 B224G224R224 占 35.9%（H 46.6/S 40.6/V 195.7，Canny 2.00%）；8 个 LED ROI（led0 V=250.9±8.7、led7 V=93.0±24.9、**led2 已饱和 V=254.2±1.4**）；汉字 ROI gray 205.2±55.2、Otsu 前景 64.0%、连通域 165 |
| **FPGA 首行状态字** | `scan_raw_yuyv` → `present=False`；魔数 `0xA5C35A00` 整帧出现 **0 次**（当时是**厂家位流**，符合预期） |

### 4.8 显示通路（只读取证，未改任何配置）

| 项 | 实测 |
|---|---|
| DSI-1 | `connected`、**800×1280**、dclk 71,428,572 Hz、`final DSI-Link bandwidth: 476193 x 4 Kbps` |
| 背光 | `brightness=200/255`、`actual_brightness=200`（面板 3.3V 已使能） |
| 面板配置（**哈希级证据**） | boot 分区 `/dev/mmcblk0p3` 里 FIT 的 `/images/fdt` @+2048、291,704 B，sha256 **`9a311aa4f5a7122a88f96a1fed4651fba9e9d069415b35ee968cfd86a24f7bf1`** —— 与**官方 `mlk-AFC03-debian-v1.2.2` 整镜像内的 DTB 完全相同**，且与该 FIT 自带的 `/images/fdt/hash` 一致（**自校验通过**）→ **10 寸 800×1280@72 MHz、init 244 条**（⚠️ **原"配置匹配"判据已作废**：用户实测裁定面板为 **7 寸 1024×600**；正确处置＝刷厂家 7 寸 `boot.img`，已实测通过 → DSI 点亮，见本小节后注） |
| 分区 | `uboot=p1 misc=p2 boot=p3(67.1 MB) recovery=p4 backup=p5 rootfs=p6 oem=p7 userdata=p8` |
| **`/boot` 内容** | **只有 `grub/`**；**没有** `extlinux.conf`、**没有** `*.dtb` |
| 板端工具 | `dtc / mkimage / fdtdump / fget / rkdeveloptool / flash_erase` **全无** |
| `bpc` 告警 | `panel-simple-dsi 27d80000.dsi.0: Expected bpc in {6,8} but got: 0`（该属性在厂家 **7 寸/10 寸 dtsi 里本来就没有** → 属该 BSP 常见告警，**不能据此判定根因**） |

**HDMI / DSI 双路显示的最终根因（两个因素叠加，均已实测）**：

| 观测 | 数据 |
|---|---|
| 只开 DSI（默认）时 | HDMI 在 vp0 上出现 **10 次** `rockchip-vop2 ... [drm:vop3_vp_isr] *ERROR* POST_BUF_EMPTY_INTR irq err at vp0` |
| **关掉 DSI 让 HDMI 独占后** | **欠载错误 = 0** |
| **因素②：面板供电** | 用户把副屏**接到电脑 USB 独立供电后，HDMI 屏点亮**（板子端 PHY/EDID/TMDS 一直是正常的） |
| **因素①：VOP 双路欠载** | 板子同时驱动 HDMI 1080P + DSI 800×1280 时显示缓冲欠载 → **PHY 有信号但画面是空的** |
| **最终结论** | **HDMI 黑屏 = ① 面板需要独立 5 V 供电 + ② 板子双路显示的 VOP 欠载，两者叠加**；**不是屏兼容性问题、也不是 HDMI PHY 故障**。工程处置：**面板独立供电 + 开机即只上 HDMI（关 DSI）**，两者都做最稳 |
| 状态 | **HDMI 已点亮（独立供电后，已验证）**；**DSI 侧仍待物理排查** |
| 旁证 | X 把 1080P 屏报成 **1080×1920 竖屏**，模式选择也值得一并核对 |

> ✅ **已结案（2026-10-03，用户实测裁定）**：**面板实为 7 寸 1024×600@52 MHz**，因此
> ① 本文档早期"**配置匹配 → 不要刷 boot**"的结论**是误判、作废**（误判链：把"活 DTB 是 10 寸"当成"屏是 10 寸"
> ＋ 采信厂家接线图对型号 `HYY7BIPS27A-40` 的**错标（标成 10 寸）** ＋ 用户早期口述）；
> ② **正确处置 = 刷厂家现成的 7 寸 `boot.img`**（U-Boot FIT 45.8 MB 装得进 67.1 MB 的 boot 分区），
> **交叉复核方已实测刷入（sha256 `04665b29…`，读回校验一致、重启 6 s 回）→ DSI 点亮** ✔；
> ③ 哈希留档：原 10 寸 DTB `9a311aa4…`、替换前活 DTB `051c8dff…`、实刷入件 `04665b29…`；
> ④ 备份与回滚：`boot_backup_10inch_20261003_190256.img` + `dd ... of=/dev/disk/by-partlabel/boot bs=4M conv=fsync`
> （需逐字核对 + lead 批准；交接包内副本不作唯一备份）；
> ⑤ **本部分只做只读工作**，刷写由交叉复核方执行；**板端复验待板子接回**（DSI 正常则不重复刷）。

### 4.9 抓帧纪律的根治工具（ABI 层已在 PC 通过）

`tools/v4l2_poll_snap.py --selfcheck`（**不碰设备**）：

```
v4l2_plane_pix_format size=20  ✓   v4l2_pix_format_mplane size=188 ✓
v4l2_format size=208 ✓（fmt 在偏移 8）           v4l2_requestbuffers size=20 ✓
v4l2_plane size=64 ✓              v4l2_buffer size=88 ✓（timestamp@24、m@64、length@72）
VIDIOC_S_FMT=0xC0D05605  REQBUFS=0xC0145608  QUERYBUF=0xC0585609
QBUF=0xC058560F  DQBUF=0xC0585611  STREAMON=0x40045612  STREAMOFF=0x40045613
fourcc('YUYV')=0x56595559
```

上诉 ioctl 号与 Linux 64 位标准值**逐位一致** → ABI 层正确。**板端实测待做（见 §6）。**

### 4.10 崩溃/复位取证（结案）

| 项 | 实测 |
|---|---|
| 现场以为的 "oops" | 实为 **`WARNING: CPU: 4 PID: 1 at drivers/regulator/core.c:2414 _regulator_put+0x158/0x160`**，出现在**开机后约 7 秒**、`Comm: swapper/0` |
| 自动重启可能性 | `panic_on_oops = 0`、`/proc/sys/kernel/panic = 0`（0=永不自动重启）→ **内核 Oops/WARNING 不会触发自动重启** |
| 看门狗 / 软挂死 | `/dev/watchdog*` **不存在**、日志无 watchdog bite；无 `soft lockup` / `hung task` / `rcu stall` |
| 复位后 FPGA 状态 | `/dev/video22` 仍 **0xFF=0.00%**、182 灰阶 → **FPGA 一直有电**（SoC 单独复位不丢 FPGA 配置） |
| 电源/温度 | `vcc12v_dcin=12.000 V`、`vcc5v0_*=5.000 V`、`vdd_*=0.750 V`；温度 **37.9~38.8 °C** |
| **归因** | **两次 `adb reboot`（同事为清理卡住进程所发）+ 一次用户按要求的 DC 断电重上电**；**不需要换电源、不需要改驱动** |

## 5 交付物清单

全部位于 `D:\xuexishengshou\afh03_board_setup\`（板端部署到 `/home/rock/afh03_board_setup/`）。

### 5.1 环境安装 / 自检 / 取帧纪律

| 文件 | 用途 |
|---|---|
| `install_ai_env.sh` | 离线一键安装（whl sha256 校验 / PEP668 处理 / apt 系统库 / 装后自检 + NPU 实测） |
| `verify_env.sh` | 只读自检（包 / librknnrt / NPU 实机 / 视频节点 / 显示 / GPIO / **5555 占用与 watchdog 提示**） |
| `tools/offline_wheel_install.py` | **不依赖 pip 的离线 wheel 安装器**（出厂无 pip 时先铺 pip） |
| `capture_probe.sh` | 列节点/格式、抓帧；**全部 v4l2-ctl 套 timeout**，并给 `[REAL]/[DUMMY]` 判据 |
| `tools/v4l2_poll_snap.py` | **自 poll 取帧**（超时自己 STREAMOFF+close，永不外部 kill）——根治"kill 取流进程 → CSI 收尾不干净" |

### 5.2 波形判定（SCPI 主判据）

| 文件 | 用途 |
|---|---|
| `soc_vision/scpi_scope.py` | **主判据**：RIGOL SCPI 直读（纯标准库）+ 白名单判定 + 波形回读交叉校验 + `--scan` |
| `soc_vision/scope_wave.py` | 图像法（降级为交叉校验/离线能力），支持同一套白名单 |
| `tools/scope_sim.py` | **DS2302A 模拟器**（含故障注入） |
| `tools/scpi_sim_selftest.py` | **一键模拟验收**（白名单 + 容错 + JSON 取证） |
| `tools/rigol_scpi_probe.py` / `tools/calib_scope_grid.py` | SCPI 真值探针（逐帧对比）/ 图像法网格标定（px/div、"5 小格"歧义排查） |

### 5.3 其它识别、显示、配置与只读排查工具

| 文件 | 用途 |
|---|---|
| `soc_vision/led_detect.py` / `ocr_cn.py` / `fpga_status.py` / `result_sink.py` / `main_runtime.py` | LED 与颜色判定 / 汉字识别 / 状态字解码 / 结果输出 / 主循环 |
| `tools/roi_stats.py` | **标定辅助**：在任意图上量 ROI 的原始统计量 |
| `tools/ocr_rate_test.py` / `tools/make_templates.py` | **真汉字识别率测试**（15 种退化变体）/ 模板库生成（已修 split 一致性缺陷） |
| `tools/xwd2png.py` | 无 scrot/ImageMagick 时用 `xwd` 截屏转 PNG |
| `config/example_config.json` / `config/service_config.json` | 完整配置（SCPI + 相机 + 20/40 MHz 白名单）/ **纯 SCPI 自启动配置**（`video.enabled=false`） |
| `systemd/` | `afh03-vision.service` / `afh03-vision.desktop` / `install_service.sh` |

| `tools/dtb_inspect.py` | 解析 **DTB / U-Boot FIT / Android boot.img**，不用上板就能判断一份镜像配哪块屏 |
| `tools/rkimg_inspect.py` | 解析 **RKFW 整镜像（update.img）/ GPT 分区表**（分段读、内存安全） |
| `tools/eth_scope_setup.sh` | 板端以太网打通 + 自动发现示波器（配静态 IP → ARP/ICMP → 扫 5555 → ping 留证） |
| `README.md` | 30 秒上手 + 文件地图 + 全部实测数字 + 未过项 |
| `afh03_work/soc/DSI_面板切换方案_待审.md` | DSI 7/10 寸切换的完整证据链与方案（含 FIT 警告、备份/回滚） |

## 6 未完成 / 受限项（诚实列出）

| 项 | 状态 | 原因 / 下一步 |
|---|---|---|
| **真实目标场景的取流数据**（LED 面板 / 文本 / 色块在镜头前） | ❌ **为空** | 两次尝试取流都因"设备未出帧 + `timeout` kill 取流进程"把板子拖到 `adb shell` 卡死；已改为**由 FPGA/联调侧同事抓帧、本部分只做离线分析**。**算法正确率已有实测（LED/颜色 100%、真汉字 96.64%），缺的是"真实目标"这一层** |
| **真机 DS2302A 的 SCPI 验收** | ⏳ 待验 | 用户身边暂无示波器；模拟器闭环已过，真机步骤已固化（见 §7.6），接上即可复用同一套断言 |
| `tools/v4l2_poll_snap.py` 板端验证 | ⏳ 待验 | ABI 层已在 PC 通过；需一个稳定板子窗口做 `--dry-run` → 实际取帧 |
| **显示：HDMI ✅ 已点亮；DSI ✅ 处置已明确** | 已结案（板端复验待接回） | **HDMI ✅ 已点亮**：根因 = ①面板需独立 5 V 供电（接电脑 USB 后点亮）+ ②板子双路显示 VOP 欠载（只开 DSI 时 vp0 有 10 次 `POST_BUF_EMPTY`，关 DSI 后 = 0）。**DSI ✅ 处置已明确**：用户实测裁定面板为 **7 寸 1024×600**，**刷厂家 7 寸 `boot.img`（sha256 `04665b29…`）已由交叉复核方实测通过 → DSI 点亮**；原"配置匹配、不要刷 boot"判据作废（详见 §4.8 后注）。**→ 板端复验待接回板子**（若 DSI 已正常则不重复刷） |
| **断电重上电后的自启动端到端** | ⏳ 未做 | 一断电 FPGA 配置会丢，需与 FPGA 侧协调窗口；目前证据是"服务 `enabled` + 实际启动成功并产出正确判定" |
| FPGA 首行状态字的**真实排布与字节序** | ⏳ 待验 | 当前为厂家位流（无状态字，`present=False`、魔数 0 次）；等带 ROI 状态字的位流 |
| 2G 内存版长期稳定性 / 串口 UART 是否与 console 冲突 | 未测 | 本机为 3902 MB 版；串口需按 `cat /proc/cmdline` + `ls /dev/ttyS*` 选非 console 口 |

## 7 复现步骤（可照抄）

```bash
# 7.1 离线自举 pip（出厂镜像没有 pip；PC 先下好 pip/setuptools/wheel/packaging 的 py3-none-any wheel）
adb push whl/ /home/rock/whls/ && adb push pip-26.2.1-py3-none-any.whl /data/local/tmp/pywhl/
python3 tools/offline_wheel_install.py --site /usr/local/lib/python3.11/dist-packages \
        /data/local/tmp/pywhl/pip-26.2.1-py3-none-any.whl
python3 -m pip --version          # -> pip 26.2.1 (python 3.11)
python3 -m pip check              # -> No broken requirements found.

# 7.2 装 7 个厂家 whl + 自检
cd /home/rock/afh03_board_setup
sudo bash install_ai_env.sh --wheel-dir /home/rock/whls          # 装完自动自检 + NPU 实测
bash verify_env.sh --model /home/rock/yolo/yolov5s_relu.rknn     # -> 结论：自检通过（0 个 FAIL）

# 7.3 板端算法自测（不需要相机）
python3 tools/selftest_offline.py --keep                          # -> PASS=95  FAIL=0

# 7.4 波形判定：模拟器闭环（不需要示波器）
python3 tools/scope_sim.py --freq 20e6 --vpp 3.3 --probe 10 --port 15555 &   # 板上 5555 被 adbd 占用
python3 -m soc_vision.scpi_scope --host 127.0.0.1 --port 15555 --nominal 20000000,40000000 --tol-pct 1
python3 tools/scpi_sim_selftest.py                                # -> PASS=52 FAIL=0（PC 侧 53/0）

# 7.5 自启动（纯 SCPI 低负载形态，零相机）
AFH03_USER=root AFH03_CONFIG=config/service_config.json sudo bash systemd/install_service.sh system
journalctl -u afh03-vision -n 20 --no-pager        # 看 [INIT]/JSONL 判定
systemctl is-enabled afh03-vision                  # -> enabled

# 7.6 真机示波器（用户上机后执行；不需要事先知道 IP）
sudo bash tools/eth_scope_setup.sh                 # 自动挑 carrier=1 网口、配 IP、扫 5555、给 ping 证据
python3 -m soc_vision.scpi_scope --host <示波器IP> --nominal 20000000,40000000 --tol-pct 1 --repeat 5
python3 tools/scpi_sim_selftest.py                 # 把 127.0.0.1 换成真机 IP，同一套断言再跑一遍

# 7.7 汉字识别率（真汉字）
python3 tools/ocr_rate_test.py --sheet calib_cn.png --config config/ocr_calib_config.json \
        --labels 北京欢迎你杭州西湖美丽中国科技强国 --augment 8      # -> 96.64%（split=fixed）

# 7.8 只读排查：DSI 面板配置 / 镜像里的面板 / 抓帧纪律
sha256sum /sys/firmware/fdt                                        # 与厂家 DTB 对照
python3 tools/dtb_inspect.py <xxx.dtb|boot.img>                    # 不用上板判"配哪块屏"
python3 tools/rkimg_inspect.py <update.img>                        # 解析 RKFW 整镜像
python3 tools/v4l2_poll_snap.py --selfcheck                        # 不碰设备的结构体自检
python3 tools/v4l2_poll_snap.py -d /dev/video22 --dry-run          # 空跑 ioctl 链路（不读帧）
```

## 8 踩坑与经验

### 8.1 已修复的真实缺陷（现象 → 根因 → 修复 → 验证）

| # | 现象 | 根因 | 修复 | 验证 |
|---|---|---|---|---|
| 1 | 抓帧可能永久阻塞；抓到"4,147,200 字节"却不是画面 | `capture_probe.sh` 里 `v4l2-ctl` **没套 timeout**；且没有 dummy 帧判据 | 全部套 `timeout ${AFH03_V4L2_TIMEOUT:-8}`；抓完自动算 **0xFF 占比/灰阶数** 给 `[REAL]/[DUMMY]` | 实抓：0xFF 0.00% → `[REAL]` |
| 2 | 模拟器设值命令直接崩 | `scope_sim.parse_num` 的 `mult` 默认值误写成 dict | 改为 `mult = 1.0` 再按后缀乘 | `:CHAN1:PROB 100` 回读 =100 |
| 3 | SCPI 客户端 TypeError | `scpi_scope._is_invalid()` 收到 **str** 就 `abs()` | 先 `float()` 再判，异常返回 False | 全部 53/52 项通过 |
| 4 | 波形解算 `IndexError: list index out of range` | `analyze_samples` 调 `_percentile(s, 99.5)` 传百分数，而函数按 0~1 比例解释 → `xs[lo]` 越界 | 改为 `0.005/0.995`，并让 `_percentile` 自动归一化 + 索引夹紧 | Vpp 交叉校验 -0.18% |
| 5 | 换 `split=projection` 识别率**从 96% 掉到 0%** | `make_templates.py` **无条件用 `split_fixed` 建模板**，与识别端切字方式不一致 | 新增 `boxes_for_item()`：建模板与识别**用同一种切分** | projection 由 0% → **94.12%** |
| 6 | systemd 限速策略不生效（`Unknown key ... ignoring`） | `StartLimitIntervalSec`/`StartLimitBurst` 写在 `[Service]`（应属 `[Unit]`） | 移到 `[Unit]` | `systemctl show` → `1min/6` |
| 7 | 模拟器 banner 在 `> log &` 后一直不出现 | stdout **块缓冲**，被 `timeout` 杀掉后缓冲区丢失 | 行缓冲 + 显式 `flush` | banner 立即可见 |
| 8 | 模拟器端口被占直接抛栈 | 没处理 `EADDRINUSE` | 明确提示 + 建议换端口 + 退出码 2 | 板机 5555 被 `adbd` 占用时表现正确 |
| 9 | 强杀取流进程可能让 CSI 收尾不干净 | `main_runtime` 没处理 SIGTERM | 加信号处理：跳出循环 → `release()` → sleep 0.3 s；退出时灭 LED | 服务停机走优雅路径 |
| 10 | `verify_env.sh` 内存行取不到 | 板上 `free -m` 是中文输出，`awk '/Mem:/'` 匹配不到 | 改用 `/proc/meminfo` | 正确显示 3902/3410 MB |
| 11 | **无帧时 `timeout` kill 取流进程 → SoC 卡死/复位** | "套 timeout" 与 "绝不中途 kill" 在无帧场景下**本质冲突**；`rc=124 就中止` 只是事后止损 | 新增 `tools/v4l2_poll_snap.py`：**自 poll + 超时自己 STREAMOFF+close**，永不依赖外部 kill | PC 侧 `--selfcheck` 通过（ioctl 号与 Linux 64 位逐位一致）；**板端待验** |

### 8.2 现场注意事项（写给后来的人）

| 事项 | 说明 |
|---|---|
| **通电时不要热插拔 DSI 排线** | 实测**两次**把 SoC 拖死（`adb` 掉线、`adb shell` 卡死），只能断电重上电恢复。插拔前**必须先断 DC-12V** |
| 取流三条纪律 | ① 所有 `v4l2-ctl` 套 `timeout`；② 抓帧**一次跑完**，绝不中途 `kill`/`pkill`；③ 首选 `v4l2_poll_snap.py`（自己超时退出） |
| `0xFF` 全白帧 | FPGA 未配置时 rkcif 给的是 **dummy buffer**，能"抓到 4,147,200 字节"但内容全 `0xFF`。判据必须用**字节统计** |
| 板上 5555 端口 | 被 `adbd` 自己占用。**连真示波器（出向连接）不受影响**；本机起 SCPI 服务器要换端口 |
| 换屏必须同时换 DTB | 厂家 7 寸 = 1024×600@52 MHz / init 88 条；10 寸 = 800×1280@72 MHz / init 244 条，**控制器与初始化序列都不同**。且 `boot.img` 是 **U-Boot FIT**，**不能只丢一颗裸 DTB**——要么用厂家完整 `boot.img`，要么 `mkimage` 重新打包完整 FIT |
| **JTAG 连不上 ≠ FPGA/TAP 故障** | 真实根因是 **FTDI 设备"幻影化"**：Windows 设备管理器里呈现 `CM_PROB_PHANTOM` / **错误码 45**（设备曾存在、当前未连接）。**换线、换 TAP、查 FPGA 都是白费**；正确处置是**重新插拔 USB / 清理幻影设备让 FTDI 重新枚举**。查幻影可用 `Get-PnpDevice -Status Unknown` 或设备管理器"显示隐藏的设备"。（由 FPGA / 联调侧定位，记录于此供后人参考） |

## 附：本部分证据文件（均在 `D:\xuexishengshou\afh03_work\soc\`）

**环境/自检**：`log_install_ai_env.txt`（pip 自举 + 7 whl + NPU 实测）、`log_verify_env.txt` / `log_verify_env2.txt`（0 FAIL 完整输出）、
`log_selftest_board.txt`（板端 **PASS=95 FAIL=0** 全量断言）。
**波形判定**：`log_scpi_sim.txt`（**PASS=52 FAIL=0**）、`log_autostart.txt` / `log_service_opts.txt`（服务实跑 20 MHz→PASS/LED 亮、25 MHz→FAIL/LED 灭 + systemd 选项核验）。
**画面与识别**：`log_capture_probe.txt` / `log_real_frame.txt` / `frame_real_video22.png(_b)`（0xFF 0.00%、帧间差 63.12%、状态字 present=False）、
`log_roi_stats_real.txt`（真实帧 ROI 统计）、`log_ocr_rate.txt` / `log_ocr_rate_proj2.txt`（96.64% / projection 修复后 94.12%）。
**显示**：`log_display_test.txt` / `log_shot_verify.txt` / `shot_display_dsi.png`（DSI `cv2.imshow` 实测）、
`log_dsi_readonly.txt` / `log_live_dtb.txt` / `log_boot_fit_dtb.txt`（boot 分区 DTB 哈希级取证）。
**崩溃取证**：`log_crash_forensics.txt` / `log_oops_deep.txt` / `log_reset_reason.txt`
（`_regulator_put` WARNING 头部、`panic_on_oops=0`、无 watchdog/lockup、电源与温度读数）。
**方案文档**：`DSI_面板切换方案_待审.md`（7/10 寸切换的哈希证据、FIT 警告、备份/回滚、只读核查清单）。
