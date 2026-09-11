# ipe 스키마 (정보처리기사 필기 기출문제 데이터셋)

`app` 데이터베이스 안에 `ipe` 스키마로 들어갑니다. **소유자와 접속 계정은 기존 앱과 동일한 `yangyag`** 입니다.
기존 `english` / `english_test` 스키마는 건드리지 않습니다.

## 무엇이 들어가나

| 테이블 | 행 수 | 내용 |
|---|---|---|
| `subject` | 5 | 과목 (1~5과목, 각 20문항) |
| `exam` | 13 | 회차. id 형식 `2026-1` |
| `question` | 1,300 | 문항. `doc jsonb` 에 원본 JSON 통째로 보관 |
| `question_choice` | 5,200 | 보기 4개. 정답 여부(`is_correct`)와 보기별 해설(`why`) 포함 |
| `tag` | 1,281 | 복습용 키워드 |
| `question_tag` | 3,347 | 문항–태그 연결 |

그림은 파일로 서빙합니다. DB에는 `question.figure_image` 경로(`figures/2026-1/099.png`, `data/` 기준 상대경로)와 `figure_alt` 만 들어갑니다.

## ⚠ search_path 주의

`yangyag` 역할의 `search_path` 는 `english, public` 입니다(기존 영어 앱이 쓰고 있음). **이 역할 전역 설정은 바꾸지 않았습니다** — 바꾸면 기존 앱이 영향을 받습니다.

따라서 `ipe` 테이블을 쓸 때는 다음 중 하나로 접근하세요.

```sql
-- 1) 스키마를 명시
select * from ipe.question;

-- 2) 접속 시 search_path 지정 (앱에서 권장)
--   postgresql://yangyag:***@localhost:5432/app?options=-csearch_path%3Dipe,public
--   또는 접속 직후:  SET search_path = ipe, public;
```

`tools/load_db.py` 는 접속할 때 세션 `search_path` 를 `ipe,public` 으로 고정하므로 역할 설정과 무관하게 동작합니다.

## 실행 순서

### 0) 접속 정보 준비

```bash
cp .env.example .env      # 그리고 EXAM_DB_URL 값에 비밀번호를 채웁니다 (.env 는 git 에 안 들어감)
```

### 1) 스키마·역할 준비 (superuser, 최초 1회)

```bash
# 로컬(docker)
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql

# EC2 등 psql 이 직접 있는 서버
psql -U postgres -d app -f db/000_bootstrap.sql
```

`yangyag` 역할이 없으면 만들고(비밀번호는 실행 후 교체), `ipe` 스키마를 `yangyag` 소유로 만들고, `pg_trgm` 확장을 설치합니다. **이미 있으면 아무것도 바꾸지 않습니다.**

### 2) 테이블 생성 + 데이터 적재

```bash
python tools/load_db.py --init     # db/001_schema.sql 적용
python tools/load_db.py            # data/questions 전체 적재 + 검증
```

두 명령 모두 **몇 번을 실행해도 같은 결과**입니다(멱등). JSON에서 사라진 문항은 적재 시 정리됩니다.

### 3) 검증만 다시

```bash
python tools/load_db.py --verify
```

행 수, 정답 분포(JSON 대조), 보기 4개 여부, 정답 1개 여부, 과목 범위, 그림 파일 존재를 확인합니다.

## 접속 문자열

`tools/load_db.py` 는 아래 순서로 접속 대상을 정합니다.

1. `EXAM_DB_URL` (환경변수 또는 저장소 루트 `.env`)
2. `DATABASE_URL`
3. libpq `PG*` 환경변수 (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`)
4. 기본값 `postgresql://yangyag@localhost:5432/app` (비밀번호 없음 → `.env` 나 환경변수를 쓰세요)

```bash
# EC2 예시
EXAM_DB_URL='postgresql://yangyag:<비번>@127.0.0.1:5432/app' python tools/load_db.py
```

## 처음부터 다시 만들기 (개발용)

```sql
DROP SCHEMA ipe CASCADE;   -- 데이터만 지움. 역할은 그대로 둔다
```

그 뒤 `000_bootstrap.sql` → `--init` → 적재 순서로 다시 만들면 됩니다.
(실제로 이 순서로 처음부터 재구축해서 검증했습니다.)

`app` 데이터베이스의 다른 스키마(`english`, `english_test`, `public`)에는 영향이 없습니다.

## 전체 파이프라인

```
data/*.pdf                    원본 기출문제
   │  python tools/extract.py          좌표 기반 문항 추출
   ▼
data/raw/<회차>.json          1차 추출 결과
   │  (문항 정리·해설 생성)
   ▼
data/questions/<회차>/<과목>.json    최종 문항 데이터 (git 에 들어감)
   │  python tools/build_index.py      앱 진입점
   ▼
data/index.json
   │  python tools/load_db.py          DB 적재
   ▼
PostgreSQL app.ipe
```

**EC2 에서는 PDF 부터 다시 돌릴 필요가 없습니다.** `data/questions/`, `data/figures/`, `data/index.json` 이 저장소에 있으므로 저장소를 받은 뒤 1) 부트스트랩 → 2) 적재만 하면 됩니다.

## 관련 도구

| 명령 | 설명 |
|---|---|
| `python tools/validate.py` | 문항 JSON 검증 (스키마 + 불변식) |
| `python tools/report.py` | 데이터셋 품질 리포트 |
| `python tools/dups.py` | 회차 간·회차 내 중복 문항 분석 |
| `python tools/build_index.py` | `data/index.json` 재생성 |
| `python tools/crop_figures.py` | 그림 크롭 재생성 |
| `python tools/scan_figures.py` | 그림 있는 문항 탐지 |
