"""Download COCO train2017 to datasets/coco/ with resume support.

Detached: launch via PowerShell Start-Process; logs to runs/datasets_download.log.
Resumable: uses HTTP Range requests for partial download + retry on transient errors.

Phases:
  1. Download 4 zips (train images / val images / annotations / yolo labels).
  2. Unzip each into the appropriate target directory.
  3. Move yolo labels from the temp staging directory into datasets/coco/labels/.
  4. Verify image + label counts; emit JSON summary at runs/datasets_download_summary.json.

Run:
  D:\\Application\\Miniconda3\\envs\\spikeyolo\\python.exe tools/ci/download_coco_train2017.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

DOWNLOADS = [
    {
        'name': 'train2017_images',
        'url': 'http://images.cocodataset.org/zips/train2017.zip',
        'size_mb': 18000,
        'unzip_to': 'datasets/coco/images/',
    },
    {
        'name': 'val2017_images',
        'url': 'http://images.cocodataset.org/zips/val2017.zip',
        'size_mb': 1000,
        'unzip_to': 'datasets/coco/images/',
    },
    {
        'name': 'annotations',
        'url': 'http://images.cocodataset.org/annotations/annotations_trainval2017.zip',
        'size_mb': 241,
        'unzip_to': 'datasets/coco/',
    },
    {
        'name': 'yolo_labels',
        'url': 'https://github.com/ultralytics/yolov5/releases/download/v1.0/coco2017labels.zip',
        'size_mb': 70,
        # Contains coco/labels + coco/images symlinks; we keep only labels (Phase 3 cleanup).
        'unzip_to': 'datasets/coco_yolo_temp/',
    },
]


def http_get_with_resume(url: str, dst: Path, max_retries: int = 10, log_fn=print) -> bool:
    """HTTP GET with Range resume + retry. Returns True on success."""
    for attempt in range(max_retries):
        try:
            existing = dst.stat().st_size if dst.exists() else 0
            headers = {'User-Agent': 'spikeyolo-dataset-fetch/1.0'}
            if existing:
                headers['Range'] = f'bytes={existing}-'
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as r:
                # Content-Length may be only the remaining bytes for a Range request.
                cl = int(r.headers.get('Content-Length', 0) or 0)
                total = cl + existing
                mode = 'ab' if existing else 'wb'
                with open(dst, mode) as f:
                    last_log = time.time()
                    while True:
                        chunk = r.read(1024 * 1024)
                        if not chunk:
                            break
                        f.write(chunk)
                        if time.time() - last_log > 10:
                            done = dst.stat().st_size
                            pct = 100.0 * done / total if total else 0.0
                            log_fn(f"[{dst.name}] {done/1e6:.0f}MB / {total/1e6:.0f}MB ({pct:.1f}%)")
                            last_log = time.time()
            log_fn(f"[{dst.name}] complete: {dst.stat().st_size/1e6:.0f}MB")
            return True
        except Exception as e:  # noqa: BLE001 (broad: network errors are diverse)
            log_fn(f"[{dst.name}] attempt {attempt+1} failed: {e}; retry in 30s")
            time.sleep(30)
    log_fn(f"[{dst.name}] FAILED after {max_retries} attempts")
    return False


def unzip(src_zip: Path, dst_dir: Path, log_fn=print) -> None:
    log_fn(f"[unzip] {src_zip.name} -> {dst_dir}")
    with zipfile.ZipFile(src_zip) as z:
        z.extractall(dst_dir)
    log_fn(f"[unzip] {src_zip.name} done")


def main() -> int:
    repo = Path(r'C:\Users\jielu\Desktop\Project\SpikeYOLO')
    os.chdir(repo)
    log_path = repo / 'runs' / 'datasets_download.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_f = open(log_path, 'a', buffering=1, encoding='utf-8')

    def log(msg: str) -> None:
        line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
        print(line, file=log_f)
        try:
            print(line)
        except Exception:
            pass

    log("=== START download COCO train2017 ===")
    download_dir = repo / 'datasets' / 'coco' / '_downloads'
    download_dir.mkdir(parents=True, exist_ok=True)

    for spec in DOWNLOADS:
        zip_path = download_dir / Path(spec['url']).name
        log(f"[download] {spec['name']} -> {zip_path} (~{spec['size_mb']}MB)")
        if not http_get_with_resume(spec['url'], zip_path, log_fn=log):
            log(f"ABORT: {spec['name']} download failed")
            return 1
        unzip_dst = repo / spec['unzip_to']
        unzip_dst.mkdir(parents=True, exist_ok=True)
        try:
            unzip(zip_path, unzip_dst, log_fn=log)
        except zipfile.BadZipFile as e:
            log(f"ABORT: {spec['name']} unzip BadZipFile: {e}; remove and re-download")
            zip_path.unlink(missing_ok=True)
            return 2
        log(f"[done] {spec['name']}")

    # --- Move yolo labels to canonical location and clean staging dir ---
    src_labels = repo / 'datasets' / 'coco_yolo_temp' / 'coco' / 'labels'
    dst_labels = repo / 'datasets' / 'coco' / 'labels'
    if src_labels.exists():
        log(f"[merge] move labels from temp -> {dst_labels}")
        for sub in ['train2017', 'val2017']:
            src = src_labels / sub
            dst = dst_labels / sub
            if dst.exists():
                shutil.rmtree(dst)
            if src.exists():
                shutil.move(str(src), str(dst))
        shutil.rmtree(repo / 'datasets' / 'coco_yolo_temp', ignore_errors=True)

    # --- Verify counts ---
    n_train_imgs = len(list((repo / 'datasets/coco/images/train2017').glob('*.jpg')))
    n_val_imgs = len(list((repo / 'datasets/coco/images/val2017').glob('*.jpg')))
    n_train_labels = len(list((repo / 'datasets/coco/labels/train2017').glob('*.txt')))
    n_val_labels = len(list((repo / 'datasets/coco/labels/val2017').glob('*.txt')))
    log(f"[verify] train imgs={n_train_imgs} (expected >=118000)")
    log(f"[verify] val imgs={n_val_imgs} (expected >=4900)")
    log(f"[verify] train labels={n_train_labels}")
    log(f"[verify] val labels={n_val_labels}")

    summary = {
        'completed_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'train_imgs': n_train_imgs,
        'val_imgs': n_val_imgs,
        'train_labels': n_train_labels,
        'val_labels': n_val_labels,
        'pass': n_train_imgs >= 118000 and n_val_imgs >= 4900,
    }
    summary_path = repo / 'runs' / 'datasets_download_summary.json'
    with open(summary_path, 'w', encoding='utf-8') as fp:
        json.dump(summary, fp, indent=2)
    log(f"=== COMPLETE === pass={summary['pass']} summary={summary_path}")
    log_f.close()
    return 0 if summary['pass'] else 3


if __name__ == '__main__':
    sys.exit(main())
