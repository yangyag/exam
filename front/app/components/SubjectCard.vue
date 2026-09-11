<script setup lang="ts">
import type { SubjectOverview } from '~/types/api'

// 과목 카드 — 홈 요약(/api/subject-cycles/overview) 한 행을 카드로 그린다.
const props = defineProps<{
  subject: SubjectOverview
  /** 이 카드에서 API 요청이 진행 중인지 */
  busy?: boolean
  /** 진행 중인 동작 — 버튼 문구를 바꾼다 */
  pendingAction?: 'start' | 'resume' | 'recreate' | null
}>()

const emit = defineEmits<{
  start: []
  resume: []
  recreate: []
}>()

const card = computed(() => toSubjectCardView(props.subject))
const notStarted = computed(() => props.subject.status === 'not_started')
const completed = computed(() => props.subject.status === 'completed')

// 상태별 주 동작 — 시작 전=시작하기, 진행 중=이어서 풀기, 완료=새로 구성(설계 5.1절)
const primaryAction = computed<'start' | 'resume' | 'recreate'>(() => {
  if (notStarted.value) return 'start'
  if (completed.value) return 'recreate'
  return 'resume'
})
const primaryLabel = computed(() => {
  if (primaryAction.value === 'start') return '시작하기'
  if (primaryAction.value === 'recreate') return '새로 구성'
  return '이어서 풀기'
})
const primaryBusy = computed(() => props.busy && props.pendingAction === primaryAction.value)
const recreateBusy = computed(() => props.busy && props.pendingAction === 'recreate')

function onPrimary() {
  if (primaryAction.value === 'start') emit('start')
  else if (primaryAction.value === 'recreate') emit('recreate')
  else emit('resume')
}
</script>

<template>
  <article
    class="flex flex-col rounded-2xl border border-slate-200 bg-white p-5 shadow-sm transition hover:shadow-md"
    data-testid="subject-card"
    :aria-busy="busy ? 'true' : undefined"
  >
    <div class="flex items-start justify-between gap-3">
      <div class="min-w-0">
        <p class="text-xs font-medium text-slate-500">
          {{ card.code }}과목
        </p>
        <h2 class="mt-0.5 truncate text-lg font-semibold text-slate-900">
          {{ card.name }}
        </h2>
        <p class="mt-0.5 text-xs text-slate-500">
          고유 문항 {{ card.uniqueCount }}개<span v-if="card.total !== card.uniqueCount"> · 이번 라운드 {{ card.total }}문항</span>
        </p>
      </div>
      <span
        class="shrink-0 rounded-full px-2.5 py-1 text-xs font-semibold ring-1 ring-slate-200 ring-inset"
        :class="card.statusTone"
      >
        {{ card.statusLabel }}
      </span>
    </div>

    <dl class="mt-4 grid grid-cols-2 gap-3">
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <dt class="text-xs text-slate-500">
          진행도
        </dt>
        <dd class="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">
          {{ card.answered }}<span class="ml-1 text-sm font-normal text-slate-500">/ {{ card.total }}</span>
        </dd>
      </div>
      <div class="rounded-xl bg-slate-50 px-3 py-2">
        <dt class="text-xs text-slate-500">
          정답 수
        </dt>
        <dd class="mt-0.5 text-xl font-semibold tabular-nums text-slate-900">
          {{ card.correct }}
        </dd>
      </div>
    </dl>

    <div class="mt-3">
      <div
        class="h-2 w-full overflow-hidden rounded-full bg-slate-100"
        role="progressbar"
        :aria-valuenow="card.percent"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-label="`${card.name} 진행률`"
      >
        <div class="h-full rounded-full transition-all" :class="card.barTone" :style="{ width: `${card.percent}%` }" />
      </div>
      <p class="mt-2 text-xs leading-relaxed text-slate-600">
        {{ card.note }}
      </p>
      <p v-if="card.detail" class="mt-0.5 text-xs text-slate-400">
        {{ card.detail }}
      </p>
    </div>

    <div class="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
      <button
        type="button"
        class="btn-primary sm:flex-1"
        data-tap
        :disabled="busy"
        @click="onPrimary"
      >
        {{ primaryBusy ? (primaryAction === 'recreate' ? '구성 중…' : '불러오는 중…') : primaryLabel }}
      </button>
      <button
        v-if="!notStarted && !completed"
        type="button"
        class="btn-secondary sm:flex-1"
        data-tap
        :disabled="busy"
        @click="emit('recreate')"
      >
        {{ recreateBusy ? '구성 중…' : '새로 구성' }}
      </button>
    </div>

    <p v-if="completed" class="mt-2 text-xs text-slate-400">
      새로 구성하면 새 사이클이 시작됩니다.
    </p>
  </article>
</template>
