# Build + run the Verilator simulation for the multi-ROI stat extension.
# ASCII only. Run from anywhere: powershell -ExecutionPolicy Bypass -File _build_sim.ps1
$ErrorActionPreference = "Continue"
$BASE = "D:\xuexishengshou\afh03_work\fpga\MIPI_RK_roi\tools"
$SIM  = "$BASE\sim"
$RTL  = "D:\xuexishengshou\afh03_work\fpga\MIPI_RK_roi\uisrc\07_user"
$env:VERILATOR_ROOT = "$BASE\_dl"
$env:TMP  = "$BASE\_tmp"; $env:TEMP = "$BASE\_tmp"
New-Item -ItemType Directory -Force -Path "$BASE\_tmp" | Out-Null
$env:PATH = "$BASE\_dl;$BASE\_dl\w64devkit\bin;" + $env:PATH
$GPP  = "D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/tools/_dl/w64devkit/bin/g++.exe"
$MAKE = "$BASE\_dl\w64devkit\bin\make.exe"
$VLT  = "$BASE\_dl\bin\verilator_bin.exe"

# keep the sim copies in sync with the real RTL
Copy-Item "$RTL\roi_win_acc.v","$RTL\roi_color_stat.v","$RTL\roi_mean_engine.v" $SIM -Force

Remove-Item -Recurse -Force "$SIM\obj_roi" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "$SIM\obj_top" -ErrorAction SilentlyContinue

Push-Location $SIM
$vargs = @("--cc","-j","4",
  "-Wno-WIDTH","-Wno-UNUSEDSIGNAL","-Wno-DECLFILENAME","-Wno-PINCONNECTEMPTY",
  "-Wno-UNUSEDPARAM","-Wno-UNDRIVEN","-Wno-GENUNNAMED","-Wno-VARHIDDEN","-Wno-TIMESCALEMOD",
  "--top-module","tb_roi_wrap","--Mdir","obj_roi","-CFLAGS","-O2",
  "tb_roi_wrap.v","tb_roi_stat.cpp","roi_win_acc.v","roi_color_stat.v","roi_mean_engine.v")
& $VLT @vargs 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Write-Host "VERILATE(roi) FAILED"; Pop-Location; exit 1 }
& $MAKE -C obj_roi -f Vtb_roi_wrap.mk CXX="$GPP" LINK="$GPP" -j 4 2>&1 |
  Select-String -Pattern "error|Error|undefined" | Select-Object -First 10
if (-not (Test-Path "$SIM\obj_roi\tb_roi_wrap.exe")) { Write-Host "BUILD(roi) FAILED"; Pop-Location; exit 1 }
Write-Host "BUILD(roi) OK"

$vargs2 = @("--cc","-j","4",
  "-Wno-WIDTH","-Wno-UNUSEDSIGNAL","-Wno-DECLFILENAME","-Wno-PINCONNECTEMPTY",
  "-Wno-UNUSEDPARAM","-Wno-UNDRIVEN","-Wno-GENUNNAMED","-Wno-VARHIDDEN","-Wno-TIMESCALEMOD",
  "--top-module","cam_stat_top","--Mdir","obj_top","-CFLAGS","-O2",
  "tb_stat_top.cpp","roi_win_acc.v","roi_color_stat.v","roi_mean_engine.v",
  "cam_stat_regs.v","axis_stat_inject.v","cam_stat_top.v","../../uisrc/07_user/cam_stat_regs.v")
& $VLT @vargs2 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Write-Host "VERILATE(top) FAILED"; Pop-Location; exit 1 }
& $MAKE -C obj_top -f Vcam_stat_top.mk CXX="$GPP" LINK="$GPP" -j 4 2>&1 |
  Select-String -Pattern "error|Error|undefined" | Select-Object -First 10
if (-not (Test-Path "$SIM\obj_top\Vcam_stat_top.exe")) { Write-Host "BUILD(top) FAILED"; Pop-Location; exit 1 }
Write-Host "BUILD(top) OK"
Pop-Location
Write-Host "=== ALL BUILT ==="
