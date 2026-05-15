@echo off
REM COCO 2017 multi-threaded download via aria2 (Plan A).
REM Resumes from existing train2017.zip if present.
REM Throttled at 10 MB/s overall to avoid saturating other IO.

set DL=datasets\coco\_downloads
set ARIA="C:\Users\jielu\AppData\Local\Microsoft\WinGet\Packages\aria2.aria2_Microsoft.Winget.Source_8wekyb3d8bbwe\aria2-1.37.0-win-64bit-build1\aria2c.exe"

if not exist %DL% mkdir %DL%

echo [%date% %time%] Plan A: aria2 multi-thread COCO 2017 download starting...
echo Target dir: %DL%

REM train2017 (19.3 GB) - 16 threads, continue from existing partial
%ARIA% -x 16 -s 16 --continue=true --max-tries=20 --retry-wait=10 ^
    --max-overall-download-limit=10M ^
    --console-log-level=warn --summary-interval=30 ^
    --file-allocation=none --auto-file-renaming=false ^
    -d %DL% -o train2017.zip ^
    http://images.cocodataset.org/zips/train2017.zip
if errorlevel 1 echo train2017 returned error %errorlevel%

REM val2017 (~1 GB)
%ARIA% -x 8 -s 8 --continue=true --max-tries=10 --retry-wait=10 ^
    --console-log-level=warn --summary-interval=30 ^
    --file-allocation=none --auto-file-renaming=false ^
    -d %DL% -o val2017.zip ^
    http://images.cocodataset.org/zips/val2017.zip
if errorlevel 1 echo val2017 returned error %errorlevel%

REM annotations (~250 MB)
%ARIA% -x 4 -s 4 --continue=true --max-tries=10 --retry-wait=10 ^
    --console-log-level=warn --summary-interval=30 ^
    --file-allocation=none --auto-file-renaming=false ^
    -d %DL% -o annotations_trainval2017.zip ^
    http://images.cocodataset.org/annotations/annotations_trainval2017.zip
if errorlevel 1 echo annotations returned error %errorlevel%

REM YOLO-format labels
%ARIA% -x 4 -s 4 --continue=true --max-tries=10 --retry-wait=10 ^
    --console-log-level=warn --summary-interval=30 ^
    --file-allocation=none --auto-file-renaming=false ^
    -d %DL% -o coco2017labels.zip ^
    https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip
if errorlevel 1 echo labels returned error %errorlevel%

echo [%date% %time%] All COCO 2017 archives downloaded.
exit /b 0
