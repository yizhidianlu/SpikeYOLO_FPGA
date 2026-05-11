@echo off
REM tools/ci/run_coco100_when_available.bat
REM
REM Windows companion for run_coco100_when_available.sh. Same auto-detect
REM logic — emits real 100-image coco_val100.json if datasets/coco/val2017
REM exists, otherwise leaves the smoke fixture and exits 0.
REM
REM Owner: A2

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%..\.." >nul
set "REPO_ROOT=%CD%"

if "%COCO_VAL_DIR%"=="" set "COCO_VAL_DIR=datasets\coco\val2017"
if "%COCO_WEIGHTS%"=="" set "COCO_WEIGHTS=models\tiny_fpga_int8.npz"
if "%COCO_OUT%"=="" set "COCO_OUT=tests\golden\coco_val100.json"
if "%COCO_NUM%"=="" set "COCO_NUM=100"
if "%COCO_PER_CLASS_MIN%"=="" set "COCO_PER_CLASS_MIN=1"

if not exist "%COCO_VAL_DIR%" (
    echo [coco100] %COCO_VAL_DIR% not present -- keeping smoke fixture
    echo [coco100] (D1: this is non-fatal; rerun once COCO val2017 is staged)
    if not exist "tests\golden\coco_val100_smoke.json" (
        echo [coco100] WARN: no smoke fixture either -- generating one now
        python tools\verify\gen_coco_val100.py --num 5 --weights "%COCO_WEIGHTS%" --output tests\golden\coco_val100_smoke.json --per-class-min 1
    )
    popd >nul
    exit /b 0
)

if not exist "%COCO_WEIGHTS%" (
    echo [coco100] ERROR: weights %COCO_WEIGHTS% missing -- cannot run real coco100
    popd >nul
    exit /b 2
)

echo [coco100] running real %COCO_NUM%-image generator -^> %COCO_OUT%
python tools\verify\gen_coco_val100.py --val-dir "%COCO_VAL_DIR%" --weights "%COCO_WEIGHTS%" --num %COCO_NUM% --per-class-min %COCO_PER_CLASS_MIN% --output "%COCO_OUT%" %*
if errorlevel 1 (
    popd >nul
    exit /b 1
)
echo [coco100] OK -^> %COCO_OUT%
popd >nul
exit /b 0
