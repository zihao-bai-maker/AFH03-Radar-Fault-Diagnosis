#=============================================================================
#  build_abc.ps1 -- one-command offline TD build of the A+B+C feature bitstream
#
#  Drives TD's flow steps directly (TD `launch_runs` silently does nothing in a
#  batch session -- see afh03_prj_fpga\README.md pitfalls #1..#3):
#     1) syn_1 : read_design -> opt_rtl -> opt_gate
#     2) phy_1 : opt_place -> opt_route -> bitgen
#
#  Uses the private flow copy DefaultFlow_nocwc.tcl (insert_debugger /
#  setup_debugger neutralised) -- workaround for
#      KIT-8469 ERROR: failed to compile the ooc module top_debug_hub
#  required because ui_ae_set.v no longer instantiates the VPI_0 probe.
#
#  NOT a board operation: no download, no FLASH, no device access.
#
#  Usage:
#    powershell -ExecutionPolicy Bypass -File build_abc.ps1            # syn+phy
#    powershell -ExecutionPolicy Bypass -File build_abc.ps1 -SynOnly
#    powershell -ExecutionPolicy Bypass -File build_abc.ps1 -PhyOnly
#
#  ASCII only on purpose (PowerShell 5.1 mis-parses UTF-8 .ps1 without a BOM).
#=============================================================================
param(
  [switch]$SynOnly,
  [switch]$PhyOnly
)

$ErrorActionPreference = "Continue"
$TD   = "D:\xuexishengshou\TD\bin\td_commands_prompt.exe"
$BASE = "D:\xuexishengshou\_work_20261028\fpga_abc\MIPI_RK_abc"
$FLOW = "D:/xuexishengshou/_work_20261028/fpga_abc/MIPI_RK_abc/DefaultFlow_nocwc.tcl"
$RUNS = "$BASE\fpga_prj_Runs"
$LOG  = "$BASE\build_logs"
if (-not (Test-Path $LOG)) { New-Item -ItemType Directory -Force -Path $LOG | Out-Null }

if (-not (Test-Path $TD))  { Write-Host "TD not found: $TD"; exit 1 }
if (-not (Test-Path $FLOW)){ Write-Host "flow not found: $FLOW"; exit 1 }

function Run-Step([string]$name) {
  $dir = "$RUNS\$name"
  if (-not (Test-Path "$dir\settings.cfg")) {
    Write-Host "!! $name : settings.cfg missing -> $dir"
    return $false
  }
  # clear stale flow markers so the flow does not halt / skip
  Get-ChildItem $dir -Force -File | Where-Object { $_.Name -match '^\.' } |
      Remove-Item -Force -ErrorAction SilentlyContinue
  $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
  $out = "$LOG\${name}_$stamp.log"
  Write-Host "==================== $name ===================="
  Write-Host "CWD = $dir"
  Write-Host "LOG = $out"
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $sw_start = Get-Date
  Push-Location $dir
  # NOTE: redirect (not Tee-Object) -- Tee can still be flushing when we read the
  # log back, which once made a failing run look like "SYN OK". `>` is synchronous.
  try { & $TD $FLOW > $out 2>&1 } finally { Pop-Location }
  $sw.Stop()
  Write-Host ("{0} elapsed: {1} s" -f $name, [int]$sw.Elapsed.TotalSeconds)
  Write-Host "---- log tail ----"
  Get-Content $out -Tail 6 | ForEach-Object { Write-Host ("   " + $_) }

  $t = Get-Content $out -Raw
  $hasErr = $t -match 'KIT-\d+ ERROR|PRJ-\d+ ERROR|BIT-\d+ ERROR|HDL-\d+ ERROR|PHY-\d+ ERROR|USR-\d+ ERROR'
  if ($hasErr) {
    Write-Host "---- ERROR lines ----"
    Select-String -Path $out -Pattern 'ERROR' | Select-Object -First 12 | ForEach-Object { Write-Host $_.Line.Trim() }
  }
  # positive artifact check: the step is only OK if its *output database* is fresh
  $art = ""
  if ($name -eq "syn_1")  { $art = "$dir\fpga_prj_gate.db" }
  if ($name -eq "phy_1")  { $art = "$dir\fpga_prj.bit" }
  if ($art -ne "") {
    if (-not (Test-Path $art)) { Write-Host "!! missing artifact: $art"; $hasErr = $true }
    elseif ((Get-Item $art).LastWriteTime -lt $sw_start) {
      Write-Host "!! stale artifact (not regenerated this run): $art"; $hasErr = $true
    } else { Write-Host "   artifact fresh: $art" }
  }
  return (-not $hasErr)
}

# ---------------------------------------------------------------- run
$ok = $true
if (-not $PhyOnly) { $ok = Run-Step "syn_1" }
if ($ok -and -not $SynOnly) { $ok = Run-Step "phy_1" }

# ---------------------------------------------------------------- report
Write-Host ""
Write-Host "==================== TIMING (authoritative: *.ts) ===================="
foreach ($f in @("$RUNS\syn_1\fpga_prj_gate.ts", "$RUNS\phy_1\fpga_prj_phy.ts")) {
  if (Test-Path $f) { Write-Host "---- $f ----"; Get-Content $f | ForEach-Object { Write-Host ("   " + $_) } }
  else { Write-Host "---- $f  <not generated> ----" }
}
Write-Host ""
Write-Host "==================== QOR ===================="
foreach ($f in @("$RUNS\syn_1\gate.qor", "$RUNS\phy_1\place.qor", "$RUNS\phy_1\route.qor")) {
  if (Test-Path $f) {
    Write-Host "---- $f ----"
    Select-String -Path $f -Pattern 'WNS|TNS|Fmax|FMAX|Hold|slices|LUT|REG|RAM|DSP|Setup' |
      Select-Object -First 24 | ForEach-Object { Write-Host ("   " + $_.Line.Trim()) }
  } else { Write-Host "---- $f  <not generated> ----" }
}

Write-Host ""
Write-Host "==================== BITSTREAM ================="
$bit  = "$RUNS\phy_1\fpga_prj.bit"
$comp = "$RUNS\phy_1\fpga_prj_compress.bit"
foreach ($f in @($bit, $comp)) {
  if (Test-Path $f) {
    $h = (Get-FileHash $f -Algorithm MD5).Hash
    Write-Host ("{0}  {1} bytes  MD5={2}" -f (Split-Path $f -Leaf), (Get-Item $f).Length, $h)
  }
}
if (Test-Path $bit) {
  $head = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($bit)[0..900])
  ($head -split "`r?`n") | Where-Object { $_ -match '^# (SPI Feature|Compress|Version|Design name)' } |
    ForEach-Object { Write-Host ("   " + $_) }
}

Write-Host ""
Write-Host "==================== VERDICT ==================="
if (-not $ok) { Write-Host "FLOW FAILED - see logs in $LOG" }
elseif ($SynOnly) { Write-Host "SYN OK" }
else { Write-Host "DONE" }
Write-Host "================================================"
