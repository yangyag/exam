<script setup lang="ts">
import type { Exam, SessionSummary } from '~/types/api'
import type { ExamKind } from '~/utils/sessions'

// 회차 진입 화면(설계 3장) — 13회차 목록에서 회차별 연습·모의고사를 고르고,
// 그 회차에 진행 중인 세션이 있으면 이어서 풀기를 함께 보여준다.
useHead({ title: '회차별 연습 · 모의고사 — 정보처리기사 필기' })

const { base, url: apiUrl } = useApi()

// 회차 목록(GET /api/exams) + 진행 중 세션(GET /api/sessions 스캔 — 백엔드 필터 추가는 이번 범위가 아니다)
const { data, error, pending, refresh } = useAsyncData('exams-list', async () => {
  const [exams, sessions] = await Promise.all([
    $fetch<Exam[]>(apiUrl('/api/exams'), { retry: 0, timeout: 10000 }),
    $fetch<SessionSummary[]>(apiUrl('/api/sessions?limit=200'), { retry: 0, timeout: 10000 }),
  ])
  return { exams, sessions }
})

const exams = computed<Exam[]>(() => data.value?.exams ?? [])
const openSessions = computed(() => (data.value?.sessions ?? []).filter(isOpenExamSession))
const loadError = computed(() => (error.value ? describeApiError(error.value, base) : null))
const initialLoading = computed(() => pending.value && error.value === undefined && exams.value.length === 0)
const isEmpty = computed(() => !pending.value && error.value === undefined && exams.value.length === 0)

function openFor(examId: string): SessionSummary[] {
  return openSessions.value.filter(session => session.examId === examId)
}

// ── 시작 ─────────────────────────────────────────────────────────────
const starting = ref<{ examId: string, kind: ExamKind } | null>(null)

function busy(label: string, kind: ExamKind): boolean {
  return starting.value?.examId === label && starting.value?.kind === kind
}

function anyBusy(examId: string): boolean {
  return starting.value?.examId === examId
}

const notice = ref<{ tone: 'ok' | 'error', text: string } | null>(null)
let noticeTimer: ReturnType<typeof setTimeout> | null = null

function showNotice(tone: 'ok' | 'error', text: string) {
  notice.value = { tone, text }
  if (noticeTimer) clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = null }, 8000)
}

onBeforeUnmount(() => { if (noticeTimer) clearTimeout(noticeTimer) })

/** 세션을 만들고 그 세션의 풀이 화면으로 보낸다(연습=/sessions/{id}, 모의고사=/exam/{id}) */
async function createSession(exam: Exam, kind: ExamKind, replaceActive: boolean) {
  starting.value = { examId: exam.id, kind }
  notice.value = null
  try {
    const session = await $fetch<SessionSummary>(apiUrl('/api/sessions'), {
      method: 'POST',
      body: { mode: kind, examId: exam.id, replaceActive },
      retry: 0,
      timeout: 15000,
    })
    await navigateTo(sessionPlayPath(session))
  } catch (caught) {
    const info = describeApiError(caught, base)
    if (info.status === 409) {
      // 진행 중 세션이 있다 — 확인 대화상자를 거쳐 replaceActive=true 로 다시 보낸다
      dialog.value = { exam, kind }
    } else {
      showNotice('error', `${exam.title} ${examKindLabels[kind]} 세션을 시작하지 못했습니다 — ${info.detail || info.title}`)
    }
  } finally {
    starting.value = null
  }
}

// ── 진행 중 세션을 중단하고 새로 시작 ────────────────────────────────
const dialog = ref<{ exam: Exam, kind: ExamKind } | null>(null)

const dialogBody = computed(() => {
  const target = dialog.value
  if (!target) return ''
  return `${target.exam.title} 의 ${examKindLabels[target.kind]} 세션을 이미 풀고 있습니다. `
    + '진행 중인 세션을 중단하고 처음부터 새로 시작할까요? 지금까지 고른 답안은 기록에 남지만 그 세션은 이어서 풀 수 없습니다.'
})

async function confirmReplace() {
  const target = dialog.value
  if (!target) return
  dialog.value = null
  await createSession(target.exam, target.kind, true)
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
            회차별 연습 · 모의고사
          </h1>
          <p class="mt-0.5 truncate text-xs text-slate-500 sm:text-sm">
            2022-1 ~ 2026-1 기출 회차<template v-if="exams.length"> · {{ exams.length }}회차</template>
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
        data-testid="exams-loading"
        aria-busy="true"
      >
        <div v-for="n in 6" :key="n" class="h-28 animate-pulse rounded-2xl border border-slate-200 bg-slate-50" />
        <span class="sr-only">회차 목록을 불러오는 중입니다</span>
      </div>

      <!-- 오류(백엔드·DB 다운 포함) -->
      <section
        v-else-if="loadError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        data-testid="exams-error"
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

      <!-- 빈 목록 -->
      <section
        v-else-if="isEmpty"
        class="rounded-2xl border border-slate-200 bg-slate-50 p-5"
        data-testid="exams-empty"
      >
        <h2 class="text-base font-semibold text-slate-900">
          표시할 회차가 없습니다
        </h2>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">
          회차 데이터를 받지 못했습니다. DB 적재 상태를 확인한 뒤 다시 시도해 주세요.
        </p>
        <button type="button" class="btn-secondary mt-4" data-tap @click="refresh()">
          다시 시도
        </button>
      </section>

      <template v-else>
        <p class="rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-relaxed text-slate-600">
          <strong class="text-slate-900">회차별 연습</strong>은 문항마다 바로 채점하고 해설을 봅니다.
          <strong class="text-slate-900">모의고사</strong>는 회차의 100문항을 모두 고른 뒤 최종 제출로 채점합니다
          — 푸는 동안에는 정답·해설이 보이지 않고 <strong class="text-slate-900">제한시간은 없습니다</strong>.
        </p>

        <ul class="mt-4 space-y-3">
          <li
            v-for="exam in exams"
            :key="exam.id"
            class="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm sm:p-5"
            :data-testid="`exam-row-${exam.id}`"
          >
            <div class="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <h2 class="text-base font-semibold text-slate-900" :data-testid="`exam-row-title-${exam.id}`">
                {{ exam.title }}
              </h2>
              <span class="text-xs text-slate-500">
                {{ exam.questionCount }}문항 · 도식 {{ exam.figureCount }}개
              </span>
            </div>

            <!-- 진행 중 세션 — 회차마다 방식별로 하나씩 열려 있을 수 있다 -->
            <div v-if="openFor(exam.id).length" class="mt-3 space-y-2">
              <div
                v-for="session in openFor(exam.id)"
                :key="session.id"
                class="flex flex-wrap items-center gap-3 rounded-xl border border-blue-200 bg-blue-50 px-3 py-2.5"
                :data-testid="`exam-open-${exam.id}-${session.mode}`"
              >
                <p class="min-w-0 flex-1 text-sm text-blue-900">
                  <strong>{{ sessionModeLabels[session.mode] }}</strong> 진행 중 ·
                  {{ session.answered }} / {{ exam.questionCount }}문항
                  <span class="block text-xs text-blue-700">
                    시작 {{ formatDateTime(session.startedAt) }}
                  </span>
                </p>
                <NuxtLink
                  :to="sessionPlayPath(session)"
                  class="btn-primary shrink-0"
                  data-tap
                  :data-testid="`exam-resume-${exam.id}-${session.mode}`"
                >
                  이어서 풀기
                </NuxtLink>
              </div>
            </div>

            <div class="mt-3 flex flex-col gap-2 sm:flex-row">
              <button
                type="button"
                class="btn-secondary sm:w-44"
                data-tap
                :data-testid="`exam-practice-${exam.id}`"
                :disabled="anyBusy(exam.id)"
                @click="createSession(exam, 'exam_practice', false)"
              >
                {{ busy(exam.id, 'exam_practice') ? '여는 중…' : '회차별 연습' }}
              </button>
              <button
                type="button"
                class="btn-primary sm:w-44"
                data-tap
                :data-testid="`exam-mock-${exam.id}`"
                :disabled="anyBusy(exam.id)"
                @click="createSession(exam, 'exam', false)"
              >
                {{ busy(exam.id, 'exam') ? '여는 중…' : '모의고사' }}
              </button>
            </div>
          </li>
        </ul>
      </template>
    </main>

    <!-- 진행 중 세션이 있어 409 가 났을 때 — 중단하고 새로 시작할지 묻는다 -->
    <AppConfirmDialog
      :open="dialog !== null"
      :busy="starting !== null"
      title="진행 중인 세션을 중단할까요?"
      :body="dialogBody"
      confirm-label="중단하고 새로 시작"
      busy-label="여는 중…"
      cancel-label="취소"
      @confirm="confirmReplace"
      @cancel="dialog = null"
    />

    <div
      v-if="notice"
      class="fixed inset-x-0 bottom-4 z-40 px-4"
      role="status"
      aria-live="polite"
    >
      <p
        class="mx-auto max-w-md rounded-xl px-4 py-3 text-sm font-medium text-white shadow-lg"
        :class="notice.tone === 'ok' ? 'bg-slate-900' : 'bg-red-600'"
        data-testid="exams-notice"
      >
        {{ notice.text }}
      </p>
    </div>
  </div>
</template>
