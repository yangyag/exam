import type { HomeCycle, SubjectOverview, SubjectStatus } from '~/types/api'

// 홈 카드가 그대로 쓰는 표시용 모델 — API 응답을 화면 문구·수치로 바꾼다.
export type SubjectCardView = {
  code: number
  name: string
  status: SubjectStatus
  statusLabel: string
  statusTone: string
  barTone: string
  /** 과목의 중복 제거 문항 수(라운드 크기와 다르다) */
  uniqueCount: number
  /** 진행도 분자 — 이번 라운드에서 푼 문항 수 */
  answered: number
  /** 진행도 분모 — 이번 라운드 문항 수(복습 라운드면 오답 수) */
  total: number
  /** 맞힌 문항 수 */
  correct: number
  /** 진행률 0~100 */
  percent: number
  /** 라운드 번호(진행 중 사이클이 아니면 null) */
  roundNo: number | null
  /** 상태 설명 문구 */
  note: string
  /** 보조 문구(1차 풀이 요약 등, 없으면 null) */
  detail: string | null
}

export const statusLabels: Record<SubjectStatus, string> = {
  not_started: '시작 전',
  first_pass: '전체 풀이 중',
  reviewing: '오답 복습 중',
  completed: '완료',
}

// 상태 배지 — 흰 배경에서 대비가 확보되는 색만 쓴다(다크모드 대응 없음)
const statusTones: Record<SubjectStatus, string> = {
  not_started: 'bg-slate-100 text-slate-600 ring-slate-200',
  first_pass: 'bg-blue-50 text-blue-700 ring-blue-200',
  reviewing: 'bg-amber-50 text-amber-700 ring-amber-200',
  completed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
}

const barTones: Record<SubjectStatus, string> = {
  not_started: 'bg-slate-300',
  first_pass: 'bg-blue-600',
  reviewing: 'bg-amber-500',
  completed: 'bg-emerald-500',
}

const dayFormatter = new Intl.DateTimeFormat('ko-KR', { dateStyle: 'medium', timeZone: 'Asia/Seoul' })

// 응답 시각은 UTC 라 한국 날짜로 바꿔 보여준다(복습 기준 날짜와 같은 기준)
export function formatDay(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : dayFormatter.format(date)
}

export function toSubjectCardView(subject: SubjectOverview): SubjectCardView {
  const status = subject.status
  const cycle: HomeCycle | null | undefined = subject.cycle
  const currentRound = cycle?.currentRound ?? null
  const firstRound = cycle?.firstRound ?? null

  const base = {
    code: subject.subjectCode,
    name: subject.subjectName,
    status,
    statusLabel: statusLabels[status],
    statusTone: statusTones[status],
    barTone: barTones[status],
    uniqueCount: subject.uniqueQuestionCount,
  }

  if (status === 'not_started') {
    return {
      ...base,
      answered: 0,
      total: subject.uniqueQuestionCount,
      correct: 0,
      percent: 0,
      roundNo: null,
      note: `시작하면 고유 문항 ${subject.uniqueQuestionCount}개를 중복 없이 섞어 구성합니다.`,
      detail: null,
    }
  }

  if (status === 'completed') {
    const answered = firstRound?.answered ?? subject.uniqueQuestionCount
    const total = firstRound?.itemCount ?? subject.uniqueQuestionCount
    const correct = firstRound?.correct ?? 0
    return {
      ...base,
      answered,
      total,
      correct,
      percent: 100,
      roundNo: null,
      note: '오답 복습까지 마쳐 사이클을 완료했습니다.',
      // 패널의 정답 수가 '1차(전체) 풀이' 값임을 화면에서 바로 알 수 있게 함께 적는다
      detail: [
        `1차(전체) 풀이 정답 ${correct}/${total}`,
        cycle?.endedAt ? `완료일 ${formatDay(cycle.endedAt)}` : null,
      ].filter(Boolean).join(' · '),
    }
  }

  // 진행 중(first_pass·reviewing) — 열린 라운드가 기준.
  // 경합으로 열린 라운드를 못 받은 경우(back/README.md 경고)에는 1차 풀이 값으로 대체한다.
  const source = currentRound ?? firstRound
  const answered = source?.answered ?? 0
  const total = source?.itemCount ?? subject.uniqueQuestionCount
  const correct = source?.correct ?? 0
  const percent = total > 0 ? Math.round((answered / total) * 100) : 0
  const roundNo = currentRound?.roundNo ?? firstRound?.roundNo ?? null

  if (status === 'first_pass') {
    return {
      ...base,
      answered,
      total,
      correct,
      percent,
      roundNo,
      note: '1라운드 · 전체 문항을 순서대로 푸는 중입니다.',
      detail: null,
    }
  }

  return {
    ...base,
    answered,
    total,
    correct,
    percent,
    roundNo,
    note: `${roundNo ?? 2}라운드 · 오답만 모아 복습 중입니다.`,
    detail: firstRound ? `1차 풀이 정답 ${firstRound.correct}/${firstRound.itemCount}` : null,
  }
}
