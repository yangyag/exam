# front/ — 정보처리기사 필기 학습 앱 (Nuxt 4 + Tailwind CSS)

`back/` 의 FastAPI(`http://127.0.0.1:8092`)를 호출해 홈 화면에서 **과목 5개의 학습 사이클 진행 상황**을 보여줍니다.
이번 단계는 골격입니다 — 홈 화면과 라운드 진입 자리 화면까지 있고, 문항·보기·채점 화면은 다음 단계입니다.

## 실행

```bash
cd front
npm install
npm run dev        # http://localhost:8091 (SPA)
```

백엔드가 먼저 떠 있어야 합니다(없으면 홈이 기동 명령을 안내합니다):

```bash
cd back && .venv/Scripts/python -m uvicorn app.main:app --host 127.0.0.1 --port 8092
```

- **포트 8091 · 주소는 `http://localhost:8091`** — 백엔드 기본 CORS 허용 오리진이 이 값입니다(`back/README.md` 6장).
  `127.0.0.1:8091` 은 오리진 문자열이 달라 CORS 에 막힙니다.
- API 오리진은 `NUXT_PUBLIC_API_BASE`(기본 `http://127.0.0.1:8092`)로 바꿉니다.
- `ssr: false`(SPA) 이고 다크모드 대응은 없습니다(흰 배경 고정 — `AGENTS.md` 자료 처리 정책).

## 스크립트

| 명령 | 설명 |
|---|---|
| `npm run dev` | 개발 서버(8091) |
| `npm run build` | 타입 검사(`nuxt typecheck`) + 프로덕션 빌드. **타입 오류가 있으면 실패합니다** |
| `npm run typecheck` | 타입 검사만 (`vue-tsc`) |
| `npm run gen:types` | `app/types/api.gen.ts` 재생성 — 백엔드 `/openapi.json` 에서 뽑습니다(백엔드가 떠 있어야 함). 산출물은 커밋합니다 |
| `npm run shots` | Playwright 스크린샷 + 화면 점검. dev 서버가 없으면 자동 기동·종료하고 `<저장소 루트>/tmp/shots/` 에 저장(gitignore) |

`npm run shots` 가 확인하는 것:

- 실제 DB 데이터로 홈 렌더링 — 과목 5개, 고유 문항 176·194·194·199·181, 헤더 합계 944문항
- 브라우저 콘솔 오류 0, 가로 잘림 0, 클릭 영역(`data-tap` 요소) 44px 이상
- 상태별 동작이 보내는 본문 — 시작하기 `{subjectCode, replaceActive:false}` / 새로 구성 `{subjectCode, replaceActive:true}`(확인 대화상자를 거침), 409(이미 진행 중) 안내 문구
- 상태 4종·확인 대화상자·백엔드 다운·로딩·빈 목록 화면 — 이 컷들은 **브라우저에서 API 응답을 대체**해 찍습니다(실제 요청을 차단하므로 DB 는 그대로).

## 구조

```
front/
  nuxt.config.ts             SPA · 포트 8091 · apiBase · Tailwind v4(@tailwindcss/vite)
  app/
    app.vue
    assets/css/main.css      Tailwind 진입 + 버튼 공통 클래스(최소 44px·포커스 링)
    components/
      SubjectCard.vue        과목 카드 — 상태 배지·진행도·정답 수·상태별 동작
      AppConfirmDialog.vue   확인 대화상자 — 새로 구성 전 한 번 묻는다
    composables/useApi.ts    API 주소 헬퍼 (/api , /figures)
    pages/index.vue          홈 — 5과목 카드 (GET /api/subject-cycles/overview)
    pages/sessions/[id].vue  라운드 진입 자리 — 세션 진행 위치만 확인
    types/api.gen.ts         /openapi.json 생성물 (직접 수정 금지)
    types/api.ts             화면용 타입 별칭
    utils/                   상태→표시 모델 변환 · API 오류 문구
  scripts/shots.mjs          Playwright 캡처·점검
```

## 홈 화면 계약

`GET /api/subject-cycles/overview` 가 주는 4가지 상태를 그대로 씁니다(`back/README.md`).

| 상태 | 카드 표시 | 동작 |
|---|---|---|
| `not_started` | 시작 전 · `0 / 고유문항` · 정답 0 | **시작하기** → `POST /api/subject-cycles` |
| `first_pass` | 전체 풀이 중 · 1라운드 진행도·정답 수 | **이어서 풀기**(열린 라운드 세션으로 이동) · **새로 구성**(확인 후 `replaceActive=true`) |
| `reviewing` | 오답 복습 중 · 라운드 진행도 + 1차 풀이 요약 | 위와 같음 |
| `completed` | 완료 · 1차 풀이 정답 수 | **새로 구성** |

- 진행도 분모는 그 라운드의 문항 수이고, 카드의 "고유 문항 N개" 는 과목의 중복 제거 문항 수입니다(라운드와 다르면 "이번 라운드 N문항"을 덧붙입니다).
- 회차별 연습·모의고사 진입점은 자리만 둡니다(비활성 버튼 — 다음 단계).
