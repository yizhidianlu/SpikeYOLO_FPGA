# A1 W10 - train2017 (~19 GB) downloader via Windows BITS.
# BITS resumes across network drops AND across reboots; the OS service
# queues the job until completion.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File tools\ci\download_train2017_bits.ps1
#
# Re-run after a reboot to check status / kick off auto-resume.
# When done: extracts train2017.zip to coco\images\train2017\ and exits.

$ErrorActionPreference = "Stop"

$cocoRoot   = "C:\Users\jielu\Desktop\Project\UI\RK3588\YOLOv8\datasets\coco"
$zipUrl     = "http://images.cocodataset.org/zips/train2017.zip"
$zipFile    = Join-Path $cocoRoot "train2017.zip"
$targetDir  = Join-Path $cocoRoot "images\train2017"
$displayName = "spikeyolo-coco-train2017"

New-Item -ItemType Directory -Force -Path $cocoRoot | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $cocoRoot "images") | Out-Null

# ---- 0. Already extracted? ----
if (Test-Path $targetDir) {
    $count = (Get-ChildItem $targetDir -Filter "*.jpg" -ErrorAction SilentlyContinue).Count
    if ($count -gt 117000) {
        Write-Output ("[bits] train2017 already extracted: {0} jpgs at {1}" -f $count, $targetDir)
        exit 0
    } elseif ($count -gt 0) {
        Write-Output ("[bits] train2017 partially extracted ({0} jpgs) - will re-extract" -f $count)
    }
}

# ---- 1. Check existing BITS job ----
$job = Get-BitsTransfer -Name $displayName -ErrorAction SilentlyContinue
if ($job) {
    Write-Output ("[bits] found existing job: {0}" -f $job.JobState)
    $denom = [Math]::Max($job.BytesTotal, 1)
    $pct = 100.0 * $job.BytesTransferred / $denom
    Write-Output ("[bits]   bytes transferred: {0:N0} / {1:N0} ({2:N1} %)" -f $job.BytesTransferred, $job.BytesTotal, $pct)
    switch ($job.JobState) {
        'Transferring' {
            Write-Output "[bits] still downloading; re-run later to check status."
            exit 0
        }
        'Connecting' {
            Write-Output "[bits] connecting..."
            exit 0
        }
        'Queued' {
            Write-Output "[bits] queued, waiting for service to start it"
            exit 0
        }
        'Suspended' {
            Write-Output "[bits] suspended - resuming"
            Resume-BitsTransfer -BitsJob $job
            exit 0
        }
        'Transferred' {
            Write-Output "[bits] transferred - completing and extracting"
            Complete-BitsTransfer -BitsJob $job
        }
        'Error' {
            Write-Output "[bits] errored - restarting fresh"
            Remove-BitsTransfer -BitsJob $job
        }
        default {
            Write-Output ("[bits] state={0} - leaving alone" -f $job.JobState)
            exit 0
        }
    }
}

# ---- 2. If zip already on disk and complete-enough, skip download ----
$zipReady = $false
if (Test-Path $zipFile) {
    $zsize = (Get-Item $zipFile).Length
    if ($zsize -gt 18GB) {
        Write-Output ("[bits] zip already on disk: {0} ({1:N1} GB) - assuming complete" -f $zipFile, ($zsize/1GB))
        $zipReady = $true
    } else {
        Write-Output ("[bits] zip partial on disk ({0:N1} GB) - will let BITS resume" -f ($zsize/1GB))
    }
}

# ---- 3. Start (or restart) BITS job if needed ----
if (-not $zipReady -and -not (Get-BitsTransfer -Name $displayName -ErrorAction SilentlyContinue)) {
    Write-Output ("[bits] starting new BITS transfer for {0}" -f $zipUrl)
    Write-Output ("[bits]   destination: {0}" -f $zipFile)
    Write-Output "[bits]   approx size: 19 GB; expect 30-300 min depending on link"
    $newJob = Start-BitsTransfer -Source $zipUrl -Destination $zipFile -Asynchronous -DisplayName $displayName -Priority Foreground
    Write-Output ("[bits] job started: {0}" -f $newJob.JobId)
    Write-Output "[bits] this script will exit; re-run periodically to check status."
    Write-Output "[bits] When job reaches 'Transferred', this script will Complete-BitsTransfer + unzip."
    exit 0
}

# ---- 4. Extract once download finishes ----
if ($zipReady -or (Test-Path $zipFile)) {
    Write-Output ("[bits] extracting {0} -> {1}\images\ (expect ~10-20 min)" -f $zipFile, $cocoRoot)
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($zipFile, (Join-Path $cocoRoot "images"))
    $count = (Get-ChildItem $targetDir -Filter "*.jpg" -ErrorAction SilentlyContinue).Count
    Write-Output ("[bits] extracted: {0} jpgs at {1}" -f $count, $targetDir)
    if ($count -gt 117000) {
        Write-Output "[bits] keeping zip for now (delete manually if you want to free 19 GB)"
        Write-Output "[bits] READY for training. Launch:"
        Write-Output "        tools\quant\start_train2017_training.bat"
    } else {
        Write-Output ("[bits] WARNING: extracted {0} < 117k - extraction may be incomplete" -f $count)
    }
}
