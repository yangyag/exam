"""JSON 문항 데이터를 PostgreSQL(ipe 스키마)로 적재한다.

사용법:
    python tools/load_db.py --init     # db/*.sql 마이그레이션 적용 (000_bootstrap.sql 제외)
    python tools/load_db.py            # data/questions 전체 적재 (멱등)
    python tools/load_db.py --verify   # 적재 결과 검증

접속 문자열 결정 순서:
    1) EXAM_DB_URL 환경변수 (또는 저장소 루트 .env 파일 — git 에 안 들어감)
    2) DATABASE_URL
    3) libpq PG* 환경변수 (PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE)
    4) 기본값 postgresql://yangyag@localhost:5432/app

EC2 등 다른 서버에서 실행할 때(서버 안에서 실행 — DB는 yangyag-postgres 컨테이너의 exam DB):
    EXAM_DB_URL='postgresql://yangyag:<비번>@127.0.0.1:5432/exam' python tools/load_db.py
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB = ROOT / "db"
# db/000_bootstrap.sql 은 superuser(postgres) 권한과 psql 메타명령(\set, \echo)이 필요해
# psycopg 로 실행할 수 없다. --init 에서 제외하고 psql 로 직접 실행한다(db/README.md 참고).
BOOTSTRAP_SQL = "000_bootstrap.sql"
ENV_FILE = ROOT / ".env"
DEFAULT_URL = "postgresql://yangyag@localhost:5432/app"


def load_env_file(path=ENV_FILE):
    """`.env` 를 읽어 환경변수로 올린다. 이미 설정된 환경변수는 덮어쓰지 않는다."""
    loaded = set()
    if not path.exists():
        return loaded
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.add(key)
    return loaded


def resolve_url():
    """접속 문자열과 그 출처를 돌려준다. (문자열이 비면 libpq 환경변수를 쓴다는 뜻)"""
    from_file = load_env_file()
    for var in ("EXAM_DB_URL", "DATABASE_URL"):
        if os.environ.get(var):
            return os.environ[var], var + (" (.env)" if var in from_file else "")
    if any(os.environ.get(v) for v in ("PGHOST", "PGPORT", "PGUSER", "PGDATABASE", "PGPASSWORD")):
        return "", "libpq PG* 환경변수"
    return DEFAULT_URL, "기본값"


def redact(url):
    """접속 문자열에서 비밀번호를 가린다."""
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", url)


SEARCH_PATH = "ipe,public"


def connect():
    """접속. 접속 역할의 search_path 에 의존하지 않도록 이 세션의 search_path 를 고정한다."""
    url, src = resolve_url()
    print(f"DB 접속: {src} — {redact(url) if url else 'libpq 환경변수'} (search_path={SEARCH_PATH})")
    opts = {"options": f"-c search_path={SEARCH_PATH}"}
    return psycopg.connect(url, **opts) if url else psycopg.connect(**opts)


def migrations():
    """db/ 아래 마이그레이션 SQL 을 파일명 오름차순으로 돌려준다.

    부트스트랩(000_bootstrap.sql)은 superuser 권한과 psql 메타명령(\\set, \\echo)이 필요해
    psycopg 로 실행할 수 없으므로 제외한다. db/ 에 새 SQL 파일을 추가하면 자동으로 포함된다.
    """
    return [p for p in sorted(DB.glob("*.sql")) if p.name != BOOTSTRAP_SQL]


def init_schema(conn):
    files = migrations()
    if not files:
        print(f"--init: {DB.relative_to(ROOT).as_posix()}/*.sql 에 적용할 마이그레이션이 없음")
        return
    with conn.cursor() as cur:
        for path in files:
            cur.execute(path.read_text(encoding="utf-8"))
    conn.commit()
    print(f"--init: {', '.join(p.relative_to(ROOT).as_posix() for p in files)} 적용")
    print(f"  ({BOOTSTRAP_SQL} 제외: superuser 권한 + psql 메타명령(\\set, \\echo) 필요 — psql 로 직접 실행)")


def read_json():
    index = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    docs = []
    for f in sorted((DATA / "questions").glob("*/*.json")):
        docs.append(json.loads(f.read_text(encoding="utf-8")))
    return index, docs


def check_doc(doc):
    """적재 전 안전망. JSON 단계에서 이미 검증됐지만 한 번 더 확인한다."""
    exam_id = doc["exam"]["id"]
    for q in doc["questions"]:
        n = q["number"]
        if len(q["choices"]) != 4:
            raise ValueError(f"{exam_id} {n}번: 보기가 4개가 아님 ({len(q['choices'])})")
        if len(q["choicesAnalysis"]) != 4:
            raise ValueError(f"{exam_id} {n}번: choicesAnalysis 가 4개가 아님")
        correct = [c for c in q["choicesAnalysis"] if c["correct"]]
        if len(correct) != 1:
            raise ValueError(f"{exam_id} {n}번: 정답 표시가 {len(correct)}개")
        if correct[0]["no"] != q["answer"]:
            raise ValueError(f"{exam_id} {n}번: answer={q['answer']} 와 정답 보기 불일치")


def load(conn):
    index, docs = read_json()
    for doc in docs:
        check_doc(doc)

    exam_ids = [d["exam"]["id"] for d in docs]
    loaded_qids = []
    stats = {"exam": 0, "question": 0, "choice": 0, "analysis": 0, "tag": 0, "link": 0}

    with conn.cursor() as cur:
        # 1) 과목
        for s in index["subjects"]:
            cur.execute(
                """INSERT INTO subject (code, name, from_no, to_no) VALUES (%s, %s, %s, %s)
                   ON CONFLICT (code) DO UPDATE
                     SET name = EXCLUDED.name, from_no = EXCLUDED.from_no, to_no = EXCLUDED.to_no""",
                (s["code"], s["name"], s["from"], s["to"]),
            )
        stats["exam_subject"] = len(index["subjects"])

        # 2) 회차 + 문항
        for doc in docs:
            exam = doc["exam"]
            cur.execute(
                """INSERT INTO exam (id, year, round, title, source_pdf) VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (id) DO UPDATE
                     SET year = EXCLUDED.year, round = EXCLUDED.round,
                         title = EXCLUDED.title, source_pdf = EXCLUDED.source_pdf""",
                (exam["id"], exam["year"], exam["round"], exam["title"], exam["sourcePdf"]),
            )
            stats["exam"] += 1

            for q in doc["questions"]:
                fig, src, prov = q["figure"], q["source"], q["provenance"]
                cur.execute(
                    """INSERT INTO question (
                           id, exam_id, number, subject_code, stem, passage, passage_kind,
                           answer, explanation, key_point, difficulty,
                           figure_needed, figure_kind, figure_image, figure_alt,
                           figure_page, figure_col, figure_box,
                           source_pdf, source_page, prov_answer, prov_explanation, doc, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
                       ON CONFLICT (id) DO UPDATE SET
                           exam_id = EXCLUDED.exam_id, number = EXCLUDED.number,
                           subject_code = EXCLUDED.subject_code, stem = EXCLUDED.stem,
                           passage = EXCLUDED.passage, passage_kind = EXCLUDED.passage_kind,
                           answer = EXCLUDED.answer, explanation = EXCLUDED.explanation,
                           key_point = EXCLUDED.key_point, difficulty = EXCLUDED.difficulty,
                           figure_needed = EXCLUDED.figure_needed, figure_kind = EXCLUDED.figure_kind,
                           figure_image = EXCLUDED.figure_image, figure_alt = EXCLUDED.figure_alt,
                           figure_page = EXCLUDED.figure_page, figure_col = EXCLUDED.figure_col,
                           figure_box = EXCLUDED.figure_box, source_pdf = EXCLUDED.source_pdf,
                           source_page = EXCLUDED.source_page, prov_answer = EXCLUDED.prov_answer,
                           prov_explanation = EXCLUDED.prov_explanation, doc = EXCLUDED.doc,
                           updated_at = now()""",
                    (
                        q["id"], exam["id"], q["number"], q["subjectCode"], q["stem"],
                        q["passage"], q["passageKind"], q["answer"], q["explanation"],
                        q["keyPoint"], q["difficulty"],
                        fig["needed"], fig["kind"], fig["image"], fig["alt"],
                        fig["page"], fig["col"], fig["box"],
                        src["pdf"], src["page"], prov["answer"], prov["explanation"],
                        Jsonb(q),
                    ),
                )
                loaded_qids.append(q["id"])
                stats["question"] += 1

        # 3) 보기 + 보기별 해설 (한 테이블로 합쳐 저장)
        cur.execute("DELETE FROM question_choice WHERE question_id = ANY(%s)", (loaded_qids,))
        rows = []
        for doc in docs:
            for q in doc["questions"]:
                analysis = {c["no"]: c for c in q["choicesAnalysis"]}
                for c in q["choices"]:
                    a = analysis[c["no"]]
                    rows.append((q["id"], c["no"], c["text"], a["correct"], a["why"]))
        cur.executemany(
            """INSERT INTO question_choice (question_id, no, text, is_correct, why)
               VALUES (%s, %s, %s, %s, %s)""",
            rows,
        )
        stats["choice"] = len(rows)

        # 4) 태그
        cur.execute("DELETE FROM question_tag WHERE question_id = ANY(%s)", (loaded_qids,))
        seen_tags = set()
        for doc in docs:
            for q in doc["questions"]:
                for t in q["tags"]:
                    seen_tags.add(t)
                    cur.execute(
                        """INSERT INTO tag (name) VALUES (%s)
                           ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                           RETURNING id""",
                        (t,),
                    )
                    tag_id = cur.fetchone()[0]
                    cur.execute(
                        """INSERT INTO question_tag (question_id, tag_id) VALUES (%s, %s)
                           ON CONFLICT DO NOTHING""",
                        (q["id"], tag_id),
                    )
                    stats["link"] += 1
        stats["tag"] = len(seen_tags)

        # 5) 사라진 문항 정리 (적재한 회차 범위 안에서만)
        cur.execute(
            "DELETE FROM question WHERE exam_id = ANY(%s) AND NOT (id = ANY(%s))",
            (exam_ids, loaded_qids),
        )
        removed = cur.rowcount

        # 6) 참조되지 않는 태그 정리
        cur.execute("DELETE FROM tag WHERE id NOT IN (SELECT tag_id FROM question_tag)")
        orphan_tags = cur.rowcount

    conn.commit()

    with conn.cursor() as cur:
        cur.execute("ANALYZE ipe.question")
        cur.execute("ANALYZE ipe.question_choice")
        cur.execute("ANALYZE ipe.question_tag")
    conn.commit()

    print(f"적재 완료: 회차 {stats['exam']} / 과목 {stats['exam_subject']} / 문항 {stats['question']} / 보기 {stats['choice']}")
    print(f"          태그 {stats['tag']} / 태그 연결 {stats['link']} / 정리된 문항 {removed} / 정리된 태그 {orphan_tags}")
    return stats


def verify(conn):
    idx = json.loads((DATA / "index.json").read_text(encoding="utf-8"))
    json_answers = {}
    json_figures = []
    for f in sorted((DATA / "questions").glob("*/*.json")):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for q in doc["questions"]:
            json_answers[q["answer"]] = json_answers.get(q["answer"], 0) + 1
            if q["figure"]["image"]:
                json_figures.append(q["figure"]["image"])

    ok = True
    with conn.cursor() as cur:
        def one(sql, args=None):
            cur.execute(sql, args)
            return cur.fetchone()[0]

        counts = {
            "exam": one("SELECT count(*) FROM exam"),
            "subject": one("SELECT count(*) FROM subject"),
            "question": one("SELECT count(*) FROM question"),
            "question_choice": one("SELECT count(*) FROM question_choice"),
            "tag": one("SELECT count(*) FROM tag"),
            "question_tag": one("SELECT count(*) FROM question_tag"),
        }
        expect = {
            "exam": idx["stats"]["examCount"],
            "subject": idx["stats"]["subjectCount"],
            "question": idx["stats"]["questionCount"],
            "question_choice": idx["stats"]["questionCount"] * 4,
            "tag": None,
            "question_tag": None,
        }
        print("\n=== 행 수 ===")
        for k, v in counts.items():
            e = expect[k]
            mark = "OK " if (e is None or e == v) else "FAIL"
            if e is not None and e != v:
                ok = False
            print(f"  [{mark}] {k:16s} {v:6d}" + (f"  (기대 {e})" if e is not None else ""))

        print("\n=== 정합성 ===")
        checks = [
            ("보기가 4개가 아닌 문항", "SELECT count(*) FROM (SELECT question_id FROM question_choice GROUP BY 1 HAVING count(*) <> 4) t"),
            ("정답 표시가 1개가 아닌 문항", "SELECT count(*) FROM (SELECT question_id FROM question_choice GROUP BY 1 HAVING count(*) FILTER (WHERE is_correct) <> 1) t"),
            ("answer 와 정답 보기 불일치", "SELECT count(*) FROM question q JOIN question_choice c ON c.question_id = q.id AND c.is_correct WHERE c.no <> q.answer"),
            ("과목 범위를 벗어난 문항 번호", "SELECT count(*) FROM question q JOIN subject s ON s.code = q.subject_code WHERE q.number NOT BETWEEN s.from_no AND s.to_no"),
            ("회차별 문항 수가 100이 아닌 회차", "SELECT count(*) FROM (SELECT exam_id FROM question GROUP BY 1 HAVING count(*) <> 100) t"),
            ("그림 문항인데 이미지 경로 없음", "SELECT count(*) FROM question WHERE figure_needed AND figure_image IS NULL"),
            ("passage 와 passage_kind 짝 불일치", "SELECT count(*) FROM question WHERE (passage IS NULL) <> (passage_kind IS NULL)"),
        ]
        for label, sql in checks:
            v = one(sql)
            mark = "OK " if v == 0 else "FAIL"
            if v:
                ok = False
            print(f"  [{mark}] {label:32s} {v}")

        print("\n=== 정답 분포 (JSON 대조) ===")
        cur.execute("SELECT answer, count(*) FROM question GROUP BY 1 ORDER BY 1")
        db_dist = dict(cur.fetchall())
        match = db_dist == json_answers
        ok = ok and match
        print(f"  [{'OK ' if match else 'FAIL'}] JSON {json_answers} / DB {db_dist}")

        print("\n=== 그림 파일 ===")
        missing = [p for p in json_figures if not (DATA / p).exists()]
        ok = ok and not missing
        print(f"  [{'OK ' if not missing else 'FAIL'}] {len(json_figures) - len(missing)}/{len(json_figures)} 파일 존재" + (f"  누락 {missing}" if missing else ""))

        print("\n=== 조회 예시 (앱이 쓰는 형태) ===")
        cur.execute(
            """SELECT q.id, q.number, q.stem, q.answer, q.difficulty,
                      array_agg(t.name ORDER BY t.name) AS tags
                 FROM question q
                 LEFT JOIN question_tag qt ON qt.question_id = q.id
                 LEFT JOIN tag t ON t.id = qt.tag_id
                WHERE q.exam_id = %s AND q.subject_code = %s AND q.figure_needed
                GROUP BY q.id, q.number, q.stem, q.answer, q.difficulty
                ORDER BY q.number LIMIT 1""",
            (idx["exams"][0]["id"], 5),
        )
        row = cur.fetchone()
        if row:
            qid, num, stem, ans, diff, tags = row
            print(f"  {qid} ({num}번) 난이도 {diff} 정답 {ans}")
            print(f"    {stem}")
            print(f"    태그: {tags}")
            cur.execute(
                "SELECT no, is_correct, text, why FROM question_choice WHERE question_id = %s ORDER BY no",
                (qid,),
            )
            for no, corr, text, why in cur.fetchall():
                print(f"    {'*' if corr else ' '} {no}. {text[:60]}")
                print(f"        └ {why[:80]}")
            fimg = one("SELECT figure_image FROM question WHERE id = %s", (qid,))
            print(f"    그림: data/{fimg}")
        else:
            print("  (해당 조건의 문항 없음)")

        print("\n=== 회차별 요약 ===")
        cur.execute(
            """SELECT exam_id, count(*) AS 문항, count(*) FILTER (WHERE figure_needed) AS 그림
                 FROM question GROUP BY 1 ORDER BY 1 DESC"""
        )
        for eid, n, fig in cur.fetchall():
            print(f"  {eid:8s} 문항 {n:3d}  그림 {fig}")

    print(f"\n검증 결과: {'전부 통과' if ok else '실패 항목 있음'}")
    return 0 if ok else 1


def configure_output():
    """파이프·리다이렉트(cp949)에서도 출력 때문에 죽지 않게 stdout·stderr 를 UTF-8 로 고정한다."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def main():
    configure_output()
    ap = argparse.ArgumentParser(description="기출문제 JSON → PostgreSQL(ipe) 적재")
    ap.add_argument("--init", action="store_true", help="db/*.sql 마이그레이션 적용 (000_bootstrap.sql 제외)")
    ap.add_argument("--verify", action="store_true", help="적재 결과 검증")
    args = ap.parse_args()

    with connect() as conn:
        if args.init:
            init_schema(conn)
            return 0
        if args.verify:
            return verify(conn)
        load(conn)
        return verify(conn)


if __name__ == "__main__":
    sys.exit(main())
