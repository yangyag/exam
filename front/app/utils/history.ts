import type { CycleRound, Exam, ExamResult, SessionMode, SessionSummary, SubjectCycle } from '~/types/api'
import { sessionModeLabels, sessionPlayPath } from '~/utils/sessions'

// 이력 화면(/history)이 쓰는 표시용 모델 — 사이클·세션 응답을 문구·수치로 바꾼다.
// 합격·정오답 판단은 서버가 준 값만 쓰고 여기서 다시 계산하지 않는다.

export const cycleStatusLabels: Record<SubjectCycle['status'], string> = {
  active: '진행 중',
  completed: '완료',
  abandoned: '중단',
}

const cycleStatusTones: Record<SubjectCycle['status'], string> = {
  active: 'bg-blue-50 text-blue-700 ring-blue-200',
  completed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  abandoned: 'bg-slate-100 text-slate-600 ring-slate-200',
}

/** 라운드 한 줄 — 몇 라운드에서 몇 문항 중 몇 문항을 풀어 몇 개를 맞혔는지 */
export type HistoryRound = {
  sessionId: number
  roundNo: number
  modeLabel: string
  itemCount: number
  answered: number
  correct: number
  percent: number
  startedAt: string
  finishedAt: string | null
  stateLabel: string
}

export type HistoryCycle = {
  id: number
  subjectCode: number
  subjectName: string
  status: SubjectCycle['status']
  statusLabel: string
  statusTone: string
  startedAt: string
  endedAt: string | null
  rounds: HistoryRound[]
  /** 진행 중 사이클의 열린 라운드 — 이어서 풀기 대상(없으면 null) */
  openSessionId: number | null
}

/** 라운드 마무리 상태 — 슬롯을 다 채점하면 서버가 finishedAt 을 채운다 */
function roundStateLabel(round: CycleRound): string {
  if (!round.finishedAt) return '진행 중'
  return round.endReason === 'abandoned' ? '중단' : '완료'
}

export function toHistoryCycle(cycle: SubjectCycle): HistoryCycle {
  const rounds: HistoryRound[] = (cycle.rounds ?? []).map(round => ({
    sessionId: round.sessionId,
    roundNo: round.roundNo,
    modeLabel: sessionModeLabels[round.mode] ?? round.mode,
    itemCount: round.itemCount,
    answered: round.answered,
    correct: round.correct,
    percent: round.itemCount > 0 ? Math.round((round.answered / round.itemCount) * 100) : 0,
    startedAt: round.startedAt,
    finishedAt: round.finishedAt ?? null,
    stateLabel: roundStateLabel(round),
  }))
  const openRound = cycle.status === 'active'
    ? rounds.find(round => round.stateLabel === '진행 중') ?? null
    : null
  return {
    id: cycle.id,
    subjectCode: cycle.subjectCode,
    subjectName: cycle.subjectName ?? `${cycle.subjectCode}과목`,
    status: cycle.status,
    statusLabel: cycleStatusLabels[cycle.status],
    statusTone: cycleStatusTones[cycle.status],
    startedAt: cycle.startedAt,
    endedAt: cycle.endedAt ?? null,
    rounds,
    openSessionId: openRound?.sessionId ?? null,
  }
}

/** 이력에 싣는 세션 — 회차(examId)가 있는 모의고사·회차별 연습만 */
export function isHistorySession(session: SessionSummary): boolean {
  return Boolean(session.examId) && (session.mode === 'exam' || session.mode === 'exam_practice')
}

export type HistorySession = {
  id: number
  mode: SessionMode
  modeLabel: string
  examId: string
  title: string
  path: string
  answered: number
  questionCount: number
  startedAt: string
  finishedAt: string | null
  stateLabel: string
  stateTone: string
  linkLabel: string
  /** 모의고사 제출 결과 — 제출하지 않았거나 결과를 못 받았으면 null */
  result: ExamResult | null
}

function sessionStateLabel(session: SessionSummary): { label: string, tone: string } {
  if (!session.finishedAt) return { label: '진행 중', tone: 'bg-blue-50 text-blue-700 ring-blue-200' }
  if (session.endReason === 'abandoned') return { label: '중단', tone: 'bg-amber-50 text-amber-700 ring-amber-200' }
  if (session.mode === 'exam') return { label: '제출 완료', tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200' }
  return { label: '완료', tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200' }
}

export function toHistorySession(
  session: SessionSummary,
  exams: Exam[],
  result: ExamResult | null,
): HistorySession {
  const exam = exams.find(item => item.id === session.examId) ?? null
  const state = sessionStateLabel(session)
  const open = !session.finishedAt
  return {
    id: session.id,
    mode: session.mode,
    modeLabel: sessionModeLabels[session.mode] ?? session.mode,
    examId: session.examId ?? '',
    title: exam?.title ?? session.examId ?? '',
    path: sessionPlayPath(session),
    answered: session.answered,
    questionCount: exam?.questionCount ?? 0,
    startedAt: session.startedAt,
    finishedAt: session.finishedAt ?? null,
    stateLabel: state.label,
    stateTone: state.tone,
    linkLabel: open ? '이어서 풀기' : (session.mode === 'exam' ? '결과 보기' : '풀이 화면'),
    result,
  }
}
