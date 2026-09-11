# ipe 스키마 (정보처리기사 필기 기출문제 데이터셋)

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

## 실행 순서

### 1) 역할·스키마 생성 (superuser, 최초 1회)

```bash
# 로컬(docker)
docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql

# EC2 등 psql 이 직접 있는 서버
psql -U postgres -d app -f db/000_bootstrap.sql
```

`exam` 역할(LOGIN만) / `ipe` 스키마(소유자 exam) / `pg_trgm` 확장을 만듭니다. **운영 서버에서는 실행 후 비밀번호를 바꾸세요:**

```sql
ALTER ROLE exam PASSWORD '<새비번>';
```

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

1. `EXAM_DB_URL`
2. `DATABASE_URL`
3. libpq `PG*` 환경변수 (`PGHOST`/`PGPORT`/`PGUSER`/`PGPASSWORD`/`PGDATABASE`)
4. 기본값 `postgresql://exam:exam@localhost:5432/app`

```bash
# 예: EC2
EXAM_DB_URL='postgresql://exam:<비번>@127.0.0.1:5432/app' python tools/load_db.py
```

앱에서 접속할 때는 역할에 `search_path` 가 `ipe, public` 으로 잡혀 있어 `select * from question` 이 바로 동작합니다.

## 처음부터 다시 만들기 (개발용)

```sql
DROP SCHEMA ipe CASCADE;
DROP ROLE exam;
```

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
