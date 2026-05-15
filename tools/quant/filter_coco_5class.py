"""Filter COCO YOLO-format labels down to 5 high-frequency classes.

A2-W11 5-class subset decision (2026-05-15):
    person (0), bottle (39), cup (41), book (73), cell phone (67)

Strategy (preserves HLS IP nc=80 contract):
    - Output labels keep ORIGINAL class ids (no remap to 0..4) so the
      ultralytics yaml can stay at nc=80 and the snn_yolov8_tiny_fpga
      detection head stays at the same channel count. The model just
      learns "75 of those channels are always background".
    - Images whose filtered label is empty are SKIPPED in the image list
      (we don't delete the source images — just produce a new label dir
      and an image-list file that yolo's dataset loader uses).

Outputs:
    <out_labels>/train2017/*.txt              filtered labels (kept ids)
    <out_labels>/val2017/*.txt
    <out_labels>/train2017.txt                image list (paths) of imgs WITH at least 1 kept obj
    <out_labels>/val2017.txt
    <out_labels>/stats.json                   counts per class, retain ratio

Usage:
    python tools/quant/filter_coco_5class.py \
        --src-labels C:/Users/jielu/Desktop/Project/UI/RK3588/YOLOv8/datasets/coco/labels \
        --src-images C:/Users/jielu/Desktop/Project/UI/RK3588/YOLOv8/datasets/coco/images \
        --out C:/Users/jielu/Desktop/Project/UI/RK3588/YOLOv8/datasets/coco_5class
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

# COCO 80-class id → name (subset we keep)
KEEP_IDS = {
    0:  "person",
    39: "bottle",
    41: "cup",
    67: "cell phone",
    73: "book",
}


def filter_split(src_labels_dir: Path, src_images_dir: Path,
                 out_labels_dir: Path, image_list_path: Path) -> dict:
    """Filter one split (train2017 / val2017). Returns stats dict."""
    out_labels_dir.mkdir(parents=True, exist_ok=True)
    image_list_path.parent.mkdir(parents=True, exist_ok=True)

    total_imgs = 0
    kept_imgs = 0
    kept_instances = {cid: 0 for cid in KEEP_IDS}
    total_instances = 0

    image_list_lines = []

    txts = sorted(src_labels_dir.glob("*.txt"))
    for i, txt in enumerate(txts):
        total_imgs += 1
        if i % 5000 == 0 and i > 0:
            print(f"  [{src_labels_dir.name}] {i}/{len(txts)}  kept_so_far={kept_imgs}")

        lines = txt.read_text().splitlines()
        keep_lines = []
        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            total_instances += 1
            parts = ln.split()
            try:
                cid = int(float(parts[0]))
            except (ValueError, IndexError):
                continue
            if cid in KEEP_IDS:
                keep_lines.append(ln)
                kept_instances[cid] += 1
        if not keep_lines:
            continue   # skip image without any kept obj

        out_txt = out_labels_dir / txt.name
        out_txt.write_text("\n".join(keep_lines) + "\n")

        # Image list line: absolute path to the .jpg
        img_path = src_images_dir / (txt.stem + ".jpg")
        image_list_lines.append(str(img_path).replace("\\", "/"))
        kept_imgs += 1

    image_list_path.write_text("\n".join(image_list_lines) + "\n")

    return {
        "split":            src_labels_dir.name,
        "total_imgs":       total_imgs,
        "kept_imgs":        kept_imgs,
        "kept_ratio":       kept_imgs / max(1, total_imgs),
        "total_instances":  total_instances,
        "kept_instances":   {f"{cid}_{KEEP_IDS[cid]}": n
                             for cid, n in kept_instances.items()},
        "image_list":       str(image_list_path),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src-labels", type=Path, required=True,
                    help="COCO YOLO labels root (contains train2017/ + val2017/)")
    ap.add_argument("--src-images", type=Path, required=True,
                    help="COCO images root (contains train2017/ + val2017/)")
    ap.add_argument("--out", type=Path, required=True,
                    help="output root; will create labels/{train,val}2017/ + img lists")
    args = ap.parse_args()

    if not args.src_labels.exists():
        print(f"[filter] src labels missing: {args.src_labels}", file=sys.stderr)
        return 2

    print(f"[filter] keep classes: {KEEP_IDS}")
    print(f"[filter] src labels   = {args.src_labels}")
    print(f"[filter] src images   = {args.src_images}")
    print(f"[filter] out          = {args.out}")

    stats = []
    for split in ("train2017", "val2017"):
        src_lab = args.src_labels / split
        src_img = args.src_images / split
        if not src_lab.exists():
            print(f"[filter] skip {split}: {src_lab} missing")
            continue
        out_lab  = args.out / "labels" / split
        out_list = args.out / f"{split}.txt"
        print(f"\n[filter] === {split} ===")
        stat = filter_split(src_lab, src_img, out_lab, out_list)
        stats.append(stat)
        print(f"  kept {stat['kept_imgs']}/{stat['total_imgs']} imgs "
              f"({stat['kept_ratio']:.1%})")
        for k, v in stat["kept_instances"].items():
            print(f"    {k}: {v}")

    (args.out / "stats.json").write_text(json.dumps(stats, indent=2))
    print(f"\n[filter] stats.json -> {args.out / 'stats.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
