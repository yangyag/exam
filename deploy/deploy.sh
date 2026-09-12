#!/usr/bin/env bash
# exam 앱 배포 — 로컬에서 이미지를 만들어 EC2 로 올리고 재기동한다.
#
#   사용법(저장소 루트에서):
#     ./deploy/deploy.sh            # 빌드 → tar → 전송 → EC2 docker load → compose up
#     ./deploy/deploy.sh --build    # 이미지 빌드까지만
#
# 전제:
#   - 로컬에 도커가 있고 aws/test-keypair.pem(EC2 키)이 있다
#   - EC2 /home/ubuntu/exam 에 docker-compose.yml 과 .env 가 이미 있다(deploy/README.md 참고)
set -euo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="43.202.113.123"
USER_NAME="ubuntu"
KEY="$ROOT/aws/test-keypair.pem"
REMOTE_DIR="/home/ubuntu/exam"
TAR="/tmp/exam-images.tar.gz"

BUILD_ONLY=0
[[ "${1:-}" == "--build" ]] && BUILD_ONLY=1

echo "== 1) 이미지 빌드 (linux/amd64) =="
cd "$ROOT"
docker build --platform linux/amd64 -f deploy/Dockerfile.back -t exam-back:1.0 .
docker build --platform linux/amd64 -f deploy/Dockerfile.front -t exam-front:1.0 .
docker image ls --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | grep -E '^exam-(back|front):' || true

if [[ "$BUILD_ONLY" == "1" ]]; then
    echo "빌드만 수행했습니다."
    exit 0
fi

echo "== 2) tar 로 저장 =="
docker save exam-back:1.0 exam-front:1.0 | gzip > "$TAR"
ls -lh "$TAR"

echo "== 3) EC2 전송 =="
chmod 600 "$KEY"
scp -i "$KEY" -o StrictHostKeyChecking=accept-new "$TAR" "$USER_NAME@$HOST:$REMOTE_DIR/"

echo "== 4) EC2 에서 로드·재기동 =="
ssh -i "$KEY" -o StrictHostKeyChecking=accept-new "$USER_NAME@$HOST" bash -s <<EOF
set -euo pipefail
cd "$REMOTE_DIR"
gzip -dc exam-images.tar.gz | docker load
rm -f exam-images.tar.gz
docker compose up -d --force-recreate
sleep 5
docker compose ps
EOF

echo "== 5) 확인 =="
printf '  앱:    https://yangyag5.duckdns.org/\n'
printf '  헬스:  https://yangyag5.duckdns.org/api/health\n'
