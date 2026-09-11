<script setup lang="ts">
import type { ApiErrorInfo } from '~/utils/apiError'
import type {
  CycleResult,
  GradeResult,
  RoundResult,
  SessionDetail,
  SessionItemDetail,
  SlotGradeResult,
} from '~/types/api'

// 라운드 풀이 화면(설계 3.1·4.1·4.2절).
// 흐름: 문항·보기 → 보기 선택 → 제출 → 같은 화면에 정오답·해설 → 다음 문항.
// 진행 위치는 서버의 nextSeq 가 정한다 — 새로고침·재접속해도 같은 자리로 돌아온다.
const route = useRoute()
const { base, url: apiUrl, figureUrl } = useApi()

const sessionId = computed(() => String(route.params.id))

// ── 세션 ─────────────────────────────────────────────────────────────
const session = ref<SessionDetail | null>(null)
const sessionLoading = ref(true)
const sessionError = ref<ApiErrorInfo | null>(null)

// ── 문항 ─────────────────────────────────────────────────────────────
const seq = ref<number | null>(null)
const item = ref<SessionItemDetail | null>(null)
const itemLoading = ref(false)
const itemError = ref<ApiErrorInfo | null>(null)

// ── 제출·채점 ────────────────────────────────────────────────────────
const selected = ref<number | null>(null)
const submitting = ref(false)
const submitError = ref<ApiErrorInfo | null>(null)
/** 409 충돌 안내 — 서버 메시지를 그대로 보여준다 */
const conflictNote = ref<string | null>(null)
/** 중단·종료 세션 안내 — 이때는 제출을 막고 홈으로 돌아가게 한다 */
const closedNote = ref<string | null>(null)
const result = ref<GradeResult | null>(null)
const nextSeq = ref<number | null>(null)
const roundResult = ref<RoundResult | null>(null)
const cycle = ref<CycleResult | null>(null)
/** 보기별 해설 접기·펼치기 — 기본은 접힘(기본안) */
const showAnalysis = ref(false)

// ── 진행 표시 ────────────────────────────────────────────────────────
const progress = ref({ itemCount: 0, answeredCount: 0 })
/** 이어풀기로 복원했음을 알리는 배너 */
const resumed = ref(false)
let itemShownAt = 0
let itemToken = 0

const PRACTICE_MODES = ['subject', 'review', 'exam_practice']
const isPracticeMode = computed(() => Boolean(session.value && PRACTICE_MODES.includes(session.value.mode)))
const itemCount = computed(() => progress.value.itemCount || session.value?.itemCount || 0)
const answeredCount = computed(() => progress.value.answeredCount)
const remaining = computed(() => Math.max(0, itemCount.value - answeredCount.value))
const percent = computed(() => (itemCount.value > 0 ? Math.round((answeredCount.value / itemCount.value) * 100) : 0))
const currentNo = computed(() => seq.value)
const roundLabel = computed(() => {
  const current = session.value
  if (!current) return ''
  const name = sessionModeLabels[current.mode] ?? current.mode
  return current.roundNo ? `${current.roundNo}라운드 · ${name}` : name
})
const subjectLine = computed(() => {
  if (item.value?.subjectName) return item.value.subjectName
  if (item.value) return `${item.value.subjectCode}과목`
  if (session.value?.subjectCode) return `${session.value.subjectCode}과목`
  return '라운드'
})

// 이미 끝난 세션(중단·종료)은 문항을 보여주지 않고 안내와 홈 이동만 준다
const closedReason = computed<'abandoned' | 'finished' | null>(() => {
  const current = session.value
  if (!current) return null
  if (current.endReason === 'abandoned') return 'abandoned'
  if (current.finishedAt && current.nextSeq === null && !roundResult.value) return 'finished'
  return null
})

const choices = computed(() => item.value?.choices ?? [])
const passageKind = computed(() => (item.value?.passage && item.value?.passageKind ? item.value.passageKind : null))
const figureSrc = computed(() => figureUrl(item.value?.figure?.imageUrl))
const showFigure = computed(() => Boolean(item.value?.figure?.needed && figureSrc.value))
const locked = computed(() => Boolean(result.value) || Boolean(closedNote.value) || submitting.value)

// 다음 문항 번호 — 서버가 준 nextSeq 를 우선하고, 없으면 슬롯 번호를 이어 센다
const nextTarget = computed<number | null>(() => {
  if (nextSeq.value !== null) return nextSeq.value
  const current = seq.value
  if (current === null) return null
  if (itemCount.value > 0 && current < itemCount.value) return current + 1
  return null
})

function resetState() {
  session.value = null
  item.value = null
  seq.value = null
  selected.value = null
  result.value = null
  nextSeq.value = null
  roundResult.value = null
  cycle.value = null
  sessionError.value = null
  itemError.value = null
  submitError.value = null
  conflictNote.value = null
  closedNote.value = null
  showAnalysis.value = false
  resumed.value = false
  progress.value = { itemCount: 0, answeredCount: 0 }
}

async function loadSession() {
  sessionLoading.value = true
  sessionError.value = null
  try {
    const data = await $fetch<SessionDetail>(apiUrl(`/api/sessions/${sessionId.value}`), { retry: 0, timeout: 10000 })
    session.value = data
    progress.value = { itemCount: data.itemCount ?? 0, answeredCount: data.answeredCount ?? 0 }
    if (!PRACTICE_MODES.includes(data.mode)) return
    if (closedReason.value) return
    if (!data.itemCount) return
    resumed.value = (data.answeredCount ?? 0) > 0
    seq.value = data.nextSeq ?? null
  } catch (caught) {
    sessionError.value = describeApiError(caught, base)
  } finally {
    sessionLoading.value = false
  }
}

async function loadItem(target: number): Promise<SessionItemDetail | null> {
  const token = ++itemToken
  itemLoading.value = true
  itemError.value = null
  try {
    const data = await $fetch<SessionItemDetail>(
      apiUrl(`/api/sessions/${sessionId.value}/items/${target}`),
      { retry: 0, timeout: 10000 },
    )
    if (token !== itemToken) return null
    item.value = data
    selected.value = data.choiceNo ?? null
    // 이미 채점된 슬롯이면 저장된 결과를 그대로 보여준다(다시 제출하지 않는다)
    result.value = data.result ?? null
    itemShownAt = Date.now()
    return data
  } catch (caught) {
    if (token !== itemToken) return null
    itemError.value = describeApiError(caught, base)
    return null
  } finally {
    if (token === itemToken) itemLoading.value = false
  }
}

function applyGrade(data: SlotGradeResult) {
  result.value = data
  nextSeq.value = data.session?.nextSeq ?? null
  roundResult.value = data.roundResult ?? null
  cycle.value = data.cycle ?? null
  showAnalysis.value = false
  resumed.value = false
  progress.value = {
    itemCount: data.session?.itemCount ?? progress.value.itemCount,
    answeredCount: data.session?.answeredCount ?? progress.value.answeredCount,
  }
}

async function submitAnswer() {
  const current = seq.value
  if (current === null || selected.value === null || locked.value) return
  submitting.value = true
  submitError.value = null
  conflictNote.value = null
  const elapsedMs = itemShownAt ? Math.min(2147483647, Math.max(0, Date.now() - itemShownAt)) : 0
  try {
    const data = await $fetch<SlotGradeResult>(
      apiUrl(`/api/sessions/${sessionId.value}/items/${current}/answer`),
      { method: 'PUT', body: { choiceNo: selected.value, elapsedMs }, retry: 0, timeout: 15000 },
    )
    applyGrade(data)
  } catch (caught) {
    const info = describeApiError(caught, base)
    if (info.status === 409) {
      // 같은 보기 재전송은 200 이라 여기 오지 않는다. 다른 보기 재제출·중단·종료 세션이 409 다.
      conflictNote.value = info.detail
      const stored = await loadItem(current)
      if (stored?.result) {
        // 이미 채점된 문항 — 저장된 결과를 보여주고 다음 진행은 막지 않는다
        result.value = stored.result
      } else if (/중단|종료|제출/.test(info.detail)) {
        closedNote.value = info.detail
      }
    } else {
      submitError.value = info
    }
  } finally {
    submitting.value = false
  }
}

function goNext() {
  const target = nextTarget.value
  if (target === null) return
  result.value = null
  nextSeq.value = null
  roundResult.value = null
  cycle.value = null
  selected.value = null
  submitError.value = null
  conflictNote.value = null
  showAnalysis.value = false
  seq.value = target
}

function goNextRound() {
  const target = cycle.value?.nextSessionId
  if (!target) return
  navigateTo(`/sessions/${target}`)
}

function retryLoad() {
  if (sessionError.value || session.value === null) loadSession()
  else if (seq.value !== null) loadItem(seq.value)
}

function choiceTone(no: number): string {
  if (result.value) {
    if (no === result.value.answer) return 'border-emerald-300 bg-emerald-50'
    if (no === result.value.choiceNo) return 'border-red-300 bg-red-50'
    return 'border-slate-200 bg-white'
  }
  if (no === selected.value) return 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
  return 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'
}

function analysisFor(no: number) {
  return result.value?.choicesAnalysis?.find(entry => entry.no === no) ?? null
}

function choiceText(no: number): string {
  return choices.value.find(choice => choice.no === no)?.text ?? ''
}

// 409 로 중단·종료가 확인되면 그 뒤로는 서버에 쓰지 않는다
watch(closedNote, (note) => {
  if (note) { result.value = null }
})

watch(seq, (value) => {
  if (value === null) { item.value = null; return }
  loadItem(value)
})

// 다음 라운드로 이동하면 같은 컴포넌트가 재사용된다 — 상태를 비우고 다시 불러온다
watch(sessionId, () => {
  itemToken++
  resetState()
  loadSession()
})

onMounted(loadSession)

useHead({ title: () => `${subjectLine.value} ${roundLabel.value} — 정보처리기사 필기` })
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900">
    <header class="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div class="mx-auto max-w-3xl px-4 py-3 sm:px-6">
        <div class="flex items-center gap-3">
          <NuxtLink to="/" class="btn-quiet shrink-0" data-tap>
            ← 홈으로
          </NuxtLink>
          <!-- 좁은 화면: 진행(n / m)을 잘리지 않게 앞세우고 과목·라운드는 아래 줄로 내린다 -->
          <p
            v-if="itemCount && !closedReason"
            class="ml-auto shrink-0 text-sm font-semibold text-slate-700 sm:hidden"
            data-testid="practice-progress-mobile"
          >
            문항 {{ currentNo ?? '—' }} / {{ itemCount }}
          </p>
          <p class="hidden min-w-0 flex-1 truncate text-sm text-slate-600 sm:block" data-testid="practice-progress">
            {{ subjectLine }} · {{ roundLabel }}<span v-if="itemCount && !closedReason"> · 문항 {{ currentNo ?? '—' }} / {{ itemCount }}</span>
          </p>
          <span v-if="itemCount && !closedReason" class="shrink-0 text-xs text-slate-500">
            남은 {{ remaining }}문항
          </span>
        </div>
        <p class="mt-0.5 truncate text-xs text-slate-500 sm:hidden" data-testid="practice-context-mobile">
          {{ subjectLine }} · {{ roundLabel }}
        </p>
        <div
          v-if="itemCount && !closedReason"
          class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          :aria-valuenow="percent"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-label="라운드 진행률"
        >
          <div class="h-full rounded-full bg-blue-600 transition-all" :style="{ width: `${percent}%` }" />
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
      <!-- 로딩 -->
      <section
        v-if="sessionLoading"
        class="h-64 animate-pulse rounded-2xl border border-slate-200 bg-slate-50"
        data-testid="practice-loading"
        aria-busy="true"
      >
        <span class="sr-only">문항을 불러오는 중입니다</span>
      </section>

      <!-- 네트워크·서버 오류(백엔드 다운 포함) — 제출 오류는 문항 아래에서 따로 안내한다 -->
      <section
        v-else-if="sessionError || itemError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        data-testid="practice-error"
        role="alert"
      >
        <h1 class="text-base font-semibold text-red-900">
          {{ (sessionError || itemError)?.title }}
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-red-800">
          {{ (sessionError || itemError)?.detail }}
        </p>
        <pre
          v-if="(sessionError || itemError)?.command"
          class="mt-3 overflow-x-auto rounded-lg bg-red-900 p-3 text-xs text-red-50"
        >{{ (sessionError || itemError)?.command }}</pre>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <button type="button" class="btn-primary" data-tap @click="retryLoad">
            다시 시도
          </button>
          <NuxtLink to="/" class="btn-secondary" data-tap>
            홈으로
          </NuxtLink>
        </div>
      </section>

      <!-- 연습 모드가 아닌 세션(모의고사·랜덤) -->
      <section
        v-else-if="session && !isPracticeMode"
        class="rounded-2xl border border-slate-200 bg-slate-50 p-5"
        data-testid="practice-unsupported"
      >
        <h1 class="text-base font-semibold text-slate-900">
          연습 화면에서 열 수 없는 세션입니다
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">
          이 화면은 과목별 연습(전체 풀이·오답 복습)과 회차별 연습을 위한 것입니다.
          지금 세션은 <strong>{{ sessionModeLabels[session.mode] ?? session.mode }}</strong> 모드입니다.
          <template v-if="session.mode === 'exam'">
            모의고사는 모의고사 화면에서 이어서 풀 수 있습니다.
          </template>
        </p>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <NuxtLink v-if="session.mode === 'exam'" :to="`/exam/${sessionId}`" class="btn-primary" data-tap data-testid="practice-to-exam">
            모의고사 화면으로
          </NuxtLink>
          <NuxtLink to="/" class="btn-secondary" data-tap>
            홈으로
          </NuxtLink>
        </div>
      </section>

      <!-- 중단·종료된 세션 -->
      <section
        v-else-if="session && (closedReason || closedNote)"
        class="rounded-2xl border border-amber-200 bg-amber-50 p-5"
        data-testid="practice-closed"
        role="alert"
      >
        <h1 class="text-base font-semibold text-amber-900">
          {{ closedReason === 'abandoned' ? '중단된 라운드입니다' : '이미 끝난 라운드입니다' }}
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-amber-800">
          {{ closedNote || (closedReason === 'abandoned'
            ? '새 사이클을 구성하면서 중단된 세션입니다. 계속 풀려면 홈에서 새로 시작해 주세요.'
            : `이 라운드는 모든 문항을 마쳤습니다 (${answeredCount} / ${itemCount}). 홈에서 다음 라운드를 이어가세요.`) }}
        </p>
        <NuxtLink to="/" class="btn-primary mt-4" data-tap>
          홈으로
        </NuxtLink>
      </section>

      <!-- 문항이 없는 라운드 -->
      <section
        v-else-if="session && itemCount === 0"
        class="rounded-2xl border border-slate-200 bg-slate-50 p-5"
        data-testid="practice-empty"
      >
        <h1 class="text-base font-semibold text-slate-900">
          이 라운드에 문항이 없습니다
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-slate-600">
          문항 목록을 받지 못했습니다. 홈에서 사이클을 다시 구성해 주세요.
        </p>
        <NuxtLink to="/" class="btn-secondary mt-4" data-tap>
          홈으로
        </NuxtLink>
      </section>

      <template v-else-if="session">
        <!-- 이어풀기 복원 안내 -->
        <p
          v-if="resumed"
          class="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-xs leading-relaxed text-blue-800"
          data-testid="practice-resume"
        >
          이어서 풀기 — {{ answeredCount }} / {{ itemCount }}문항을 마쳤습니다. {{ currentNo }}번째 문항부터 이어집니다.
        </p>

        <!-- 문항 로딩 -->
        <section
          v-if="itemLoading && !item"
          class="h-64 animate-pulse rounded-2xl border border-slate-200 bg-slate-50"
          data-testid="practice-item-loading"
          aria-busy="true"
        >
          <span class="sr-only">문항을 불러오는 중입니다</span>
        </section>

        <template v-else-if="item">
          <article
            class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"
            data-testid="practice-item"
          >
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span class="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">
                {{ currentNo }} / {{ itemCount }}
              </span>
              <span v-if="item.difficulty" class="rounded-full bg-slate-100 px-2.5 py-1">
                난이도 {{ item.difficulty }}
              </span>
              <span v-for="tag in item.tags" :key="tag" class="rounded-full bg-slate-100 px-2.5 py-1">
                {{ tag }}
              </span>
            </div>

            <h1 class="mt-4 text-lg leading-relaxed font-semibold text-slate-900 sm:text-xl" data-testid="practice-stem">
              {{ item.stem }}
            </h1>

            <QuestionPassage
              v-if="passageKind && item.passage"
              :text="item.passage"
              :kind="passageKind"
            />

            <figure v-if="showFigure" class="mt-4">
              <img
                :src="figureSrc!"
                :alt="item.figure?.alt || '문항 도식'"
                class="mx-auto max-w-full rounded-xl border border-slate-200 bg-white"
                data-testid="practice-figure"
              >
              <figcaption v-if="item.figure?.alt" class="mt-2 text-xs leading-relaxed text-slate-500">
                {{ item.figure.alt }}
              </figcaption>
            </figure>
            <p v-else-if="item.figure?.needed" class="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-500">
              이 문항에는 도식이 있지만 이미지 경로가 없습니다.
            </p>

            <!-- 보기 선택 → 제출 -->
            <form class="mt-5" @submit.prevent="submitAnswer">
              <fieldset :disabled="locked">
                <legend class="sr-only">보기 선택</legend>
                <div class="flex flex-col gap-2">
                  <label
                    v-for="choice in choices"
                    :key="choice.no"
                    class="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm transition"
                    :class="choiceTone(choice.no)"
                    data-tap
                    :data-testid="`practice-choice-${choice.no}`"
                  >
                    <input
                      v-model="selected"
                      type="radio"
                      name="practice-choice"
                      :value="choice.no"
                      :disabled="locked"
                      class="mt-0.5 h-5 w-5 shrink-0 accent-blue-600"
                    >
                    <span class="flex min-w-0 flex-1 flex-col gap-1">
                      <span class="font-medium whitespace-pre-line text-slate-900">
                        {{ choice.no }}. {{ choice.text }}
                      </span>
                    </span>
                    <span
                      v-if="result && choice.no === result.answer"
                      class="shrink-0 rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white"
                    >
                      정답
                    </span>
                    <span
                      v-else-if="result && choice.no === result.choiceNo"
                      class="shrink-0 rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white"
                    >
                      내 답
                    </span>
                  </label>
                </div>
              </fieldset>

              <button
                v-if="!result && !closedNote"
                type="submit"
                class="btn-primary mt-4 w-full sm:w-auto"
                data-testid="practice-submit"
                data-tap
                :disabled="submitting || selected === null"
              >
                {{ submitting ? '제출 중…' : '제출하기' }}
              </button>
            </form>
          </article>

          <!-- 제출 충돌(409) — 서버 메시지를 그대로 보여주고 다음 진행은 막지 않는다 -->
          <p
            v-if="conflictNote && result"
            class="mt-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-800"
            data-testid="practice-conflict"
            role="status"
          >
            {{ conflictNote }}
          </p>

          <!-- 채점 결과·해설 -->
          <section
            v-if="result"
            class="mt-5 rounded-2xl border p-5 sm:p-6"
            :class="result.isCorrect ? 'border-emerald-200 bg-emerald-50' : 'border-red-200 bg-red-50'"
            data-testid="practice-result"
            aria-live="polite"
          >
            <div class="flex flex-wrap items-center gap-2">
              <span
                class="rounded-full px-3 py-1 text-sm font-bold text-white"
                :class="result.isCorrect ? 'bg-emerald-600' : 'bg-red-600'"
                data-testid="practice-verdict"
              >
                {{ result.isCorrect ? '정답입니다' : '오답입니다' }}
              </span>
              <span class="text-sm text-slate-700">
                정답 {{ result.answer }}번<template v-if="!result.isCorrect && result.choiceNo"> · 내 답 {{ result.choiceNo }}번</template>
              </span>
            </div>

            <h2 class="mt-4 text-sm font-semibold text-slate-900">
              해설
            </h2>
            <p class="mt-1 text-sm leading-relaxed whitespace-pre-line text-slate-800" data-testid="practice-explanation">
              {{ result.explanation }}
            </p>

            <p v-if="result.keyPoint" class="mt-3 rounded-xl bg-white/70 px-3 py-2 text-sm leading-relaxed text-slate-700">
              <span class="font-semibold text-slate-900">핵심 개념</span> — {{ result.keyPoint }}
            </p>

            <!-- 보기별 해설: 기본은 접힘(기본안), 펼치면 4개 보기 전부 -->
            <div class="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-white">
              <button
                type="button"
                class="flex min-h-11 w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-800"
                :aria-expanded="showAnalysis"
                aria-controls="practice-analysis"
                data-testid="practice-analysis-toggle"
                data-tap
                @click="showAnalysis = !showAnalysis"
              >
                <span>보기별 해설 {{ result.choicesAnalysis?.length ?? 0 }}개 {{ showAnalysis ? '접기' : '보기' }}</span>
                <span aria-hidden="true">{{ showAnalysis ? '▲' : '▼' }}</span>
              </button>
              <ul
                v-if="showAnalysis"
                id="practice-analysis"
                class="divide-y divide-slate-100 border-t border-slate-200"
                data-testid="practice-analysis"
              >
                <li v-for="entry in result.choicesAnalysis" :key="entry.no" class="flex gap-3 px-4 py-3">
                  <span
                    class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                    :class="entry.correct ? 'bg-emerald-600' : 'bg-slate-400'"
                  >
                    {{ entry.no }}
                  </span>
                  <div class="min-w-0">
                    <p class="text-sm font-medium whitespace-pre-line text-slate-900">
                      {{ choiceText(entry.no) }}
                      <span v-if="entry.no === result?.choiceNo" class="ml-1 text-xs font-semibold text-blue-700">(내가 고른 보기)</span>
                    </p>
                    <p class="mt-0.5 text-sm leading-relaxed text-slate-600">
                      {{ entry.why }}
                    </p>
                  </div>
                </li>
              </ul>
            </div>

            <!-- 라운드 종료 요약 + 다음 라운드 전환 -->
            <div v-if="roundResult" class="mt-5 rounded-xl border border-slate-200 bg-white p-4" data-testid="practice-round-end">
              <h2 class="text-sm font-semibold text-slate-900">
                {{ roundResult.roundNo ? `${roundResult.roundNo}라운드 결과` : '라운드 결과' }}
              </h2>
              <dl class="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-sm text-slate-700">
                <div class="flex gap-1">
                  <dt>전체</dt>
                  <dd class="font-semibold" data-testid="round-item-count">{{ roundResult.itemCount }}문항</dd>
                </div>
                <div class="flex gap-1">
                  <dt>정답</dt>
                  <dd class="font-semibold text-emerald-700" data-testid="round-correct">{{ roundResult.correct }}</dd>
                </div>
                <div class="flex gap-1">
                  <dt>오답</dt>
                  <dd class="font-semibold text-red-700" data-testid="round-wrong">{{ roundResult.wrong }}</dd>
                </div>
              </dl>

              <template v-if="cycle?.nextSessionId">
                <p class="mt-2 text-sm leading-relaxed text-slate-600">
                  <template v-if="roundResult.wrong > 0">
                    틀린 {{ roundResult.wrong }}문항은 다음 라운드에서 다시 풉니다.
                  </template>
                  <template v-else>
                    다음 라운드를 이어갑니다.
                  </template>
                </p>
                <button type="button" class="btn-primary mt-3 w-full sm:w-auto" data-testid="practice-next-round" data-tap @click="goNextRound">
                  오답 복습 {{ cycle.nextRoundNo }}라운드 이어가기 ({{ cycle.nextItemCount }}문항)
                </button>
              </template>
              <template v-else-if="cycle && cycle.status === 'completed'">
                <p class="mt-2 text-sm leading-relaxed text-slate-600" data-testid="practice-cycle-completed">
                  <template v-if="roundResult.wrong > 0">
                    복습 라운드까지 마쳐
                  </template>
                  <template v-else>
                    틀린 문항이 없어
                  </template>
                  사이클을 완료했습니다. 수고하셨습니다.
                </p>
                <NuxtLink to="/" class="btn-primary mt-3 w-full sm:w-auto" data-tap>
                  홈으로
                </NuxtLink>
              </template>
              <template v-else>
                <p class="mt-2 text-sm leading-relaxed text-slate-600">
                  이 라운드를 모두 마쳤습니다.
                </p>
                <NuxtLink to="/" class="btn-secondary mt-3 w-full sm:w-auto" data-tap>
                  홈으로
                </NuxtLink>
              </template>
            </div>

            <!-- 다음 문항 -->
            <div v-else-if="nextTarget !== null" class="mt-5">
              <button
                type="button"
                class="btn-primary w-full sm:w-auto"
                data-testid="practice-next"
                data-tap
                :disabled="itemLoading"
                @click="goNext"
              >
                {{ itemLoading ? '불러오는 중…' : '다음 문항 →' }}
              </button>
            </div>
            <div v-else class="mt-5">
              <NuxtLink to="/" class="btn-secondary w-full sm:w-auto" data-tap>
                홈으로
              </NuxtLink>
            </div>
          </section>

          <!-- 제출 오류(네트워크 등) — 보기 선택은 그대로 두고 다시 보낼 수 있게 한다 -->
          <section
            v-else-if="submitError"
            class="mt-5 rounded-2xl border border-red-200 bg-red-50 p-5"
            data-testid="practice-submit-error"
            role="alert"
          >
            <h2 class="text-base font-semibold text-red-900">
              {{ submitError.title }}
            </h2>
            <p class="mt-1 text-sm leading-relaxed text-red-800">
              {{ submitError.detail }}
            </p>
            <p class="mt-2 text-xs leading-relaxed text-red-700">
              같은 보기로 다시 보내면 기록이 늘지 않고 그대로 채점됩니다.
            </p>
          </section>

          <!-- 제출 충돌 안내(아직 채점 결과를 못 받은 경우) -->
          <p
            v-if="conflictNote && !result"
            class="mt-5 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-relaxed text-amber-800"
            data-testid="practice-conflict"
            role="status"
          >
            {{ conflictNote }}
          </p>
        </template>
      </template>
    </main>
  </div>
</template>
