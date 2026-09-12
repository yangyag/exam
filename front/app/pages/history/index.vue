<script setup lang="ts">
import type { Exam, ExamResult, SessionDetail, SessionSummary, Subject, SubjectCycle } from '~/types/api'
import type { HistoryCycle, HistorySession } from '~/utils/history'

// 이전 결과 조회 화면(설계 9.1절 7-a).
// ① 과목별 최근 사이클 — 상태·라운드별 문항/정답 수·시작·종료 시각, 진행 중이면 이어서 풀기
// ② 회차 세션(모의고사·회차별 연습) — 응답/문항·제출 시각·합격 여부
// 전부 조회(GET)만 쓴다 — 이 화면은 진도 테이블에 아무것도 쓰지 않는다.
useHead({ title: '이전 결과 — 정보처리기사 필기' })

const { base, url: apiUrl } = useApi()

// 과목 5행·회차 목록·세션 목록을 함께 읽고, 그다음 과목마다 최근 사이클 1개를 읽는다.
const { data, error, pending, refresh } = useAsyncData('history', async () => {
  const [subjects, exams, sessions] = await Promise.all([
    $fetch<Subject[]>(apiUrl('/api/subjects'), { retry: 0, timeout: 10000 }),
    $fetch<Exam[]>(apiUrl('/api/exams'), { retry: 0, timeout: 10000 }),
    $fetch<SessionSummary[]>(apiUrl('/api/sessions?limit=50'), { retry: 0, timeout: 10000 }),
  ])
  // 사이클 목록은 최근 생성순이라 limit=1 이 그 과목의 마지막 사이클이다(subjectCode·limit 필터)
  const latest = await Promise.all(subjects.map(async (subject) => {
    const rows = await $fetch<SubjectCycle[]>(
      apiUrl(`/api/subject-cycles?subjectCode=${subject.code}&limit=1`),
      { retry: 0, timeout: 10000 },
    )
    return { subject, cycle: rows[0] ?? null }
  }))
  return { subjects, exams, sessions, latest }
})

type SubjectHistoryRow = { code: number, name: string, cycle: HistoryCycle | null }

const subjectRows = computed<SubjectHistoryRow[]>(() => (data.value?.latest ?? [])
  .map(entry => ({
    code: entry.subject.code,
    name: entry.subject.name,
    cycle: entry.cycle ? toHistoryCycle(entry.cycle) : null,
  }))
  .sort((left, right) => left.code - right.code))

// 모의고사 합격 여부는 세션 단건(GET /api/sessions/{id})의 examResult 로만 알 수 있다 —
// 목록을 먼저 그리고 제출이 끝난 모의고사만 이어서 채운다(조회라 원장은 늘지 않는다).
const examResults = ref<Record<number, ExamResult>>({})
const resultsLoading = ref(false)

async function loadExamResults() {
  const targets = (data.value?.sessions ?? [])
    .filter(session => isHistorySession(session)
      && session.mode === 'exam'
      && session.finishedAt
      && session.endReason !== 'abandoned')
    .map(session => session.id)
  if (!targets.length) {
    examResults.value = {}
    return
  }
  resultsLoading.value = true
  try {
    const settled = await Promise.allSettled(targets.map(id =>
      $fetch<SessionDetail>(apiUrl(`/api/sessions/${id}`), { retry: 0, timeout: 10000 })))
    const found: Record<number, ExamResult> = {}
    settled.forEach((outcome, index) => {
      const id = targets[index]
      if (id === undefined || outcome.status !== 'fulfilled') return
      const result = outcome.value.examResult
      if (result) found[id] = result
    })
    examResults.value = found
  } finally {
    resultsLoading.value = false
  }
}

watch(data, loadExamResults, { immediate: true })

const sessions = computed<HistorySession[]>(() => {
  const exams = data.value?.exams ?? []
  return (data.value?.sessions ?? [])
    .filter(isHistorySession)
    .map(session => toHistorySession(session, exams, examResults.value[session.id] ?? null))
})

const loadError = computed(() => (error.value ? describeApiError(error.value, base) : null))
const initialLoading = computed(() => pending.value && error.value === undefined && subjectRows.value.length === 0)
const hasAnyCycle = computed(() => subjectRows.value.some(row => row.cycle !== null))
const isEmpty = computed(() => !pending.value && error.value === undefined
  && subjectRows.value.length > 0 && !hasAnyCycle.value && sessions.value.length === 0)

function finishLine(cycle: HistoryCycle): string {
  return cycle.endedAt ? `종료 ${formatDateTime(cycle.endedAt)}` : '진행 중'
}
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-3xl items-center gap-3 px-4 py-4 sm:px-6">
        <NuxtLink to="/" class="btn-quiet shrink-0" data-tap>
          ← 홈으로
        </NuxtLink>
        <div class="min-w-0">
          <h1 class="truncate text-lg font-bold sm:text-xl">
            이전 결과
          </h1>
          <p class="mt-0.5 truncate text-xs text-slate-500 sm:text-sm">
            과목별 사이클 기록 · 회차 세션 결과
          </p>
        </div>
        <button
          type="button"
          class="btn-quiet ml-auto shrink-0"
          data-tap
          :disabled="pending"
          @click="refresh()"
        >
          {{ pending ? '불러오는 중…' : '새로고침' }}
        </button>
      </div>
    </header>

    <main class="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
      <!-- 로딩 -->
      <div
        v-if="initialLoading"
        class="space-y-3"
        data-testid="history-loading"
        aria-busy="true"
      >
        <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-2xl border border-slate-200 bg-slate-50" />
        <span class="sr-only">이전 결과를 불러오는 중입니다</span>
      </div>

      <!-- 오류(백엔드·DB 다운 포함) -->
      <section
        v-else-if="loadError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        data-testid="history-error"
        role="alert"
      >
        <h2 class="text-base font-semibold text-red-900">
          {{ loadError.title }}
        </h2>
        <p class="mt-1 text-sm leading-relaxed text-red-800">
          {{ loadError.detail }}
        </p>
        <pre
          v-if="loadError.command"
          class="mt-3 overflow-x-auto rounded-lg bg-red-900 p-3 text-xs text-red-50"
        >{{ loadError.command }}</pre>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <button type="button" class="btn-primary" data-tap @click="refresh()">
            다시 시도
          </button>
          <NuxtLink to="/" class="btn-secondary" data-tap>
            홈으로
          </NuxtLink>
        </div>
      </section>

      <!-- 빈 상태 — 사이클도 회차 세션도 없을 때 -->
      <section
        v-else-if="isEmpty"
        class="rounded-2xl border border-slate-200 bg-slate-50 p-5"
        data-testid="history-empty"
      >
        <h2 class="text-base font-semibold text-slate-900">
          아직 기록이 없습니다
        </h2>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">
          과목 사이클을 시작하거나 회차별 연습·모의고사를 풀면 그 기록이 이 자리에 쌓입니다.
          홈에서 과목을 골라 시작해 보세요.
        </p>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <NuxtLink to="/" class="btn-primary" data-tap data-testid="history-empty-home">
            홈에서 시작하기
          </NuxtLink>
          <NuxtLink to="/exams" class="btn-secondary" data-tap data-testid="history-empty-exams">
            회차 선택
          </NuxtLink>
        </div>
      </section>

      <template v-else>
        <!-- ① 과목별 최근 사이클 -->
        <section data-testid="history-cycles">
          <h2 class="text-base font-semibold text-slate-900">
            과목별 최근 사이클
          </h2>
          <p class="mt-1 text-sm leading-relaxed text-slate-600">
            과목마다 마지막으로 만든 사이클 하나입니다 — 라운드별 문항·정답 수와 시작·종료 시각을 보여줍니다.
          </p>

          <ul class="mt-3 space-y-3">
            <li
              v-for="row in subjectRows"
              :key="row.code"
              :data-testid="`history-cycle-${row.code}`"
              class="rounded-2xl border p-4 sm:p-5"
              :class="row.cycle ? 'border-slate-200 bg-white shadow-sm' : 'border-dashed border-slate-300 bg-slate-50'"
            >
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 class="text-base font-semibold text-slate-900">
                  {{ row.code }}과목 {{ row.name }}
                </h3>
                <span
                  v-if="row.cycle"
                  class="rounded-full px-2.5 py-1 text-xs font-semibold ring-1"
                  :class="row.cycle.statusTone"
                  :data-testid="`history-cycle-status-${row.code}`"
                >
                  {{ row.cycle.statusLabel }}
                </span>
              </div>

              <template v-if="row.cycle">
                <p class="mt-1 text-xs text-slate-500">
                  사이클 #{{ row.cycle.id }} · 시작 {{ formatDateTime(row.cycle.startedAt) }} · {{ finishLine(row.cycle) }}
                </p>

                <ul class="mt-3 space-y-2" :data-testid="`history-cycle-rounds-${row.code}`">
                  <li
                    v-for="round in row.cycle.rounds"
                    :key="round.sessionId"
                    class="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2.5"
                    :data-testid="`history-cycle-round-${row.code}-${round.roundNo}`"
                  >
                    <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
                      <span class="font-semibold text-slate-900">{{ round.roundNo }}라운드</span>
                      <span class="text-slate-600">{{ round.modeLabel }}</span>
                      <span class="rounded-full bg-white px-2 py-0.5 text-xs text-slate-600 ring-1 ring-slate-200">
                        {{ round.stateLabel }}
                      </span>
                    </div>
                    <p class="mt-1 text-sm text-slate-700">
                      푼 문항 <strong>{{ round.answered }}</strong> / {{ round.itemCount }} ·
                      정답 <strong class="text-emerald-700">{{ round.correct }}</strong>
                    </p>
                    <div
                      class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-200"
                      role="progressbar"
                      :aria-valuenow="round.percent"
                      aria-valuemin="0"
                      aria-valuemax="100"
                      :aria-label="`${round.roundNo}라운드 진행률`"
                    >
                      <div class="h-full rounded-full bg-blue-600" :style="{ width: `${round.percent}%` }" />
                    </div>
                    <p class="mt-1 text-xs text-slate-500">
                      시작 {{ formatDateTime(round.startedAt) }}
                      <template v-if="round.finishedAt"> · 종료 {{ formatDateTime(round.finishedAt) }}</template>
                    </p>
                  </li>
                </ul>

                <NuxtLink
                  v-if="row.cycle.openSessionId"
                  :to="`/sessions/${row.cycle.openSessionId}`"
                  class="btn-primary mt-3 w-full sm:w-auto"
                  data-tap
                  :data-testid="`history-cycle-resume-${row.code}`"
                >
                  이어서 풀기
                </NuxtLink>
              </template>

              <p v-else class="mt-1 text-sm leading-relaxed text-slate-600" :data-testid="`history-cycle-none-${row.code}`">
                아직 사이클이 없습니다.
                <NuxtLink to="/" class="font-semibold text-blue-700 underline">홈</NuxtLink>에서 시작하면 이 자리에 기록이 남습니다.
              </p>
            </li>
          </ul>
        </section>

        <!-- ② 회차 세션(모의고사·회차별 연습) -->
        <section class="mt-8" data-testid="history-sessions">
          <div class="flex flex-wrap items-baseline justify-between gap-2">
            <h2 class="text-base font-semibold text-slate-900">
              회차 세션 — 모의고사 · 회차별 연습
            </h2>
            <NuxtLink to="/exams" class="btn-secondary shrink-0" data-tap data-testid="history-exams-link">
              회차 선택
            </NuxtLink>
          </div>
          <p class="mt-1 text-sm leading-relaxed text-slate-600">
            최근 세션 {{ sessions.length }}건입니다 — 모의고사는 제출 시각과 합격 여부까지,
            회차별 연습은 풀어 둔 문항 수를 보여줍니다.
            <span v-if="resultsLoading" class="text-slate-500" data-testid="history-results-loading">합격 여부를 확인하는 중…</span>
          </p>

          <ul v-if="sessions.length" class="mt-3 space-y-3">
            <li
              v-for="session in sessions"
              :key="session.id"
              class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
              :data-testid="`history-session-${session.id}`"
            >
              <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                <h3 class="text-base font-semibold text-slate-900">
                  {{ session.title }}
                </h3>
                <span class="text-xs text-slate-500">{{ session.modeLabel }} · 세션 #{{ session.id }}</span>
                <span
                  class="rounded-full px-2.5 py-1 text-xs font-semibold ring-1"
                  :class="session.stateTone"
                  :data-testid="`history-session-state-${session.id}`"
                >
                  {{ session.stateLabel }}
                </span>
              </div>

              <p class="mt-1 text-sm text-slate-700">
                <template v-if="session.questionCount">응답 <strong>{{ session.answered }}</strong> / {{ session.questionCount }}문항</template>
                <template v-else>응답 <strong>{{ session.answered }}</strong>문항</template>
                · 시작 {{ formatDateTime(session.startedAt) }}
                <template v-if="session.finishedAt">
                  · <template v-if="session.mode === 'exam'">제출 {{ formatDateTime(session.finishedAt) }}</template>
                  <template v-else>종료 {{ formatDateTime(session.finishedAt) }}</template>
                </template>
              </p>

              <div class="mt-2 flex flex-wrap items-center gap-2">
                <span
                  v-if="session.result"
                  class="rounded-full px-2.5 py-1 text-xs font-semibold ring-1"
                  :class="session.result.passed
                    ? 'bg-emerald-50 text-emerald-700 ring-emerald-200'
                    : 'bg-red-50 text-red-700 ring-red-200'"
                  :data-testid="`history-session-result-${session.id}`"
                >
                  {{ session.result.passed ? '합격' : '불합격' }} · 평균 {{ session.result.averageScore }}점
                  · 미응답 {{ session.result.unansweredCount }}
                </span>
                <NuxtLink
                  :to="session.path"
                  class="btn-secondary w-full sm:w-auto"
                  data-tap
                  :data-testid="`history-session-link-${session.id}`"
                >
                  {{ session.linkLabel }}
                </NuxtLink>
              </div>
            </li>
          </ul>

          <p
            v-else
            class="mt-3 rounded-2xl border border-slate-200 bg-slate-50 px-4 py-3 text-sm leading-relaxed text-slate-600"
            data-testid="history-sessions-empty"
          >
            아직 회차 세션이 없습니다.
            <NuxtLink to="/exams" class="font-semibold text-blue-700 underline">회차를 골라</NuxtLink> 연습이나 모의고사를 시작해 보세요.
          </p>
        </section>
      </template>
    </main>
  </div>
</template>
