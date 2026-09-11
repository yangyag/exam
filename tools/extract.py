"""기출문제 PDF -> 문항 단위 raw JSON 추출기.

PDF는 2단(column) 레이아웃이고 텍스트가 그려진 순서도 뒤섞여 있어서
좌표를 이용해 읽기 순서를 복원한다.

  1) 페이지에서 단(column) 경계(거터)를 찾는다
  2) 단어를 단별로 나누고, 단 안에서 y(줄) -> x(좌->우) 순으로 정렬
  3) 왼쪽 단 전체 -> 오른쪽 단 전체 순으로 이어붙인다 (신문식 흐름)
  4) 문항번호(N.)와 보기기호(①~④)로 문항을 분리한다
"""
import json
import re
import sys
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "data" / "raw"

CIRCLE = "①②③④"

# 정보처리기사 필기 과목 구성은 항상 20문항씩 5과목으로 고정되어 있다.
SUBJECTS = {
    1: {"code": 1, "name": "소프트웨어 설계", "from": 1, "to": 20},
    2: {"code": 2, "name": "소프트웨어 개발", "from": 21, "to": 40},
    3: {"code": 3, "name": "데이터베이스 구축", "from": 41, "to": 60},
    4: {"code": 4, "name": "프로그래밍 언어 활용", "from": 61, "to": 80},
    5: {"code": 5, "name": "정보시스템 구축 관리", "from": 81, "to": 100},
}


def subject_code(number):
    for code, s in SUBJECTS.items():
        if s["from"] <= number <= s["to"]:
            return code
    raise ValueError(number)
NOISE_RE = re.compile(
    r"정보처리기사필기기출문제|기출문제\s*&|정답\s*및?\s*해설"
    r"|^저작권 안내$|시나공 카페 회원을 대상|허락 없이 복제"
    r"|매체에 옮겨 실을 수 없으며|상업적 용도로 사용할 수 없습니다"
    r"|^\s*\d{4}\s*년\s*\d\s*회|^\s*\d+\s*회\s*$|^\s*-\s*\d+\s*-\s*$"
)
SUBJECT_RE = re.compile(r"제\s*(\d)\s*과목\s*(.+?)(?:\s|$)")
QSTART_RE = re.compile(r"^(\d{1,3})\.\s*(.*)$")


def slug(stem: str) -> str:
    m = re.search(r"(\d{4})\s*년\s*(\d)\s*회", stem)
    if not m:
        m = re.search(r"(\d{4}).{0,8}?(\d)\s*회", stem)
    if not m:
        raise ValueError(f"연도/회차를 찾을 수 없음: {stem}")
    return f"{m.group(1)}-{m.group(2)}"


# 이 PDF들은 왼쪽 단(대략 x<295) / 오른쪽 단(x>300) 2단 레이아웃이다.
COL_SPLIT_X = 200
Y_TOL = 3.0
X_GAP = 8.0


def column_lines(page, y_top=58, y_bottom=800):
    """페이지를 (왼쪽 단 위->아래) -> (오른쪽 단 위->아래) 순으로 정리한다.

    줄 묶기는 y 기준, 같은 줄 안에서 x 간격이 크면(단 경계) 별도 조각으로 자른다.
    """
    words = [w for w in page.get_text("words") if w[4].strip()]
    if not words:
        return []
    words.sort(key=lambda w: (w[1], w[0]))
    lines, cur, cy = [], [], None
    for w in words:
        if cy is None or abs(w[1] - cy) <= Y_TOL:
            cur.append(w)
            cy = w[1] if cy is None else cy
        else:
            lines.append(cur)
            cur, cy = [w], w[1]
    if cur:
        lines.append(cur)

    cells = []
    for ln in lines:
        ln.sort(key=lambda w: w[0])
        part = [ln[0]]
        for prev, w in zip(ln, ln[1:]):
            if w[0] - prev[2] > X_GAP:
                cells.append(part)
                part = []
            part.append(w)
        cells.append(part)

    out = []
    for part in cells:
        x0 = min(w[0] for w in part)
        out.append(
            {
                "col": 0 if x0 < COL_SPLIT_X else 1,
                "y": min(w[1] for w in part),
                "x": x0,
                "text": " ".join(w[4] for w in part),
            }
        )
    out.sort(key=lambda c: (c["col"], round(c["y"] / Y_TOL), c["x"]))
    return [c for c in out if y_top < c["y"] < y_bottom]


def split_choices(text):
    """한 줄에 ①~④가 두 개 이상 붙어 있을 수 있으므로 마커 기준으로 자른다."""
    parts = re.split(f"([{CIRCLE}])", text)
    out = []
    for i in range(1, len(parts), 2):
        out.append({"mark": parts[i], "text": parts[i + 1].strip()})
    return out


def parse_answers(doc):
    """정답표 페이지에서 '1.④' / '1. ④' 형태를 뽑는다."""
    answers, pages, per_page = {}, [], {}
    for pno in range(doc.page_count):
        raw = doc[pno].get_text()
        found = {
            int(m.group(1)): CIRCLE.index(m.group(2)) + 1
            for m in re.finditer(r"(\d{1,3})\s*[.\s]\s*([①②③④])", raw)
            if 1 <= int(m.group(1)) <= 100
        }
        if len(found) >= 15:
            pages.append(pno)
            per_page[pno] = found
            for k, v in sorted(found.items()):
                answers.setdefault(k, v)
    return answers, pages


def parse_exam(pdf: Path):
    doc = pymupdf.open(pdf)
    answers, answer_pages = parse_answers(doc)
    q_end = min(answer_pages) if answer_pages else doc.page_count

    rows = []
    for pno in range(q_end):
        for ln in column_lines(doc[pno]):
            t = ln["text"].strip()
            if not t or NOISE_RE.search(t):
                continue
            if t.startswith("※") or t.startswith("다음 문제를 읽고"):
                continue
            rows.append({"page": pno + 1, "y": ln["y"], "x": ln["x"], "col": ln["col"], "text": t})

    subject, subject_of = None, {}
    questions, cur = [], None
    for r in rows:
        sm = SUBJECT_RE.search(r["text"])
        if sm:
            subject = sm.group(2).strip()
            continue
        m = QSTART_RE.match(r["text"])
        num = int(m.group(1)) if m else None
        if m and num is not None and 1 <= num <= 100:
            if cur:
                questions.append(cur)
            cur = {"number": num, "page": r["page"], "y": r["y"], "x": r["x"], "lines": [m.group(2)]}
            subject_of[num] = subject
            continue
        if cur:
            cur["lines"].append(r["text"])
            cur["pageEnd"] = r["page"]
    if cur:
        questions.append(cur)

    # 번호 중복/누락 정리: 1..100 순서를 유지하며 중복 번호는 병합
    merged, seen = [], {}
    for q in questions:
        n = q["number"]
        if n in seen:
            seen[n]["lines"].extend(q["lines"])
            continue
        seen[n] = q
        merged.append(q)

    exam = {
        "id": slug(pdf.name),
        "file": pdf.name,
        "questions": [],
    }
    for q in merged:
        stem_parts, choices = [], []
        for ln in q["lines"]:
            cs = split_choices(ln)
            if cs:
                if not choices:
                    head = ln.split(ln.strip()[0])[0].strip()
                    if head:
                        stem_parts.append(head)
                for c in cs:
                    choices.append(c)
            elif choices:
                choices[-1]["text"] += " " + ln
            else:
                stem_parts.append(ln)
        exam["questions"].append(
            {
                "number": q["number"],
                "subject": SUBJECTS[subject_code(q["number"])]["name"],
                "subjectCode": subject_code(q["number"]),
                "page": q["page"],
                "pageEnd": q.get("pageEnd", q["page"]),
                "y": round(q["y"], 1),
                "x": round(q.get("x", 0), 1),
                "col": 0 if q.get("x", 0) < COL_SPLIT_X else 1,
                "stem": re.sub(r"\s+", " ", " ".join(stem_parts)).strip(),
                "choices": [re.sub(r"\s+", " ", c["text"]).strip() for c in choices],
                "choiceMarks": [c["mark"] for c in choices],
                "answer": answers.get(q["number"]),
            }
        )
    return exam


def page_text(exam_id, lo=1, hi=None):
    """회차의 특정 페이지를 읽기 순서 텍스트로 덤프한다(해설 페이지 확인용)."""
    pdf = _pdf_of(exam_id)
    doc = pymupdf.open(pdf)
    hi = hi or doc.page_count
    out_dir = OUT / "text"
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for pno in range(lo - 1, min(hi, doc.page_count)):
        lines = [l["text"] for l in column_lines(doc[pno], y_top=58)]
        p = out_dir / f"{exam_id}-p{pno + 1:02d}.txt"
        p.write_text("\n".join(lines), encoding="utf-8")
        paths.append(p)
    return paths


def render_pages(exam_id, pages=None, dpi=130):
    """페이지를 PNG로 렌더링한다(텍스트가 깨진 문항을 눈으로 확인할 때 사용)."""
    pdf = _pdf_of(exam_id)
    doc = pymupdf.open(pdf)
    out_dir = OUT / "pages" / exam_id
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = pages or range(1, doc.page_count + 1)
    paths = []
    for pno in targets:
        p = out_dir / f"p{pno:02d}.png"
        if not p.exists():
            doc[pno - 1].get_pixmap(dpi=dpi).save(p)
        paths.append(p)
    return paths


def _pdf_of(exam_id):
    for pdf in DATA.glob("*.pdf"):
        if slug(pdf.name) == exam_id:
            return pdf
    raise SystemExit(f"회차를 찾을 수 없음: {exam_id}")


def build_all():
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"{'id':9s} {'q':>4s} {'dup':>4s} {'miss':>5s} {'badCh':>6s} {'noAns':>6s}  file")
    for pdf in sorted(DATA.glob("*.pdf")):
        exam = parse_exam(pdf)
        (OUT / f"{exam['id']}.json").write_text(
            json.dumps(exam, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        nums = [q["number"] for q in exam["questions"]]
        dup = len(nums) - len(set(nums))
        missing = sorted(set(range(1, 101)) - set(nums))
        bad = [q["number"] for q in exam["questions"] if len(q["choices"]) != 4]
        noans = [q["number"] for q in exam["questions"] if q["answer"] is None]
        print(
            f"{exam['id']:9s} {len(nums):4d} {dup:4d} {len(missing):5d} {len(bad):6d} {len(noans):6d}  {pdf.name[:34]}"
        )
        if missing:
            print(f"{'':9s}  missing: {missing[:20]}")
        if bad:
            print(f"{'':9s}  badChoices: {bad[:20]}")


def configure_output():
    """파이프·리다이렉트(cp949)에서도 출력 때문에 죽지 않게 stdout·stderr 를 UTF-8 로 고정한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main(argv):
    configure_output()
    if argv and argv[0] == "dump":
        for p in page_text(argv[1], int(argv[2]) if len(argv) > 2 else 1, int(argv[3]) if len(argv) > 3 else None):
            print(p)
        return 0
    if argv and argv[0] == "render":
        for p in render_pages(argv[1], [int(x) for x in argv[2:]] or None):
            print(p)
        return 0
    return build_all()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
