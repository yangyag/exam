"""문항별 도형/이미지 스캔 + 분류 (헤더 장식 오탐 제거).

분류:
  figure : 실제 그림/도식/표 이미지 (앱에 이미지로 넣어야 하는 것)
  banner : 과목 머리글 등 장식 (무시)
  none   : 그림 없음
"""
import glob
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crop_figures import COL_X, band, draw_bbox  # noqa: E402
from extract import slug  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def classify(box):
    if not box:
        return "none"
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if h <= 32 and w >= 180:
        return "banner"
    return "figure"


def scan(pdf: Path):
    sid = slug(pdf.name)
    raw = json.loads((ROOT / "data" / "raw" / f"{sid}.json").read_text(encoding="utf-8"))
    figs, banners = [], []
    for q in raw["questions"]:
        y0, y1 = band(raw, q)
        box = draw_bbox(pdf, q, y0, y1)
        kind = classify(box)
        if kind == "figure":
            figs.append({"number": q["number"], "page": q["page"], "col": q["col"], "box": [round(v, 1) for v in box], "w": round(box[2] - box[0]), "h": round(box[3] - box[1])})
        elif kind == "banner":
            banners.append(q["number"])
    return sid, figs, banners


def main():
    total = 0
    out = {}
    for pdf in sorted(glob.glob(str(ROOT / "data" / "*.pdf"))):
        sid, figs, banners = scan(Path(pdf))
        out[sid] = figs
        total += len(figs)
        ex = ", ".join(f"{f['number']}({f['w']}x{f['h']})" for f in figs)
        print(f"{sid:9s} 그림 {len(figs):2d}개  오탐(머리글) {len(banners):2d}개  {ex}")
    (ROOT / "data" / "raw" / "_figures.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n실제 그림 문항: {total}개 / 1,300문항 ({total / 13:.1f}%, 회차당 평균 {total / 13:.1f}개)")


if __name__ == "__main__":
    main()
