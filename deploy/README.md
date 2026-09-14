# exam 배포 (EC2)

정보처리기사 학습 앱의 운영 배포. **로컬에서 이미지를 빌드해 tar 로 올리고 EC2 에서 로드**하는 방식이다(EC2 에서는 빌드하지 않는다).

## 구성

```
인터넷 → 호스트 nginx (yangyag5.duckdns.org, TLS/certbot)
          └→ exam-front 컨테이너 (nginx, 127.0.0.1:8091)
               ├ 정적 파일: Nuxt SPA (nuxt generate 결과)
               └ /api·/figures → exam-back 컨테이너 (uvicorn 8092)
                                   └→ yangyag-postgres (공용, exam DB · 네트워크 auto_default)
```

- EC2: `43.202.113.123` (ubuntu), 앱 디렉터리 `/home/ubuntu/exam`
- 이미지: `exam-back:1.0`, `exam-front:1.0` (linux/amd64)
- 같은 오리진 구성이라 **CORS 설정과 쓰기 토큰(`EXAM_API_TOKEN`)이 필요 없다**
- 로컬 개발은 기존대로 프론트 8091 / 백엔드 8092 를 쓴다(이 구성과 무관)

## 전제

- 로컬(배포 스크립트 실행)에 **도커**와 EC2 키 `aws/test-keypair.pem` 이 있어야 한다.
- EC2 에 공용 컨테이너 **`yangyag-postgres`** 와 external 네트워크 **`auto_default`** 가 이미 있어야 한다(이 앱은 기존 앱 네트워크에 함께 붙는다).
- EC2 호스트에 **nginx + certbot** 이 준비돼 있어야 한다(`yangyag4` 와 같은 방식).
- DB 역할 **`yangyag`** 은 없을 때만 만든다(절차·주의는 §1).

## 최초 배포 절차

### 1) DB 준비 (한 번만)

로컬에서 `ipe` 스키마를 덤프해 EC2 의 기존 postgres 컨테이너에 새 데이터베이스로 복원한다.

**운영 DB 스키마 변경·최초 구축은 이 덤프 복원이 표준이다.** `tools/load_db.py --init` 은 로컬·신규 구축 경로이고, `db/000_bootstrap.sql` 은 `app` DB명이 하드코딩(`GRANT CONNECT ON DATABASE app`, 30행)이라 `exam` DB 에 그대로 쓰면 실패하므로 대상 DB명으로 바꿔야 한다.

```bash
# 로컬(저장소 루트) — 구조+데이터 (그림은 파일 서빙이라 DB에 없다)
#   주의: 로컬 컨테이너 이름은 postgres, EC2 는 yangyag-postgres 다.
docker exec postgres pg_dump -U yangyag -d app -n ipe --no-owner -Fc > /tmp/exam-ipe.dump

# EC2 로 전송
scp -i aws/test-keypair.pem /tmp/exam-ipe.dump ubuntu@43.202.113.123:/home/ubuntu/exam/
```

```bash
# EC2 — 계정·소유자는 기존 앱과 같은 yangyag 다(비밀번호는 .env 에만 적는다).
#   역할이 없을 때만 만든다(이미 있으면 건너뛴다 — db/000_bootstrap.sql 14~24행과 같은 판단).
docker exec yangyag-postgres psql -U auto -d postgres -c "CREATE ROLE yangyag LOGIN PASSWORD '<비번>'"

# EC2 — DB 생성 후 복원
docker exec yangyag-postgres psql -U auto -d postgres -c "CREATE DATABASE exam OWNER yangyag"
docker exec -i yangyag-postgres pg_restore -U auto -d exam --no-owner --role=yangyag < /home/ubuntu/exam/exam-ipe.dump
# 주의: 덤프에 CREATE EXTENSION 이 없어 trgm 인덱스 2개가 실패한다(경고 2건, 나머지는 정상).
#       확장을 만든 뒤 그 두 인덱스만 다시 만들면 된다.
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA ipe"
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE INDEX IF NOT EXISTS question_stem_trgm_idx ON ipe.question USING gin (stem ipe.gin_trgm_ops)"
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE INDEX IF NOT EXISTS question_expl_trgm_idx ON ipe.question USING gin (explanation ipe.gin_trgm_ops)"
#   방금 만든 인덱스는 superuser(auto) 소유가 되므로 yangyag 로 맞춘다.
#   (psql 세션에서 SET ROLE yangyag; 후 만들었다면 이 두 줄은 필요 없다)
docker exec yangyag-postgres psql -U auto -d exam -c "ALTER INDEX ipe.question_stem_trgm_idx OWNER TO yangyag"
docker exec yangyag-postgres psql -U auto -d exam -c "ALTER INDEX ipe.question_expl_trgm_idx OWNER TO yangyag"
rm -f /home/ubuntu/exam/exam-ipe.dump
```

운영 `exam` DB 의 소유자·접속 계정은 기존 앱과 같은 `yangyag` 다. 초기에는 전용 `exam` 역할을 썼지만 제거하고 `yangyag` 로 통일했다(옛 `exam` 역할은 더 이상 존재하지 않는다). 예전 덤프를 `--role=exam` 으로 복원해 둔 DB 가 있다면 `REASSIGN OWNED BY exam TO yangyag; ALTER DATABASE exam OWNER TO yangyag; DROP ROLE exam;` 로 이관한다.

덤프에는 진도 테이블(`study_*`)도 들어간다 — 로컬에서 눌러본 기록까지 운영으로 넘어가므로, 깨끗한 상태로 시작하려면 복원 후 비운다.

```bash
# EC2 — 진도만 초기화(문항·태그는 유지)
docker exec yangyag-postgres psql -U auto -d exam -c "TRUNCATE ipe.study_session_item, ipe.study_attempt, ipe.study_state, ipe.study_session, ipe.study_cycle RESTART IDENTITY"
```


### 2) EC2 앱 디렉터리 준비

```bash
# EC2
cd /home/ubuntu/exam
# 이 저장소의 deploy/docker-compose.yml, deploy/nginx-yangyag5-exam.conf 를 여기로 올린다
cat > .env <<'EOF'
# 컨테이너(exam-back)가 쓰는 값이라 호스트명이 서비스명 yangyag-postgres 다.
# 호스트 도구(load_db.py 등)에서 직접 쓸 때는 127.0.0.1 로 바꾼다(명령행 EXAM_DB_URL 이 .env 보다 우선).
EXAM_DB_URL=postgresql://yangyag:<비번>@yangyag-postgres:5432/exam?options=-csearch_path%3Dipe,public
EOF
chmod 600 .env
```

### 3) 이미지 빌드·전송·기동 (로컬에서)

```bash
./deploy/deploy.sh          # 빌드 → tar → 전송 → docker load → compose up
```

### 4) 호스트 nginx + HTTPS (한 번만)

```bash
# EC2
sudo cp /home/ubuntu/exam/nginx-yangyag5-exam.conf /etc/nginx/sites-available/yangyag5-exam
sudo ln -sf /etc/nginx/sites-available/yangyag5-exam /etc/nginx/sites-enabled/yangyag5-exam
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d yangyag5.duckdns.org     # yangyag4 와 같은 방식
```

## 재배포 · 롤백

- 재배포: `./deploy/deploy.sh` 한 번이면 된다. 스크립트가 **덮어쓰기 전에 직전 이미지를 `before-<타임스탬프>` 태그로 자동 보존**한다(롤백 지점).
- `deploy/docker-compose.yml` 이나 호스트 nginx 설정(`deploy/nginx-yangyag5-exam.conf`)을 바꿨으면 먼저 §2처럼 EC2 로 다시 올리고(호스트 반영은 §4의 `cp`+`reload`), 그 뒤 `deploy.sh` 를 돌린다. 프론트 컨테이너 nginx(`deploy/front-nginx.conf`)는 이미지에 함께 구워지므로 `deploy.sh` 만으로 반영된다.
- 롤백: 보존 태그를 `1.0` 으로 되돌리고 컨테이너를 재생성한다.

```bash
# EC2 — 보존 태그 확인
docker images --format '{{.Repository}}:{{.Tag}}' | grep '^exam-' | sort

# 되돌리기(예: before-20260912-1500 로 복귀)
docker tag exam-front:before-20260912-1500 exam-front:1.0
docker tag exam-back:before-20260912-1500  exam-back:1.0
cd /home/ubuntu/exam && docker compose up -d --force-recreate

# 오래된 태그 정리(디스크 절약)
docker rmi exam-front:before-<오래된> exam-back:before-<오래된>
```

- DB 스키마 변경은 §1 덤프 복원으로 하므로, 스키마 변경이 있으면 배포 전에 `pg_dump` 로 백업한다. 문항 데이터만 다시 적재하는 길은 아래 데이터 갱신 절을 본다.

## 데이터 갱신 (문항 데이터만)

문항 JSON(`data/questions`)을 고쳐 반영할 때는 이미지 재배포 없이 EC2 저장소에서 적재만 다시 돌린다. 단 **그림 파일(`data/figures`)을 바꿨으면 백엔드 이미지에 구워지므로 `deploy.sh` 로 다시 올려야 한다**(`deploy/Dockerfile.back` 16행).

```bash
# EC2 — 저장소를 최신으로 맞춘 뒤(git pull 또는 로컬에서 scp)
cd /home/ubuntu/exam
# .env 의 EXAM_DB_URL 은 컨테이너용(호스트명 yangyag-postgres)이라 호스트에서는 127.0.0.1 로 바꿔 넘긴다.
# 명령행에서 준 EXAM_DB_URL 이 .env 값보다 우선한다(tools/load_db.py 의 resolve_url).
# psycopg 가 없으면: python3 -m pip install 'psycopg[binary]'
export EXAM_DB_URL='postgresql://yangyag:<비번>@127.0.0.1:5432/exam?options=-csearch_path%3Dipe,public'
python3 tools/load_db.py            # 적재 + 검증 (멱등)
python3 tools/load_db.py --verify   # 검증만
```

- 적재는 멱등이고 `study_*`(진도) 테이블은 직접 건드리지 않는다. 다만 **적재 중 삭제된 문항을 참조하던 진도 행은 외래키(`ON DELETE CASCADE`, `db/002_progress.sql`)로 함께 지워진다** — 문항 번호를 바꾸는 갱신은 피한다.
- 스키마 변경이 있으면 같은 접속 문자열로 `python3 tools/load_db.py --init` 을 먼저 돌린다(마이그레이션만 적용하고 적재는 하지 않는다).
- **§1 덤프 복원을 다시 돌리는 것은 진도와 충돌한다.** 덤프에 든 로컬 `study_*` 가 운영 기록과 섞이거나 키 중복으로 복원이 실패한다. 진도까지 되돌릴 게 아니면 복원 대신 위 적재만 하고, 정말 필요하면 §1 의 `TRUNCATE` 로 진도를 정리한다.

## 주의

- `aws/`(키)·`.env`(DB 암호)는 **커밋하지 않는다**. 이미지에도 굽지 않는다(런타임 env 로만).
- 이 배포는 별도 인증을 걸지 않는다(주소를 아는 사람은 사용할 수 있다). 필요하면 호스트 nginx 에 Basic Auth 를 추가한다.
- 앱 데이터 초기화가 필요하면 EC2 에서 `exam` DB 의 `study_*` 테이블만 비우면 된다(문항 데이터는 유지).
