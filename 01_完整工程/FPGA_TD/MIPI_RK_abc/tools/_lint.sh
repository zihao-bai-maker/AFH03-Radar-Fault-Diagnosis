#!/bin/sh
export VERILATOR_ROOT="D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/tools/_dl"
export PATH="/d/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/tools/_dl/w64devkit/bin:$PATH"
RTL="D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/uisrc/07_user"
"$VERILATOR_ROOT/bin/verilator_bin.exe" --lint-only -Wall -Wno-DECLFILENAME -Wno-UNUSEDSIGNAL \
  --top-module cam_stat_top \
  "$RTL/roi_win_acc.v" "$RTL/roi_color_stat.v" "$RTL/roi_mean_engine.v" \
  "$RTL/cam_stat_regs.v" "$RTL/axis_stat_inject.v" "$RTL/cam_stat_top.v" 2>&1
echo "LINT_EXIT=$?"
