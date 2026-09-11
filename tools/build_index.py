"""앱 진입점이 될 data/index.json 을 생성한다.

문항 파일을 훑어서 회차/과목/파일경로/문항 수를 모은다.
경로는 모두 data/ 기준 상대경로이고 슬래시(/)를 쓴다.
(figure.image 도 같은 규칙이라 앱에서 `data/` + path 로 바로 붙일 수 있다)
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "index.json"

SUBJECTS = [
    {"code": 1, "name": "소프트웨어 설계", "from": 1, "to": 20},
    {"code": 2, "name": "소프트웨어 개발", "from": 21, "to": 40},
    {"code": 3, "name": "데이터베이스 구축", "from": 41, "to": 60},
    {"code": 4, "name": "프로그래밍 언어 활용", "from": 61, "to": 80},
    {"code": 5, "name": "정보시스템 구축 관리", "from": 81, "to": 100},
]


def build():
    exams = []
    for path in sorted((DATA / "questions").glob("*/*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        exam, subject, questions = doc["exam"], doc["subject"], doc["questions"]
        with_figure = sum(1 for q in questions if q["figure"]["needed"])
        entries = [
            {
                "code": subject["code"],
                "name": subject["name"],
                "from": questions[0]["number"],
                "to": questions[-1]["number"],
                "questionCount": len(questions),
                "file": path.relative_to(DATA).as_posix(),
            }
        ]
        if subject["code"] == 1:
            base = {
                "id": exam["id"],
                "year": exam["year"],
                "round": exam["round"],
                "title": exam["title"],
                "sourcePdf": exam["sourcePdf"],
                "questionCount": 0,
                "figureCount": 0,
                "subjects": [],
            }
            exams.append(base)
        base = exams[-1]
        base["subjects"].append(entries[0])
        base["questionCount"] += len(questions)
        base["figureCount"] += with_figure

    for e in exams:
        e["subjects"].sort(key=lambda s: s["code"])

    exams.sort(key=lambda e: (e["year"], e["round"]), reverse=True)

    return {
        "schemaVersion": 1,
        "generatedAt": date.today().isoformat(),
        "description": "정보처리기사 필기 기출문제 데이터셋 인덱스",
        "pathBase": "data/",
        "note": "file / figure.image 경로는 모두 data/ 기준 상대경로입니다.",
        "stats": {
            "examCount": len(exams),
            "questionCount": sum(e["questionCount"] for e in exams),
            "subjectCount": len(SUBJECTS),
            "figureCount": sum(e["figureCount"] for e in exams),
        },
        "subjects": SUBJECTS,
        "exams": exams,
    }


def main():
    index = build()
    OUT.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    s = index["stats"]
    print(f"{OUT}")
    print(f"회차 {s['examCount']}개 / 문항 {s['questionCount']}개 / 그림 {s['figureCount']}개")
    for e in index["exams"][:3]:
        print(f"  {e['id']} {e['title']} 문항 {e['questionCount']} 과목 {len(e['subjects'])} 그림 {e['figureCount']}")
    print("  ...")
    for e in index["exams"][-1:]:
        print(f"  {e['id']} {e['title']} 문항 {e['questionCount']} 과목 {len(e['subjects'])} 그림 {e['figureCount']}")
    missing = []
    for e in index["exams"]:
        for s2 in e["subjects"]:
            if not (DATA / s2["file"]).exists():
                missing.append(s2["file"])
        if e["questionCount"] != 100:
            missing.append(f"{e['id']} 문항수 {e['questionCount']}")
    print("검증:", "이상 없음" if not missing else f"문제 {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
