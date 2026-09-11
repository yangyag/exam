-- 정보처리기사 기출문제 데이터셋(ipe) 부트스트랩.
-- superuser 로 1회 실행한다. 여러 번 실행해도 안전하다.
--
--   로컬(docker):
--     docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql
--   EC2 등 psql 이 직접 있는 서버:
--     psql -U postgres -d app -f db/000_bootstrap.sql
--
-- 접속 계정은 기존 앱과 동일한 yangyag 를 쓴다. ipe 스키마의 소유자도 yangyag 다.
-- (처음에 만들었던 exam 역할은 제거했다. 역할을 새로 만들지 않는다.)

\set ON_ERROR_STOP on

-- 1) 역할이 없으면 만든다. 이미 있으면 손대지 않는다.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'yangyag') THEN
        CREATE ROLE yangyag LOGIN PASSWORD 'change-me';
        RAISE NOTICE '역할 yangyag 생성. 실행 후 ALTER ROLE yangyag PASSWORD ''<새비번>''; 로 교체하세요.';
    ELSE
        RAISE NOTICE '역할 yangyag 이미 존재: 그대로 사용합니다.';
    END IF;
END
$$;

-- 2) 스키마 (소유자 yangyag)
CREATE SCHEMA IF NOT EXISTS ipe AUTHORIZATION yangyag;

-- 3) 접속 권한
GRANT CONNECT ON DATABASE app TO yangyag;

-- 4) 부분일치 검색용 확장. ipe 스키마 안에 설치한다.
CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA ipe;

-- 5) search_path 는 역할 전역으로 설정하지 않는다.
--    yangyag 는 기존 english 스키마를 쓰고 있어(english, public) 역할 전역 설정을 바꾸면
--    기존 앱이 영향을 받는다. 이 모듈은 `ipe.question` 처럼 한정해서 쓰거나
--    접속 문자열에 옵션으로 지정한다:
--      postgresql://yangyag:***@localhost:5432/app?options=-csearch_path%3Dipe,public

\echo '--- 결과 확인 ---'
SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname = 'yangyag';
SELECT nspname, nspowner::regrole FROM pg_namespace WHERE nspname = 'ipe';
SELECT extname, extnamespace::regnamespace FROM pg_extension WHERE extname = 'pg_trgm';
