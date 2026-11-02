#!/bin/sh
BASE="D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/tools"
export VERILATOR_ROOT="$BASE/_dl"
export PATH="$BASE/_dl/w64devkit/bin:/usr/bin:/bin"
RTL="D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/uisrc/07_user"
SIM="$BASE/sim"
mkdir -p "$SIM/obj_roi"
cd "$SIM" || exit 1
"$VERILATOR_ROOT/bin/verilator_bin.exe" --binary --timing -j 4 \
  -Wno-WIDTH -Wno-UNUSEDSIGNAL -Wno-DECLFILENAME -Wno-PINCONNECTEMPTY -Wno-UNUSEDPARAM -Wno-UNDRIVEN -Wno-GENUNNAMED -Wno-VARHIDDEN \
  --top-module tb_roi_wrap \
  --Mdir "$SIM/obj_roi" \
  -CFLAGS "-O2" \
  "$SIM/tb_roi_wrap.v" "$SIM/tb_roi_stat.cpp" \
  "$RTL/roi_win_acc.v" "$RTL/roi_color_stat.v" "$RTL/roi_mean_engine.v" 2>&1 | tail -25
echo "BUILD_EXIT=$?"
ls -la "$SIM/obj_roi/tb_roi_wrap.exe" 2>/dev/null || echo "NO EXE"
