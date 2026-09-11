-- 정보처리기사 기출문제 데이터셋(ipe) 부트스트랩.
-- superuser 로 1회 실행한다. 여러 번 실행해도 안전하다.
--
--   로컬(docker):
--     docker exec -i postgres psql -U postgres -d app -f - < db/000_bootstrap.sql
--   EC2 등 psql 이 직접 있는 서버:
--     psql -U postgres -d app -f db/000_bootstrap.sql
--   (비밀번호는 실행 후 반드시 교체: ALTER ROLE exam PASSWORD '<새비번>';)

\set ON_ERROR_STOP on

-- 1) 애플리케이션 역할 (LOGIN 만 부여. superuser/CREATEDB 없음)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'exam') THEN
        ALTER ROLE exam LOGIN PASSWORD 'exam';
        RAISE NOTICE '역할 exam 이미 존재: LOGIN/PASSWORD 갱신';
    ELSE
        CREATE ROLE exam LOGIN PASSWORD 'exam';
        RAISE NOTICE '역할 exam 생성';
    END IF;
END
$$;

-- 2) 스키마. 소유자를 exam 으로 두면 이후 테이블 생성/적재를 exam 권한으로 할 수 있다.
CREATE SCHEMA IF NOT EXISTS ipe AUTHORIZATION exam;

-- 3) 접속 권한과 기본 search_path (앱에서 select * from question 이 바로 동작)
GRANT CONNECT ON DATABASE app TO exam;
ALTER ROLE exam SET search_path = ipe, public;

-- 4) 부분일치 검색용 확장. ipe 스키마 안에 설치한다.
CREATE EXTENSION IF NOT EXISTS pg_trgm SCHEMA ipe;

\echo '--- 결과 확인 ---'
SELECT rolname, rolcanlogin, rolsuper FROM pg_roles WHERE rolname = 'exam';
SELECT nspname, nspowner::regrole FROM pg_namespace WHERE nspname = 'ipe';
SELECT extname, extnamespace::regnamespace FROM pg_extension WHERE extname = 'pg_trgm';
