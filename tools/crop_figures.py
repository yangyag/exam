"""문항 영역을 잘라 PNG로 저장한다 (그림 확인 및 그림 문항 자산 생성용).

사용법:
    python tools/crop_figures.py <회차ID> <문항번호> [<문항번호> ...] [--dpi 150] [--full]
      --full : 문항 지문부터 보기까지 영역 전체 (기본값: 그림 영역만 시도)
"""
import json
import sys
from pathlib import Path

import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract import slug  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
COL_X = {0: (42.0, 297.0), 1: (299.0, 558.0)}


def band(raw, q, col_filter=True):
    qs = raw["questions"]
    i = qs.index(q)
    nxt = next((x for x in qs[i + 1 :] if x["col"] == q["col"]), None)
    y0 = q["y"] - 2
    if nxt and nxt["page"] == q["page"]:
        y1 = nxt["y"] - 2
    else:
        y1 = 793.0
    return max(y0, 55.0), y1


def draw_bbox(pdf_path, q, y0, y1):
    """문항 영역 안의 도형/이미지 합집합 bbox."""
    doc = pymupdf.open(pdf_path)
    page = doc[q["page"] - 1]
    x0, x1 = COL_X[q["col"]]
    xs = []
    ys = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.height > 4 and r.width > 4 and r.y0 >= y0 - 6 and r.y1 <= y1 + 6 and r.x0 >= x0 - 10 and r.x1 <= x1 + 10:
            xs += [r.x0, r.x1]
            ys += [r.y0, r.y1]
    for im in page.get_images(full=True):
        for r in page.get_image_rects(im[0]):
            if r.y0 >= y0 - 6 and r.y1 <= y1 + 6 and r.x0 >= x0 - 10 and r.x1 <= x1 + 10:
                xs += [r.x0, r.x1]
                ys += [r.y0, r.y1]
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def crop(exam_id, numbers, dpi=150, full=False):
    pdf = next(p for p in (ROOT / "data").glob("*.pdf") if slug(p.name) == exam_id)
    raw = json.loads((ROOT / "data" / "raw" / f"{exam_id}.json").read_text(encoding="utf-8"))
    doc = pymupdf.open(pdf)
    out_dir = ROOT / "data" / "figures" / exam_id
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for n in numbers:
        q = next(x for x in raw["questions"] if x["number"] == n)
        y0, y1 = band(raw, q)
        box = None if full else draw_bbox(pdf, q, y0, y1)
        cx0, cx1 = COL_X[q["col"]]
        if box:
            x0, y0, x1, y1 = box
        else:
            x0, x1 = cx0, cx1
        box = pymupdf.Rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2)
        clip = pymupdf.Rect(cx0, 0, cx1, doc[q["page"] - 1].rect.height)
        box &= clip
        p = out_dir / f"{n:03d}{'_full' if full else ''}.png"
        doc[q["page"] - 1].get_pixmap(dpi=dpi, clip=box).save(p)
        paths.append((p, box))
    return paths


def main(argv):
    full = "--full" in argv
    args = [a for a in argv if a != "--full"]
    dpi = 200
    if "--dpi" in args:
        i = args.index("--dpi")
        dpi = int(args[i + 1])
        del args[i : i + 2]
    exam_id = args[0]
    numbers = [int(a) for a in args[1:]]
    for p, box in crop(exam_id, numbers, dpi, full):
        rel = f"figures/{exam_id}/{p.name}"
        vals = ",".join(f"{v:.1f}" for v in (box.x0, box.y0, box.x1, box.y1))
        print(f"{p}")
        print(f'  image: "{rel}"')
        print(f"  box: [{vals}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
