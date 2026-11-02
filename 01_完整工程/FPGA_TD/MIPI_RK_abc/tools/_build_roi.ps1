# Build the multi-ROI stat simulation (Verilator + w64devkit g++). ASCII only.
$ErrorActionPreference = "Continue"
$BASE = "D:\xuexishengshou\afh03_work\fpga\MIPI_RK_roi\tools"
$SIM  = "$BASE\sim"
$RTL  = "D:\xuexishengshou\afh03_work\fpga\MIPI_RK_roi\uisrc\07_user"
$env:VERILATOR_ROOT = "$BASE\_dl"
$env:TMP = "$BASE\_tmp"; $env:TEMP = "$BASE\_tmp"
New-Item -ItemType Directory -Force -Path "$BASE\_tmp" | Out-Null
$env:PATH = "$BASE\_dl;$BASE\_dl\w64devkit\bin;" + $env:PATH
$GPP  = "D:/xuexishengshou/afh03_work/fpga/MIPI_RK_roi/tools/_dl/w64devkit/bin/g++.exe"
$MAKE = "$BASE\_dl\w64devkit\bin\make.exe"
$VLT  = "$BASE\_dl\bin\verilator_bin.exe"
Copy-Item "$RTL\roi_win_acc.v","$RTL\roi_color_stat.v","$RTL\roi_mean_engine.v" $SIM -Force
Push-Location $SIM
Remove-Item -Recurse -Force obj_roi -ErrorAction SilentlyContinue
$va = @("--exe","--cc","--timing","-j","4","-Wno-WIDTH","-Wno-UNUSEDSIGNAL","-Wno-DECLFILENAME","-Wno-PINCONNECTEMPTY","-Wno-UNUSEDPARAM","-Wno-UNDRIVEN","-Wno-GENUNNAMED","-Wno-VARHIDDEN","-Wno-TIMESCALEMOD","--top-module","tb_roi_wrap","--Mdir","obj_roi","-CFLAGS","-O2","tb_roi_wrap.v","tb_roi_stat.cpp","roi_win_acc.v","roi_color_stat.v","roi_mean_engine.v")
& $VLT @va 2>&1 | Select-Object -Last 2
if ($LASTEXITCODE -ne 0) { Write-Host "VERILATE FAIL"; Pop-Location; exit 1 }
& $MAKE -C obj_roi -f Vtb_roi_wrap.mk CXX="$GPP" LINK="$GPP" -j 4 2>&1 | Select-String "error" | Select-Object -First 8
if (-not (Test-Path "$SIM\obj_roi\tb_roi_wrap.exe")) { Write-Host "BUILD FAIL(no exe)"; Pop-Location; exit 1 }
Write-Host "BUILD OK -> obj_roi\tb_roi_wrap.exe"
Pop-Location
