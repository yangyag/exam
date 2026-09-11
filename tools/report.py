"""데이터셋 전체 품질 리포트 (독립 교차 검증용).

- raw JSON 의 정답과 최종 JSON 의 정답을 대조한다
- passageKind / figure / provenance 분포를 낸다
- 참조되지 않는 고아 이미지 파일을 찾는다
- 회차 간 중복 문항을 찾는다
"""
import glob
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def norm(s):
    return re.sub(r"[\s.,·・()\[\]{}'\"“”‘’…?!~\-]", "", s)


def configure_output():
    """파이프·리다이렉트(cp949)에서도 출력 때문에 죽지 않게 stdout·stderr 를 UTF-8 로 고정한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    configure_output()
    files = sorted((DATA / "questions").rglob("*.json"))
    qs = []
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        for q in doc["questions"]:
            q["_exam"] = doc["exam"]["id"]
            q["_file"] = f
            qs.append(q)

    print(f"파일 {len(files)}개 / 문항 {len(qs)}개")

    rounds = Counter(q["_exam"] for q in qs)
    print(f"회차 {len(rounds)}개: " + ", ".join(f"{k}({v})" for k, v in sorted(rounds.items())))

    # 1) 정답 교차검증
    mismatch = []
    for q in qs:
        raw = json.loads((DATA / "raw" / f"{q['_exam']}.json").read_text(encoding="utf-8"))
        rq = next((x for x in raw["questions"] if x["number"] == q["number"]), None)
        if rq and rq["answer"] != q["answer"]:
            mismatch.append((q["_exam"], q["number"], rq["answer"], q["answer"]))
    print(f"\n[정답 교차검증] raw 와 불일치: {len(mismatch)}건")
    for m in mismatch[:20]:
        print(f"   {m[0]} {m[1]}번: raw={m[2]} -> json={m[3]}")

    # 2) provenance
    pa = Counter(q["provenance"]["answer"] for q in qs)
    pe = Counter(q["provenance"]["explanation"] for q in qs)
    print(f"\n[provenance] answer={dict(pa)}  explanation={dict(pe)}")

    # 3) passageKind
    pk = Counter(q["passageKind"] for q in qs)
    print(f"[passageKind] {dict(pk)}")

    # 4) figure
    figs = [q for q in qs if q["figure"]["needed"]]
    print(f"\n[그림] needed=true {len(figs)}문항 / 이미지 지정 {sum(1 for q in qs if q['figure']['image'])}문항")
    for q in figs:
        print(f"   {q['_exam']} {q['number']:3d}번 page{q['figure']['page']} {q['figure']['kind']:8s} {q['figure']['image']}")

    used = {q["figure"]["image"] for q in qs if q["figure"]["image"]}
    on_disk = {p.relative_to(DATA).as_posix() for p in (DATA / "figures").rglob("*.png")}
    orphans = sorted(on_disk - used)
    print(f"   이미지 파일 {len(on_disk)}개 / 참조 {len(used)}개 / 고아 {len(orphans)}개 {orphans}")

    # 5) 중복은 tools/dups.py 에서 별도 분석 (회차 간/회차 내 완전 중복)
    print("\n[중복] 회차 간·회차 내 중복 분석은 `python tools/dups.py` 참고")

    # 6) 잔여물 의심
    BAD = re.compile(r"[,、]\s*[,、]|제\s*\d\s*과목|있고여러|이며뷰마다|^\s*$")
    sus = []
    for q in qs:
        blob = q["stem"] + " " + " ".join(c["text"] for c in q["choices"])
        if BAD.search(blob):
            sus.append((q["_exam"], q["number"], BAD.search(blob).group(0)))
    print(f"\n[잔여물 의심] {len(sus)}건")
    for s in sus[:15]:
        print(f"   {s[0]} {s[1]}번: {s[2]!r}")

    # 7) 용량
    def size(p):
        return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())

    print(f"\n[용량] questions {size(DATA / 'questions') / 1024:.0f}KB / figures {size(DATA / 'figures') / 1024:.0f}KB")


if __name__ == "__main__":
    sys.exit(main())
