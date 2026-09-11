<script setup lang="ts">
import type { SubjectCycle, SubjectOverview } from '~/types/api'

useHead({ title: '정보처리기사 필기 — 과목별 학습' })

const { base, url: apiUrl } = useApi()

// 홈 요약 — 과목 5행 고정(GET /api/subject-cycles/overview).
// 로딩·오류 화면을 직접 그리려고 await 하지 않는다(SPA 라 첫 렌더가 곧 로딩 상태).
const { data, error, pending, refresh } = useAsyncData(
  'subject-overview',
  // 재시도·타임아웃은 $fetch 옵션으로 넘긴다(백엔드가 꺼져 있으면 곧바로 오류 화면)
  () => $fetch<SubjectOverview[]>(apiUrl('/api/subject-cycles/overview'), { retry: 0, timeout: 10000 }),
)

const subjects = computed<SubjectOverview[]>(() => data.value ?? [])
const totalUnique = computed(() => subjects.value.reduce((sum, s) => sum + s.uniqueQuestionCount, 0))
const loadError = computed(() => (error.value ? describeApiError(error.value, base) : null))
const initialLoading = computed(() => pending.value && error.value === undefined && subjects.value.length === 0)
const isEmpty = computed(() => !pending.value && error.value === undefined && subjects.value.length === 0)

// 진행 중인 동작 표시 — `${과목코드}:${동작}`
const actionKey = ref<string | null>(null)

function pendingActionFor(subject: SubjectOverview): 'start' | 'resume' | 'recreate' | null {
  if (!actionKey.value?.startsWith(`${subject.subjectCode}:`)) return null
  return actionKey.value.split(':')[1] as 'start' | 'resume' | 'recreate'
}

const notice = ref<{ tone: 'ok' | 'error', text: string } | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null

function showNotice(tone: 'ok' | 'error', text: string) {
  notice.value = { tone, text }
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = null }, 8000)
}

function actionErrorText(error: unknown, fallback: string): string {
  const info = describeApiError(error, base)
  return `${fallback} — ${info.detail || info.title}`
}

// 사이클을 만들면 바로 열린 라운드로 보낸다(문제 풀이 화면은 다음 단계에서 붙는다)
async function openCycleRound(cycle: SubjectCycle) {
  const rounds = cycle.rounds ?? []
  const round = rounds.find(r => !r.finishedAt) ?? rounds.at(-1)
  if (round) await navigateTo(`/sessions/${round.sessionId}`)
}

async function startCycle(subject: SubjectOverview) {
  actionKey.value = `${subject.subjectCode}:start`
  notice.value = null
  try {
    const cycle = await $fetch<SubjectCycle>(apiUrl('/api/subject-cycles'), {
      method: 'POST',
      body: { subjectCode: subject.subjectCode, replaceActive: false },
    })
    await refresh()
    showNotice('ok', `${subject.subjectName} 1라운드 ${cycle.rounds?.[0]?.itemCount ?? 0}문항을 구성했습니다.`)
    await openCycleRound(cycle)
  } catch (caught) {
    showNotice('error', actionErrorText(caught, `${subject.subjectName} 사이클을 시작하지 못했습니다`))
  } finally {
    actionKey.value = null
  }
}

async function resumeCycle(subject: SubjectOverview) {
  const round = subject.cycle?.currentRound
  if (!round?.sessionId) {
    showNotice('error', `${subject.subjectName} 의 진행 중인 라운드를 찾지 못했습니다. 새로고침해 주세요.`)
    return
  }
  actionKey.value = `${subject.subjectCode}:resume`
  try {
    await navigateTo(`/sessions/${round.sessionId}`)
  } finally {
    actionKey.value = null
  }
}

// 새로 구성 — 되돌릴 수 없으므로 확인 대화상자를 거친다(API 는 replaceActive=true)
const dialogSubject = ref<SubjectOverview | null>(null)

function askRecreate(subject: SubjectOverview) {
  dialogSubject.value = subject
}

// 완료한 사이클은 중단할 라운드가 없으므로 확인 문구를 나눈다
const dialogBody = computed(() => {
  const subject = dialogSubject.value
  if (!subject) return ''
  const label = `${subject.subjectCode}과목 ${subject.subjectName}`
  if (subject.status === 'completed') {
    return `${label} 의 새 사이클을 시작합니다. 완료한 사이클의 기록과 통계는 그대로 남습니다.`
  }
  return `${label} 의 진행 중인 라운드를 중단하고 새 사이클을 만듭니다. 지금까지 푼 기록은 남지만 그 라운드는 이어서 풀 수 없습니다.`
})

async function confirmRecreate() {
  const subject = dialogSubject.value
  if (!subject) return
  dialogSubject.value = null
  actionKey.value = `${subject.subjectCode}:recreate`
  notice.value = null
  try {
    const cycle = await $fetch<SubjectCycle>(apiUrl('/api/subject-cycles'), {
      method: 'POST',
      body: { subjectCode: subject.subjectCode, replaceActive: true },
    })
    await refresh()
    showNotice('ok', `${subject.subjectName} 사이클을 새로 구성했습니다.`)
    await openCycleRound(cycle)
  } catch (caught) {
    showNotice('error', actionErrorText(caught, `${subject.subjectName} 사이클을 새로 구성하지 못했습니다`))
  } finally {
    actionKey.value = null
  }
}

onBeforeUnmount(() => { if (noticeTimer) clearTimeout(noticeTimer) })
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-4 sm:px-6">
        <div class="min-w-0">
          <h1 class="truncate text-lg font-bold sm:text-xl">
            정보처리기사 필기
          </h1>
          <p class="mt-0.5 text-xs text-slate-500 sm:text-sm">
            과목별 학습 사이클<span v-if="subjects.length"> · 과목별 고유 문항 합계 {{ totalUnique }}개 (과목마다 중복 제거)</span>
          </p>
        </div>
        <button
          type="button"
          class="btn-quiet shrink-0"
          data-tap
          :disabled="pending"
          @click="refresh()"
        >
          {{ pending ? '불러오는 중…' : '새로고침' }}
        </button>
      </div>
    </header>

    <main class="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-8">
      <!-- 로딩 -->
      <div
        v-if="initialLoading"
        class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3"
        data-testid="home-loading"
        aria-busy="true"
        aria-live="polite"
      >
        <div v-for="n in 5" :key="n" class="h-64 animate-pulse rounded-2xl border border-slate-200 bg-slate-50" />
        <span class="sr-only">과목 정보를 불러오는 중입니다</span>
      </div>

      <!-- 오류(백엔드·DB 다운 포함) -->
      <section
        v-else-if="loadError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        data-testid="home-error"
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
        <button type="button" class="btn-secondary mt-4" data-tap @click="refresh()">
          다시 시도
        </button>
      </section>

      <!-- 빈 목록 -->
      <section
        v-else-if="isEmpty"
        class="rounded-2xl border border-slate-200 bg-slate-50 p-5"
        data-testid="home-empty"
      >
        <h2 class="text-base font-semibold text-slate-900">
          표시할 과목이 없습니다
        </h2>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">
          과목 데이터를 받지 못했습니다. DB 적재 상태를 확인한 뒤 다시 시도해 주세요.
        </p>
        <button type="button" class="btn-secondary mt-4" data-tap @click="refresh()">
          다시 시도
        </button>
      </section>

      <template v-else>
        <!-- 과목 5개 — 모바일 1열, 데스크톱 2~3열 -->
        <div class="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          <SubjectCard
            v-for="subject in subjects"
            :key="subject.subjectCode"
            :subject="subject"
            :busy="actionKey !== null && actionKey.startsWith(`${subject.subjectCode}:`)"
            :pending-action="pendingActionFor(subject)"
            @start="startCycle(subject)"
            @resume="resumeCycle(subject)"
            @recreate="askRecreate(subject)"
          />
        </div>

        <!-- 회차별 연습·모의고사 자리(다음 단계에서 연결) -->
        <section class="mt-8 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5">
          <h2 class="text-base font-semibold text-slate-900">
            회차별 연습 · 모의고사
          </h2>
          <p class="mt-1 text-sm leading-relaxed text-slate-600">
            2022-1 ~ 2026-1 기출 회차를 골라 연습하거나 실전처럼 모의고사를 볼 자리입니다.
            <span class="text-slate-500">화면은 다음 단계에서 연결됩니다.</span>
          </p>
          <div class="mt-3 flex flex-col gap-2 sm:flex-row">
            <button type="button" class="btn-placeholder" disabled>
              회차별 연습 (준비 중)
            </button>
            <button type="button" class="btn-placeholder" disabled>
              모의고사 (준비 중)
            </button>
          </div>
        </section>
      </template>
    </main>

    <AppConfirmDialog
      :open="dialogSubject !== null"
      :busy="actionKey !== null"
      title="사이클을 새로 구성할까요?"
      :body="dialogBody"
      confirm-label="새로 구성"
      cancel-label="취소"
      @confirm="confirmRecreate"
      @cancel="dialogSubject = null"
    />

    <!-- 동작 결과 안내 -->
    <div
      v-if="notice"
      class="fixed inset-x-0 bottom-4 z-40 px-4"
      role="status"
      aria-live="polite"
    >
      <p
        class="mx-auto max-w-md rounded-xl px-4 py-3 text-sm font-medium shadow-lg"
        :class="notice.tone === 'ok' ? 'bg-slate-900 text-white' : 'bg-red-600 text-white'"
        data-testid="notice"
      >
        {{ notice.text }}
      </p>
    </div>
  </div>
</template>
