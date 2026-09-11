/**
 * 회차 선택·모의고사 화면 스크린샷용 고정 데이터.
 *
 * 회차 13행은 실 DB(GET /api/exams) 응답을 그대로 옮겼고, 모의고사 세션은 100문항 가운데
 * **12문항만 고른 채 제출**하는 상황을 만든다 — 미응답 88문항이 오답과 구분되는지, 미응답이
 * 원장에 남지 않는지(원장 확인은 실 DB 검증)를 화면에서 보려는 것이다.
 *
 * 문항 본문은 실제 데이터셋 문항(scripts/practice-fixtures.mjs)을 번호 순서대로 돌려 쓴다.
 * 과목 표시만 번호에 맞춰 바꾼다(1~20=1과목 …) — 결과 요약의 과목별 점수와 화면이 어긋나지 않게.
 */
import { CODE_QUESTION, FIGURE_QUESTION, STUB_AT, TABLE_QUESTION, TEXT_QUESTION } from './practice-fixtures.mjs'

export { STUB_AT }

/** 실 DB 응답 그대로 — 연도·회차 내림차순 13행 */
export const EXAM_LIST = [
  { id: '2026-1', year: 2026, round: 1, title: '2026년 1회 정보처리기사 필기', questionCount: 100, figureCount: 1 },
  { id: '2025-3', year: 2025, round: 3, title: '2025년 3회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2025-2', year: 2025, round: 2, title: '2025년 2회 정보처리기사 필기', questionCount: 100, figureCount: 1 },
  { id: '2025-1', year: 2025, round: 1, title: '2025년 1회 정보처리기사 필기', questionCount: 100, figureCount: 1 },
  { id: '2024-3', year: 2024, round: 3, title: '2024년 3회 정보처리기사 필기', questionCount: 100, figureCount: 3 },
  { id: '2024-2', year: 2024, round: 2, title: '2024년 2회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2024-1', year: 2024, round: 1, title: '2024년 1회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2023-3', year: 2023, round: 3, title: '2023년 3회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2023-2', year: 2023, round: 2, title: '2023년 2회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2023-1', year: 2023, round: 1, title: '2023년 1회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2022-3', year: 2022, round: 3, title: '2022년 3회 정보처리기사 필기', questionCount: 100, figureCount: 3 },
  { id: '2022-2', year: 2022, round: 2, title: '2022년 2회 정보처리기사 필기', questionCount: 100, figureCount: 2 },
  { id: '2022-1', year: 2022, round: 1, title: '2022년 1회 정보처리기사 필기', questionCount: 100, figureCount: 1 },
]

export const SUBJECT_NAMES = {
  1: '소프트웨어 설계',
  2: '소프트웨어 개발',
  3: '데이터베이스 구축',
  4: '프로그래밍 언어 활용',
  5: '정보시스템 구축 관리',
}

export const EXAM_DETAIL = {
  ...EXAM_LIST[0],
  sourcePdf: '2026년1회_정보처리기사필기기출문제.pdf',
  subjects: [1, 2, 3, 4, 5].map(code => ({
    code,
    name: SUBJECT_NAMES[code],
    fromNo: (code - 1) * 20 + 1,
    toNo: code * 20,
    questionCount: 20,
  })),
}

/** 모의고사 100문항 가운데 답을 고른 번호(나머지 88문항은 미응답) */
export const ANSWERED_SEQ = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]
/** 그중 정답인 번호 — 1~9만 정답이고 10~12는 오답 */
export const CORRECT_SEQ = [1, 2, 3, 4, 5, 6, 7, 8, 9]

const QUESTIONS = [CODE_QUESTION, TEXT_QUESTION, TABLE_QUESTION, FIGURE_QUESTION]

/** seq 번째 문항(문항 종류를 돌려 쓴다) */
export function examQuestionAt(seq) {
  return QUESTIONS[(seq - 1) % QUESTIONS.length]
}

/** seq 번째 문항의 과목 번호(1~20=1과목 … 81~100=5과목) */
export function examSubjectCode(seq) {
  return Math.min(5, Math.max(1, Math.ceil(seq / 20)))
}

/** 처음 상태의 선택 — 1~9번은 정답 보기, 10~12번은 다른 보기 */
export function initialExamChoices() {
  const choices = {}
  for (const seq of ANSWERED_SEQ) {
    const { answer } = examQuestionAt(seq)
    choices[seq] = CORRECT_SEQ.includes(seq) ? answer : (answer % 4) + 1
  }
  return choices
}

/** 채점 응답(GET items/{seq} 의 result·제출 응답과 같은 모양) */
export function examGrade(seq, choiceNo) {
  const entry = examQuestionAt(seq)
  return {
    questionId: entry.item.id,
    choiceNo,
    isCorrect: choiceNo === entry.answer,
    answer: entry.answer,
    explanation: entry.explanation,
    keyPoint: entry.keyPoint,
    choicesAnalysis: entry.choicesAnalysis,
  }
}

/** 문항 상세 — 제출 전에는 정답·해설(result)이 없다 */
export function examItem(seq, choiceNo, { revealed = false } = {}) {
  const entry = examQuestionAt(seq)
  const code = examSubjectCode(seq)
  return {
    ...entry.item,
    subjectCode: code,
    subjectName: SUBJECT_NAMES[code],
    seq,
    choiceNo,
    isCorrect: revealed ? choiceNo === entry.answer : null,
    answeredAt: choiceNo === null ? null : STUB_AT,
    result: revealed ? examGrade(seq, choiceNo) : null,
  }
}

/** 세션 상세 — choices 는 seq→choiceNo 표(미응답은 키가 없다) */
export function examSession(choices, { submitted = false, id = 7201 } = {}) {
  const seqs = Array.from({ length: 100 }, (_, index) => index + 1)
  const answered = seqs.filter(seq => choices[seq] !== undefined)
  const correct = answered.filter(seq => choices[seq] === examQuestionAt(seq).answer)
  const firstUnanswered = seqs.find(seq => choices[seq] === undefined) ?? null
  return {
    id,
    mode: 'exam',
    examId: '2026-1',
    subjectCode: null,
    cycleId: null,
    roundNo: null,
    endReason: submitted ? 'finished' : null,
    startedAt: STUB_AT,
    finishedAt: submitted ? STUB_AT : null,
    answered: answered.length,
    correct: correct.length,
    itemCount: 100,
    answeredCount: answered.length,
    nextSeq: submitted ? null : firstUnanswered,
    items: seqs.map(seq => ({
      seq,
      questionId: examQuestionAt(seq).item.id,
      choiceNo: choices[seq] ?? null,
      isCorrect: submitted ? choices[seq] === examQuestionAt(seq).answer : null,
    })),
    examResult: submitted ? examResult(choices, id) : null,
  }
}

/** 제출 결과 — 과목당 20문항·문항당 5점, 매 과목 40점 이상 + 평균 60점 이상이면 합격 */
export function examResult(choices, id = 7201) {
  const seqs = Array.from({ length: 100 }, (_, index) => index + 1)
  const answered = seqs.filter(seq => choices[seq] !== undefined)
  const correct = answered.filter(seq => choices[seq] === examQuestionAt(seq).answer)
  const bySubject = [1, 2, 3, 4, 5].map((code) => {
    const count = correct.filter(seq => examSubjectCode(seq) === code).length
    return { subjectCode: code, correct: count, score: count * 5, passed: count * 5 >= 40 }
  })
  const average = bySubject.length
    ? Math.round((bySubject.reduce((sum, row) => sum + row.score, 0) / bySubject.length) * 10) / 10
    : 0
  return {
    sessionId: id,
    itemCount: 100,
    answeredCount: answered.length,
    unansweredCount: 100 - answered.length,
    correctCount: correct.length,
    wrongCount: answered.length - correct.length,
    bySubject,
    averageScore: average,
    passed: bySubject.every(row => row.passed) && average >= 60,
    submittedAt: STUB_AT,
  }
}

/** 진행 중 세션 목록(GET /api/sessions) — 7201 모의고사·7202 회차 연습이 열려 있고 7205 는 끝난 세션 */
export function openSessionList() {
  const choices = initialExamChoices()
  const session = examSession(choices)
  return [
    {
      id: session.id,
      mode: 'exam',
      examId: '2026-1',
      subjectCode: null,
      cycleId: null,
      roundNo: null,
      endReason: null,
      startedAt: session.startedAt,
      finishedAt: null,
      answered: session.answeredCount,
      correct: session.correct,
    },
    {
      id: 7202,
      mode: 'exam_practice',
      examId: '2024-1',
      subjectCode: null,
      cycleId: null,
      roundNo: null,
      endReason: null,
      startedAt: '2026-09-11T22:00:00Z',
      finishedAt: null,
      answered: 5,
      correct: 3,
    },
    {
      id: 7205,
      mode: 'exam',
      examId: '2023-3',
      subjectCode: null,
      cycleId: null,
      roundNo: null,
      endReason: 'finished',
      startedAt: '2026-09-10T00:00:00Z',
      finishedAt: '2026-09-10T01:00:00Z',
      answered: 100,
      correct: 70,
    },
  ]
}
