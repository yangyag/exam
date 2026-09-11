<script setup lang="ts">
import type { SessionDetail } from '~/types/api'

// 라운드 진입 자리 화면 — 세션 정보(진행 위치)만 실제 API 로 확인한다.
// 문항·보기·채점 화면은 다음 단계에서 붙는다.
const route = useRoute()
const { base, url: apiUrl } = useApi()

const sessionId = computed(() => String(route.params.id))

const { data: session, error, pending, refresh } = useAsyncData(
  `session-${sessionId.value}`,
  () => $fetch<SessionDetail>(apiUrl(`/api/sessions/${sessionId.value}`), { retry: 0, timeout: 10000 }),
)

const loadError = computed(() => (error.value ? describeApiError(error.value, base) : null))

const modeLabels: Record<string, string> = {
  subject: '1라운드 · 전체 문항 풀이',
  review: '오답 복습 라운드',
  exam_practice: '회차별 연습',
  exam: '모의고사',
  random: '랜덤 출제',
}

const modeLabel = computed(() => (session.value ? modeLabels[session.value.mode] ?? session.value.mode : ''))
const finished = computed(() => Boolean(session.value?.finishedAt))
const percent = computed(() => {
  const item = session.value
  if (!item || item.itemCount === 0) return 0
  return Math.round((item.answeredCount / item.itemCount) * 100)
})

useHead({ title: () => `세션 #${sessionId.value} — 정보처리기사 필기` })
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900">
    <header class="border-b border-slate-200 bg-white">
      <div class="mx-auto flex max-w-3xl items-center gap-3 px-4 py-4 sm:px-6">
        <NuxtLink to="/" class="btn-quiet" data-tap>
          ← 홈으로
        </NuxtLink>
        <p class="truncate text-sm text-slate-500">
          세션 #{{ sessionId }}
        </p>
      </div>
    </header>

    <main class="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
      <section
        v-if="pending && !session"
        class="h-48 animate-pulse rounded-2xl border border-slate-200 bg-slate-50"
        data-testid="session-loading"
        aria-busy="true"
      >
        <span class="sr-only">세션 정보를 불러오는 중입니다</span>
      </section>

      <section
        v-else-if="loadError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        role="alert"
      >
        <h1 class="text-base font-semibold text-red-900">
          {{ loadError.title }}
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-red-800">
          {{ loadError.detail }}
        </p>
        <button type="button" class="btn-secondary mt-4" data-tap @click="refresh()">
          다시 시도
        </button>
      </section>

      <template v-else-if="session">
        <h1 class="text-xl font-bold sm:text-2xl">
          {{ modeLabel }}
        </h1>
        <p class="mt-1 text-sm text-slate-500">
          {{ session.roundNo ? `${session.roundNo}라운드 · ` : '' }}{{ finished ? '종료됨' : '진행 중' }}
        </p>

        <dl class="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">
              진행도
            </dt>
            <dd class="mt-0.5 text-xl font-semibold tabular-nums">
              {{ session.answeredCount }}<span class="ml-1 text-sm font-normal text-slate-500">/ {{ session.itemCount }}</span>
            </dd>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">
              정답 수
            </dt>
            <dd class="mt-0.5 text-xl font-semibold tabular-nums">
              {{ session.correct }}
            </dd>
          </div>
          <div class="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
            <dt class="text-xs text-slate-500">
              다음 문항
            </dt>
            <dd class="mt-0.5 text-xl font-semibold tabular-nums">
              {{ session.nextSeq ?? '—' }}
            </dd>
          </div>
        </dl>

        <div class="mt-4 h-2 w-full overflow-hidden rounded-full bg-slate-100">
          <div class="h-full rounded-full bg-blue-600" :style="{ width: `${percent}%` }" />
        </div>

        <section class="mt-6 rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5">
          <h2 class="text-base font-semibold text-slate-900">
            문제 풀이 화면 준비 중
          </h2>
          <p class="mt-1 text-sm leading-relaxed text-slate-600">
            이 화면은 사이클을 시작하거나 이어서 풀 때 도착하는 자리입니다.
            문항·보기·채점·해설 화면은 다음 단계에서 연결됩니다.
          </p>
          <NuxtLink to="/" class="btn-secondary mt-4" data-tap>
            과목 목록으로
          </NuxtLink>
        </section>
      </template>
    </main>
  </div>
</template>
