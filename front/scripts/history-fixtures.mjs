/**
 * 이전 결과 조회 화면(/history) 스크린샷용 고정 데이터.
 *
 * 실제 응답 모양(GET /api/subjects · /api/subject-cycles?subjectCode&limit · GET /api/exams ·
 * GET /api/sessions · GET /api/sessions/{id})을 그대로 흉내 낸다. 과목명·문항 수는 실 DB 값이고
 * (과목별 고유 문항 176·194·194·199·181), 사이클·세션 id 와 시각만 화면 점검용으로 만든 값이다.
 *
 * 세 상태를 모두 지나가게 구성했다 — 완료(1과목) · 진행 중(2과목, 열린 복습 라운드) · 중단(3과목),
 * 회차 세션은 열린 연습 · 끝난 연습 · 중단된 모의고사 · 제출한 모의고사(합격/불합격)를 담았다.
 */

export const HISTORY_SUBJECTS = [
  { code: 1, name: '소프트웨어 설계', fromNo: 1, toNo: 20, questionCount: 260 },
  { code: 2, name: '소프트웨어 개발', fromNo: 21, toNo: 40, questionCount: 260 },
  { code: 3, name: '데이터베이스 구축', fromNo: 41, toNo: 60, questionCount: 260 },
  { code: 4, name: '프로그래밍 언어 활용', fromNo: 61, toNo: 80, questionCount: 260 },
  { code: 5, name: '정보시스템 구축 관리', fromNo: 81, toNo: 100, questionCount: 260 },
]

/** GET /api/subject-cycles?subjectCode=N&limit=1 — 과목별 마지막 사이클(없는 과목은 빈 배열) */
export const CYCLES_BY_SUBJECT = {
  1: [{
    id: 120,
    subjectCode: 1,
    subjectName: '소프트웨어 설계',
    status: 'completed',
    startedAt: '2026-08-20T01:00:00Z',
    endedAt: '2026-09-02T11:30:00Z',
    rounds: [
      {
        sessionId: 7310,
        roundNo: 1,
        mode: 'subject',
        itemCount: 176,
        answered: 176,
        correct: 150,
        startedAt: '2026-08-20T01:00:00Z',
        finishedAt: '2026-08-28T12:00:00Z',
        endReason: 'finished',
      },
      {
        sessionId: 7311,
        roundNo: 2,
        mode: 'review',
        itemCount: 26,
        answered: 26,
        correct: 24,
        startedAt: '2026-08-29T00:30:00Z',
        finishedAt: '2026-09-02T11:30:00Z',
        endReason: 'finished',
      },
    ],
  }],
  2: [{
    id: 330,
    subjectCode: 2,
    subjectName: '소프트웨어 개발',
    status: 'active',
    startedAt: '2026-09-12T05:39:32Z',
    endedAt: null,
    rounds: [
      {
        sessionId: 7320,
        roundNo: 1,
        mode: 'subject',
        itemCount: 194,
        answered: 194,
        correct: 182,
        startedAt: '2026-09-12T05:39:32Z',
        finishedAt: '2026-09-12T06:10:00Z',
        endReason: 'finished',
      },
      {
        sessionId: 7321,
        roundNo: 2,
        mode: 'review',
        itemCount: 12,
        answered: 5,
        correct: 4,
        startedAt: '2026-09-12T06:11:00Z',
        finishedAt: null,
        endReason: null,
      },
    ],
  }],
  3: [{
    id: 250,
    subjectCode: 3,
    subjectName: '데이터베이스 구축',
    status: 'abandoned',
    startedAt: '2026-08-05T03:00:00Z',
    endedAt: '2026-08-11T09:00:00Z',
    rounds: [
      {
        sessionId: 7330,
        roundNo: 1,
        mode: 'subject',
        itemCount: 194,
        answered: 60,
        correct: 51,
        startedAt: '2026-08-05T03:00:00Z',
        finishedAt: '2026-08-11T09:00:00Z',
        endReason: 'abandoned',
      },
    ],
  }],
  4: [],
  5: [],
}

/**
 * GET /api/sessions?limit=50 — 최근순.
 * 마지막 한 행(7320)은 사이클 라운드라 이전 결과 목록에서 걸러져야 한다(examId 가 없음).
 */
export const HISTORY_SESSIONS = [
  {
    id: 7305,
    mode: 'exam_practice',
    examId: '2024-2',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: null,
    startedAt: '2026-09-12T04:00:00Z',
    finishedAt: null,
    answered: 37,
    correct: 30,
  },
  {
    id: 7304,
    mode: 'exam_practice',
    examId: '2023-2',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: 'finished',
    startedAt: '2026-09-10T01:00:00Z',
    finishedAt: '2026-09-10T02:30:00Z',
    answered: 100,
    correct: 71,
  },
  {
    id: 7303,
    mode: 'exam',
    examId: '2025-3',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: 'abandoned',
    startedAt: '2026-09-08T09:00:00Z',
    finishedAt: '2026-09-08T10:00:00Z',
    answered: 12,
    correct: 9,
  },
  {
    id: 7302,
    mode: 'exam',
    examId: '2025-2',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: 'finished',
    startedAt: '2026-09-06T05:00:00Z',
    finishedAt: '2026-09-06T07:20:00Z',
    answered: 100,
    correct: 55,
  },
  {
    id: 7301,
    mode: 'exam',
    examId: '2026-1',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: 'finished',
    startedAt: '2026-09-05T01:00:00Z',
    finishedAt: '2026-09-05T03:40:00Z',
    answered: 92,
    correct: 87,
  },
  {
    id: 7320,
    mode: 'subject',
    examId: null,
    subjectCode: 2,
    cycleId: 330,
    roundNo: 1,
    endReason: 'finished',
    startedAt: '2026-09-12T05:39:32Z',
    finishedAt: '2026-09-12T06:10:00Z',
    answered: 194,
    correct: 182,
  },
]

/** 제출이 끝난 모의고사의 채점 요약 — GET /api/sessions/{id} 의 examResult 로만 온다 */
export const EXAM_RESULTS = {
  7301: {
    sessionId: 7301,
    itemCount: 100,
    answeredCount: 92,
    unansweredCount: 8,
    correctCount: 87,
    wrongCount: 5,
    bySubject: [
      { subjectCode: 1, correct: 18, score: 90, passed: true },
      { subjectCode: 2, correct: 16, score: 80, passed: true },
      { subjectCode: 3, correct: 19, score: 95, passed: true },
      { subjectCode: 4, correct: 17, score: 85, passed: true },
      { subjectCode: 5, correct: 17, score: 85, passed: true },
    ],
    averageScore: 87,
    passed: true,
    submittedAt: '2026-09-05T03:40:00Z',
  },
  7302: {
    sessionId: 7302,
    itemCount: 100,
    answeredCount: 100,
    unansweredCount: 0,
    correctCount: 55,
    wrongCount: 45,
    bySubject: [
      { subjectCode: 1, correct: 12, score: 60, passed: true },
      { subjectCode: 2, correct: 7, score: 35, passed: false },
      { subjectCode: 3, correct: 13, score: 65, passed: true },
      { subjectCode: 4, correct: 11, score: 55, passed: true },
      { subjectCode: 5, correct: 12, score: 60, passed: true },
    ],
    averageScore: 55,
    passed: false,
    submittedAt: '2026-09-06T07:20:00Z',
  },
}

/** GET /api/sessions/{id} — 이 화면은 examResult 만 본다(조회라 원장은 늘지 않는다) */
export function historySessionDetail(session) {
  return {
    ...session,
    itemCount: EXAM_RESULTS[session.id]?.itemCount ?? session.answered,
    answeredCount: EXAM_RESULTS[session.id]?.answeredCount ?? session.answered,
    nextSeq: null,
    items: [],
    examResult: EXAM_RESULTS[session.id] ?? null,
  }
}
