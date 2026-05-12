# runs/remote_machine/run_all_csim.ps1
#
# Option-C workaround driver — see URGENT_ASK.md for context.
#
# Loops the same 10 targets as hw/hls/run_csim.tcl but invokes vitis_hls once
# per target with per-target SA_*_DIR env vars set to ABSOLUTE paths, so the
# testbenches' env_or() bypasses the broken relative-path defaults. The
# canonical hw/hls/run_csim.tcl will still fail; this driver is a workaround,
# not a replacement. M2-W1 backlog: B1 owner adds env-var setting to the
# canonical run_csim.tcl (Option A).
#
# Usage:
#   . E:\Applaction\Xilinx\Vitis_HLS\2024.1\settings64.bat   # PowerShell can't
#       # source .bat directly — use the wrapper PowerShell vars or call from
#       # cmd /c. See the bottom of this file for a reliable invocation form.
#   pwsh runs\remote_machine\run_all_csim.ps1

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path "$PSScriptRoot\..\..").Path
$HlsDir   = Join-Path $RepoRoot "hw\hls"
$DriverTcl = Join-Path $PSScriptRoot "run_csim_one_target.tcl"
$LogDir   = $PSScriptRoot
$Stdout   = Join-Path $LogDir "step1_csim_optionC_stdout.log"
if (Test-Path $Stdout) { Remove-Item $Stdout }

# Per-target spec. Keep in sync with hw/hls/run_csim.tcl TARGETS list.
# srcs / tbs are comma-separated relative paths (relative to hw/hls).
$Targets = @(
    @{
        top  = "sa_conv2d_int"
        srcs = "src/conv2d_int.cpp"
        tbs  = "sim/tb_conv2d_int.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"
        sep_golden = $null
    },
    @{
        top  = "sa_conv2d_bn"
        srcs = "src/conv2d_bn.cpp,src/conv2d_int.cpp"
        tbs  = "sim/tb_conv2d_bn.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"  # tb is synthetic; harmless
        sep_golden = $null
    },
    @{
        top  = "sa_lif_expand"
        srcs = "src/lif_expand.cpp"
        tbs  = "sim/tb_lif_expand.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"  # synthetic
        sep_golden = $null
    },
    @{
        top  = "sa_maxpool_or"
        srcs = "src/maxpool_or.cpp"
        tbs  = "sim/tb_maxpool_or.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"  # synthetic
        sep_golden = $null
    },
    @{
        top  = "sa_ms_downsampling"
        srcs = "src/ms_downsampling.cpp,src/conv2d_bn.cpp,src/conv2d_int.cpp,src/lif_expand.cpp"
        tbs  = "sim/tb_ms_downsampling.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"
        sep_golden = $null
    },
    @{
        top  = "sa_sep_conv"
        srcs = "src/sep_conv.cpp,src/conv2d_bn.cpp,src/conv2d_int.cpp,src/lif_expand.cpp"
        tbs  = "sim/tb_sep_conv.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_01_acb1"  # sep_conv uses its own
        sep_golden = "hw/hls/sim/golden_local/sep_conv_smoke"
    },
    @{
        top  = "sa_ms_all_conv_block"
        srcs = "src/ms_all_conv_block.cpp,src/sep_conv.cpp,src/conv2d_bn.cpp,src/conv2d_int.cpp,src/lif_expand.cpp"
        tbs  = "sim/tb_ms_all_conv_block.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_01_acb1"
        sep_golden = $null
    },
    @{
        top  = "sa_spike_sppf"
        srcs = "src/spike_sppf.cpp,src/conv2d_bn.cpp,src/conv2d_int.cpp,src/lif_expand.cpp,src/maxpool_or.cpp"
        tbs  = "sim/tb_spike_sppf.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_08_sppf"
        sep_golden = $null
    },
    @{
        top  = "sa_detect_head"
        srcs = "src/detect_head.cpp"
        tbs  = "sim/tb_detect_head.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_11_detect"
        sep_golden = $null
    },
    @{
        top  = "sa_tiny_fpga_top"
        srcs = "src/tiny_fpga_top.cpp,src/ms_downsampling.cpp,src/ms_all_conv_block.cpp,src/sep_conv.cpp,src/spike_sppf.cpp,src/detect_head.cpp,src/conv2d_bn.cpp,src/conv2d_int.cpp,src/lif_expand.cpp,src/maxpool_or.cpp"
        tbs  = "sim/tb_tiny_fpga_top.cpp,sim/npz_reader.cpp"
        golden_dir = "tests/golden/exploded/layer_00_stem"  # tb uses SA_GOLDEN_ROOT, not SA_GOLDEN_DIR
        sep_golden = $null
    }
)

$WeightDir = Join-Path $RepoRoot "models\exploded"
$GoldenRoot = Join-Path $RepoRoot "tests\golden\exploded"

$AbsResults = @()
$startAll = Get-Date

foreach ($tgt in $Targets) {
    $top = $tgt.top
    $absGolden = Join-Path $RepoRoot $tgt.golden_dir.Replace("/", "\")
    $env:SA_WEIGHT_DIR  = $WeightDir
    $env:SA_GOLDEN_DIR  = $absGolden
    $env:SA_GOLDEN_ROOT = $GoldenRoot
    if ($tgt.sep_golden) {
        $env:SA_SEP_GOLDEN_DIR = Join-Path $RepoRoot $tgt.sep_golden.Replace("/", "\")
    } else {
        Remove-Item Env:SA_SEP_GOLDEN_DIR -ErrorAction SilentlyContinue
    }

    $start = Get-Date
    $hdr = "==== $top  (start $($start.ToString('s')))"
    Add-Content -Path $Stdout -Value $hdr -Encoding ascii
    Write-Host $hdr

    # Pass per-target params via env vars (Vitis HLS -tclargs flaky under
    # cmd /c quoting; env vars survive cleanly).
    $env:OPT_C_TOP      = $top
    $env:OPT_C_SRCS_CSV = $tgt.srcs
    $env:OPT_C_TBS_CSV  = $tgt.tbs

    Push-Location $HlsDir
    try {
        # vitis_hls must be invoked after sourcing settings64.bat. The caller
        # of this script is expected to have done so via cmd /c chain. Output
        # is redirected by cmd directly to the log file (avoids PowerShell
        # capturing UTF-16 and re-encoding it badly).
        & cmd /c "vitis_hls -f `"$DriverTcl`" >> `"$Stdout`" 2>&1"
        $ec = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    $end = Get-Date
    $wall = [int]($end - $start).TotalSeconds

    Add-Content -Path $Stdout -Value "---- $top result: exit=$ec  wall=${wall}s ----" -Encoding ascii
    Write-Host "---- $top result: exit=$ec  wall=${wall}s ----"

    $AbsResults += [pscustomobject]@{
        top = $top
        exit = $ec
        wall_s = $wall
    }
}

$endAll = Get-Date
$totalWall = [int]($endAll - $startAll).TotalSeconds
$summary = "`n==== ALL TARGETS DONE  total=${totalWall}s ===="
Add-Content -Path $Stdout -Value $summary -Encoding ascii
Write-Host $summary

$tableStr = ($AbsResults | Format-Table -AutoSize | Out-String)
Add-Content -Path $Stdout -Value $tableStr -Encoding ascii
Write-Host $tableStr

$nFail = ($AbsResults | Where-Object { $_.exit -ne 0 }).Count
if ($nFail -gt 0) {
    $line = "FAIL: $nFail / $($Targets.Count) targets"
    Add-Content -Path $Stdout -Value $line -Encoding ascii
    Write-Host $line
    exit 1
} else {
    $line = "PASS: $($Targets.Count) / $($Targets.Count) targets"
    Add-Content -Path $Stdout -Value $line -Encoding ascii
    Write-Host $line
    exit 0
}
