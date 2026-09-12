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

## 최초 배포 절차

### 1) DB 준비 (한 번만)

로컬에서 `ipe` 스키마를 덤프해 EC2 의 기존 postgres 컨테이너에 새 데이터베이스로 복원한다.

```bash
# 로컬(저장소 루트) — 구조+데이터 (그림은 파일 서빙이라 DB에 없다)
#   주의: 로컬 컨테이너 이름은 postgres, EC2 는 yangyag-postgres 다.
docker exec postgres pg_dump -U yangyag -d app -n ipe --no-owner -Fc > /tmp/exam-ipe.dump

# EC2 로 전송
scp -i aws/test-keypair.pem /tmp/exam-ipe.dump ubuntu@43.202.113.123:/home/ubuntu/exam/
```

```bash
# EC2 — 역할·DB 생성 후 복원 (비밀번호는 여기서 정해 .env 에만 적는다)
docker exec yangyag-postgres psql -U auto -d postgres -c "CREATE ROLE exam LOGIN PASSWORD '<비번>'"
docker exec yangyag-postgres psql -U auto -d postgres -c "CREATE DATABASE exam OWNER exam"
docker exec -i yangyag-postgres pg_restore -U auto -d exam --no-owner --role=exam < /home/ubuntu/exam/exam-ipe.dump
# 주의: 덤프에 CREATE EXTENSION 이 없어 trgm 인덱스 2개가 실패한다(경고 2건, 나머지는 정상).
#       확장을 만든 뒤 그 두 인덱스만 다시 만들면 된다.
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA ipe"
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE INDEX IF NOT EXISTS question_stem_trgm_idx ON ipe.question USING gin (stem ipe.gin_trgm_ops)"
docker exec yangyag-postgres psql -U auto -d exam -c "CREATE INDEX IF NOT EXISTS question_expl_trgm_idx ON ipe.question USING gin (explanation ipe.gin_trgm_ops)"
rm -f /home/ubuntu/exam/exam-ipe.dump
```

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
EXAM_DB_URL=postgresql://exam:<비번>@yangyag-postgres:5432/exam?options=-csearch_path%3Dipe,public
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

- 재배포: `./deploy/deploy.sh` 한 번이면 된다(같은 태그를 덮어쓰고 컨테이너를 재생성).
- 롤백: 배포 전 이미지를 태그로 보존해 두고 되돌린다.

```bash
# EC2 — 직전 이미지 보존 예시
docker tag exam-front:1.0 exam-front:before-20260912
docker tag exam-back:1.0  exam-back:before-20260912
# 되돌릴 때: docker-compose.yml 의 태그를 before-… 로 바꾸고 docker compose up -d
```

- DB 는 덤프로만 바꾸므로, 스키마 변경이 있으면 배포 전에 `pg_dump` 로 백업한다.

## 주의

- `aws/`(키)·`.env`(DB 암호)는 **커밋하지 않는다**. 이미지에도 굽지 않는다(런타임 env 로만).
- 이 배포는 별도 인증을 걸지 않는다(주소를 아는 사람은 사용할 수 있다). 필요하면 호스트 nginx 에 Basic Auth 를 추가한다.
- 앱 데이터 초기화가 필요하면 EC2 에서 `exam` DB 의 `study_*` 테이블만 비우면 된다(문항 데이터는 유지).
