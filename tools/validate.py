"""문항 JSON 검증기.

사용법:
    python tools/validate.py data/questions/2026-1/1.json [또는 여러 파일/디렉터리]
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

REQUIRED_Q = [
    "id", "number", "subjectCode", "stem", "passage", "passageKind", "choices",
    "answer", "explanation", "choicesAnalysis", "keyPoint", "tags", "difficulty",
    "figure", "source", "provenance",
]
SUBJECT_RANGE = {1: (1, 20), 2: (21, 40), 3: (41, 60), 4: (61, 80), 5: (81, 100)}
BAD_SPACING = re.compile(r"[,、]\s*[,、]|\(\s*[,、]|있고여러|이며뷰마다")
IMAGE_RE = re.compile(r"^figures/[0-9]{4}-[0-9]/[0-9]{3}\.png$")


def check_question(q, path, exam_id, errs):
    tag = f"{path.name}#{q.get('number', '?')}"
    for k in REQUIRED_Q:
        if k not in q:
            errs.append(f"{tag}: 필드 누락 '{k}'")
    for k in ("stem", "explanation", "keyPoint"):
        v = q.get(k)
        if not isinstance(v, str) or len(v.strip()) < 5:
            errs.append(f"{tag}: '{k}' 가 비었거나 너무 짧음")
    passage = q.get("passage")
    kind = q.get("passageKind")
    if passage is None:
        if kind is not None:
            errs.append(f"{tag}: passage 가 null 인데 passageKind={kind!r}")
    else:
        if not isinstance(passage, str):
            errs.append(f"{tag}: passage 는 문자열 또는 null")
        elif kind not in ("code", "table", "text"):
            errs.append(f"{tag}: passageKind 가 잘못됨 {kind!r}")
    ch = q.get("choices") or []
    if len(ch) != 4:
        errs.append(f"{tag}: 보기가 4개가 아님 ({len(ch)}개)")
    for i, c in enumerate(ch, 1):
        if c.get("no") != i:
            errs.append(f"{tag}: 보기 번호 불일치 {c.get('no')} (기대 {i})")
        t = c.get("text")
        if not isinstance(t, str) or not t.strip():
            errs.append(f"{tag}: 보기 {i} 텍스트 비었음 ({t!r})")
        elif BAD_SPACING.search(t):
            errs.append(f"{tag}: 보기 {i} 에 추출 잔여물 의심 '{t[:40]}'")
    a = q.get("answer")
    if not isinstance(a, int) or not 1 <= a <= 4:
        errs.append(f"{tag}: answer 는 1~4 정수 ({a!r})")
    ca = q.get("choicesAnalysis") or []
    if len(ca) != 4:
        errs.append(f"{tag}: choicesAnalysis 가 4개가 아님 ({len(ca)}개)")
    else:
        correct = [c for c in ca if c.get("correct")]
        if len(correct) != 1:
            errs.append(f"{tag}: 정답 표시가 {len(correct)}개 (1개여야 함)")
        elif a and correct[0].get("no") != a:
            errs.append(f"{tag}: answer={a} 인데 choicesAnalysis 정답은 {correct[0].get('no')}")
        for c in ca:
            w = c.get("why")
            if not isinstance(w, str) or not w.strip():
                errs.append(f"{tag}: 보기 {c.get('no')} 해설 비었음 ({w!r})")
        for c in ca:
            if not isinstance(c.get("correct"), bool):
                errs.append(f"{tag}: 보기 {c.get('no')} correct 가 bool 이 아님 ({c.get('correct')!r})")
    if not isinstance(q.get("difficulty"), int) or not 1 <= q["difficulty"] <= 5:
        errs.append(f"{tag}: difficulty 는 1~5 정수")
    tags = q.get("tags")
    if not tags:
        errs.append(f"{tag}: tags 비었음")
    else:
        for t in tags:
            if not isinstance(t, str) or not t.strip():
                errs.append(f"{tag}: 태그가 비었거나 문자열이 아님 ({t!r})")

    fig = q.get("figure")
    if not isinstance(fig, dict):
        errs.append(f"{tag}: figure 누락")
    else:
        for k in ("needed", "kind", "image", "alt", "page", "col", "box"):
            if k not in fig:
                errs.append(f"{tag}: figure.{k} 누락")
        img = fig.get("image")
        if img is not None:
            if not IMAGE_RE.match(str(img)):
                errs.append(f"{tag}: figure.image 경로 규칙 위반 {img!r}")
            elif not (DATA / str(img)).exists():
                errs.append(f"{tag}: figure.image 파일 없음 {img}")
            if not str(fig.get("alt") or "").strip():
                errs.append(f"{tag}: figure.image 가 있는데 alt 가 없음")
            if not isinstance(fig.get("box"), list) or len(fig.get("box") or []) != 4:
                errs.append(f"{tag}: figure.image 가 있는데 box 가 없음")
        if fig.get("needed"):
            if fig.get("kind") not in ("diagram", "screen"):
                errs.append(f"{tag}: figure.needed=true 이면 kind 는 diagram/screen ({fig.get('kind')!r})")
            if not isinstance(fig.get("page"), int):
                errs.append(f"{tag}: figure.needed=true 인데 page 없음")
            if not img:
                errs.append(f"{tag}: figure.needed=true 인데 image 없음")
        if img is None and fig.get("box") is not None:
            errs.append(f"{tag}: image 가 없는데 box 가 있음")

    prov = q.get("provenance") or {}
    if prov.get("answer") not in ("pdf", "derived"):
        errs.append(f"{tag}: provenance.answer 값 오류 {prov.get('answer')!r}")
    if prov.get("explanation") not in ("pdf", "generated"):
        errs.append(f"{tag}: provenance.explanation 값 오류 {prov.get('explanation')!r}")
    src = q.get("source") or {}
    if not src.get("pdf") or not isinstance(src.get("page"), int):
        errs.append(f"{tag}: source.pdf/page 오류")


def check_file(path: Path):
    errs = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        return [f"{path}: JSON 파싱 실패 - {e}"], 0
    exam = doc.get("exam") or {}
    subject = doc.get("subject") or {}
    qs = doc.get("questions") or []
    for k in ("id", "year", "round", "title", "sourcePdf"):
        if k not in exam:
            errs.append(f"{path}: exam.{k} 누락")
    if subject.get("code") not in SUBJECT_RANGE:
        errs.append(f"{path}: subject.code 오류 {subject.get('code')!r}")
        return errs, len(qs)
    lo, hi = SUBJECT_RANGE[subject["code"]]
    nums = sorted(q["number"] for q in qs if isinstance(q.get("number"), int))
    expect = list(range(lo, hi + 1))
    if nums != expect:
        missing = sorted(set(expect) - set(nums))
        extra = sorted(set(nums) - set(expect))
        errs.append(f"{path}: 문항 번호 불일치 누락={missing} 범위밖={extra} (총 {len(nums)}개)")
    for q in qs:
        check_question(q, path, exam.get("id"), errs)
        if isinstance(q.get("number"), int) and q.get("id") != f"{exam.get('id')}-{q['number']:03d}":
            errs.append(f"{path}: id 규칙 오류 {q.get('id')!r}")
        if isinstance(q.get("number"), int) and q.get("subjectCode") != subject["code"]:
            errs.append(f"{path}: {q['number']}번 subjectCode 불일치")
    return errs, len(qs)


def main(argv):
    targets = []
    for a in argv:
        p = Path(a)
        if p.is_dir():
            targets.extend(sorted(p.rglob("*.json")))
        else:
            targets.append(p)
    if not targets:
        targets = sorted((DATA / "questions").rglob("*.json"))
    total = 0
    all_errs = []
    for t in targets:
        errs, n = check_file(t)
        total += n
        status = "OK " if not errs else "FAIL"
        print(f"[{status}] {t.as_posix():46s} 문항 {n:3d}  문제 {len(errs)}")
        all_errs.extend(errs)
    print(f"\n검사 파일 {len(targets)}개 / 문항 {total}개 / 오류 {len(all_errs)}건")
    for e in all_errs[:80]:
        print("  -", e)
    return 1 if all_errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
