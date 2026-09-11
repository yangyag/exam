import type { SessionMode, SessionSummary } from '~/types/api'

// 세션 모드·회차 세션 표시용 헬퍼 — 홈·회차 화면·연습 화면이 같은 문구와 이동 규칙을 쓴다.
export const sessionModeLabels: Record<SessionMode, string> = {
  subject: '전체 문항 풀이',
  review: '오답 복습',
  exam_practice: '회차별 연습',
  exam: '모의고사',
  random: '랜덤 출제',
}

/** 회차에서 바로 시작할 수 있는 두 방식 */
export type ExamKind = 'exam_practice' | 'exam'

export const examKindLabels: Record<ExamKind, string> = {
  exam_practice: '회차별 연습',
  exam: '모의고사',
}

/**
 * 진행 중인 회차 세션인지 — 회차(examId)가 있고 아직 끝나지 않은 세션.
 * 중단(abandoned)·제출(finished) 세션은 finishedAt 이 채워지므로 걸러진다.
 */
export function isOpenExamSession(session: SessionSummary): boolean {
  return Boolean(session.examId) && session.finishedAt == null
}

/** 이어서 풀 경로 — 모의고사는 전용 화면, 회차별 연습은 기존 연습 화면(설계 3.2절) */
export function sessionPlayPath(session: SessionSummary): string {
  return session.mode === 'exam' ? `/exam/${session.id}` : `/sessions/${session.id}`
}

const dateTimeFormatter = new Intl.DateTimeFormat('ko-KR', {
  dateStyle: 'medium',
  timeStyle: 'short',
  timeZone: 'Asia/Seoul',
})

const timeFormatter = new Intl.DateTimeFormat('ko-KR', {
  timeStyle: 'short',
  timeZone: 'Asia/Seoul',
})

/** 서버 시각(UTC)을 한국 시각 문구로 — 시작·제출 시각 표시용 */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dateTimeFormatter.format(date)
}

/** 시각만 — 답안 저장 시각 표시용 */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : timeFormatter.format(date)
}
