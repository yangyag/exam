"""회차 간 문항 중복 행렬 분석.

같은 지문 + 같은 보기 4개 = 동일 문항으로 보고 회차 쌍별 중복 수를 센다.
"""
import json
import re
import sys
from collections import defaultdict
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
    rounds = {}
    for f in sorted((DATA / "questions").rglob("*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        rid = doc["exam"]["id"]
        rounds.setdefault(rid, {})
        for q in doc["questions"]:
            key = norm(q["stem"]) + "||" + "|".join(norm(c["text"]) for c in q["choices"])
            rounds[rid][key] = q["number"]

    ids = sorted(rounds)
    print("회차별 고유 문항 수:")
    for r in ids:
        print(f"  {r}: {len(rounds[r])}")

    print("\n회차 쌍별 동일 문항 수:")
    header = "        " + " ".join(f"{r:>8s}" for r in ids)
    print(header)
    for a in ids:
        row = f"{a:>8s}"
        for b in ids:
            n = len(set(rounds[a]) & set(rounds[b]))
            row += f" {n:>8d}"
        print(row)

    # 전체 고유 문항
    allkeys = defaultdict(list)
    for r in ids:
        for k, n in rounds[r].items():
            allkeys[k].append((r, n))
    print(f"\n전체 문항 {sum(len(rounds[r]) for r in ids)}개 / 고유 문항 {len(allkeys)}개")
    dist = defaultdict(int)
    for k, v in allkeys.items():
        dist[len(v)] += 1
    for cnt in sorted(dist):
        print(f"  {cnt}개 회차에 등장: {dist[cnt]}문항")

    # 중복 1위 예시 자세히
    top = sorted(allkeys.items(), key=lambda kv: -len(kv[1]))[:5]
    print("\n가장 많이 반복된 문항:")
    for k, v in top:
        doc = json.loads((DATA / "questions" / v[0][0] / "1.json").read_text(encoding="utf-8"))
        q = next((x for x in doc["questions"] if x["number"] == v[0][1]), None)
        stem = q["stem"] if q else k[:50]
        print(f"  {len(v)}회 등장 {v}")
        print(f"     {stem[:90]}")

    # 회차별 중복 제거 후 남는 고유 문항
    print("\n회차별 '그 회차에서 처음 보는 문항' 수 (연대순 누적):")
    seen = set()
    for r in ids:
        new = [k for k in rounds[r] if k not in seen]
        seen |= set(rounds[r])
        print(f"  {r}: 신규 {len(new):3d} / 중복 {100 - len(new):3d}")


if __name__ == "__main__":
    sys.exit(main())
