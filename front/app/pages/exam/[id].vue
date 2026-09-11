<script setup lang="ts">
import type { ApiErrorInfo } from '~/utils/apiError'
import type {
  ExamDetail,
  ExamResult,
  GradeResult,
  SessionDetail,
  SessionItemDetail,
  SessionItemSummary,
  SlotSaveResult,
} from '~/types/api'

// 모의고사 풀이·결과 화면(설계 3.2절).
// 푸는 동안에는 정답·해설을 노출하지 않고(서버도 보내지 않는다) 고른 보기를 즉시 저장한다.
// 제출 확인 대화상자에서 미응답 문항 수를 강조하고, 제출이 끝나면 같은 화면이 결과 화면이 된다.
// 조회(GET)만으로는 원장이 늘지 않으므로 결과 화면의 해설 재조회도 기록을 남기지 않는다.
const route = useRoute()
const { base, url: apiUrl, figureUrl } = useApi()

const sessionId = computed(() => String(route.params.id))

// ── 세션·회차 ────────────────────────────────────────────────────────
const session = ref<SessionDetail | null>(null)
const exam = ref<ExamDetail | null>(null)
const loading = ref(true)
const loadError = ref<ApiErrorInfo | null>(null)
/** 중단(409)·비-exam(400) 세션 — 풀이를 막고 안내만 한다 */
const closedNote = ref<string | null>(null)

// ── 슬롯(진행·번호 그리드의 원천) ────────────────────────────────────
const slots = ref<SessionItemSummary[]>([])

// ── 현재 문항 ────────────────────────────────────────────────────────
const seq = ref<number | null>(null)
const item = ref<SessionItemDetail | null>(null)
const itemLoading = ref(false)
const itemError = ref<ApiErrorInfo | null>(null)
let itemToken = 0

// ── 선택 저장 ────────────────────────────────────────────────────────
const saving = ref(false)
const saveError = ref<string | null>(null)
const savedAt = ref<string | null>(null)
/** 저장에 실패한 선택(undefined = 재시도할 것 없음, null = 해제 재시도) */
const retryChoice = ref<number | null | undefined>(undefined)
/** 이어풀기로 열었는지(안내 배너) */
const resumed = ref(false)
let saveToken = 0

// ── 최종 제출 ────────────────────────────────────────────────────────
const confirmOpen = ref(false)
const submitting = ref(false)
const submitError = ref<ApiErrorInfo | null>(null)
const submitted = ref<ExamResult | null>(null)
const refreshError = ref<string | null>(null)

// ── 결과 화면: 문항별 해설 재조회 ────────────────────────────────────
const explainSeq = ref<number | null>(null)
const explainItem = ref<SessionItemDetail | null>(null)
const explainLoading = ref(false)
const explainError = ref<ApiErrorInfo | null>(null)
const showAnalysis = ref(false)
const explainPanel = ref<HTMLElement | null>(null)
let explainToken = 0

// 번호 그리드는 모바일에서 세로로 길어 기본 접힘(데스크톱은 펼침) — 첫 렌더 뒤 한 번 정한다
const gridOpen = ref(true)

// ── 파생 상태 ────────────────────────────────────────────────────────
const title = computed(() => exam.value?.title ?? session.value?.examId ?? '모의고사')
const isResultView = computed(() => submitted.value !== null)
const result = computed<ExamResult | null>(() => submitted.value)
const itemCount = computed(() => session.value?.itemCount ?? slots.value.length)
const answeredCount = computed(() => slots.value.filter(slot => slot.choiceNo !== null).length)
const unansweredCount = computed(() => Math.max(0, itemCount.value - answeredCount.value))
const percent = computed(() => (itemCount.value > 0 ? Math.round((answeredCount.value / itemCount.value) * 100) : 0))

function slotFor(target: number | null): SessionItemSummary | null {
  if (target === null) return null
  return slots.value.find(slot => slot.seq === target) ?? null
}

const currentChoice = computed<number | null>(() => slotFor(seq.value)?.choiceNo ?? null)
const choices = computed(() => item.value?.choices ?? [])
const passageKind = computed(() => (item.value?.passage && item.value.passageKind ? item.value.passageKind : null))
const figureSrc = computed(() => figureUrl(item.value?.figure?.imageUrl))
const showFigure = computed(() => Boolean(item.value?.figure?.needed && figureSrc.value))
const gridCells = computed(() => slots.value.map(slot => ({
  seq: slot.seq,
  choiceNo: slot.choiceNo ?? null,
  isCorrect: slot.isCorrect ?? null,
})))
const canPrev = computed(() => (seq.value ?? 1) > 1)
const canNext = computed(() => seq.value !== null && seq.value < itemCount.value)
/** 실수로 바뀐 세션(연습 화면으로 열 수 있는 모드)인지 — 안내 화면의 이동 링크 */
const canOpenPractice = computed(() => Boolean(session.value && ['subject', 'review', 'exam_practice'].includes(session.value.mode)))

// ── 결과 화면 파생 ───────────────────────────────────────────────────
const subjectNames = computed<Record<number, string>>(() => {
  const map: Record<number, string> = {}
  for (const subject of exam.value?.subjects ?? []) map[subject.code] = subject.name
  return map
})

function subjectLabel(code: number): string {
  return subjectNames.value[code] ?? `${code}과목`
}

const submitTimeLabel = computed(() => formatDateTime(result.value?.submittedAt ?? session.value?.finishedAt ?? null))

const explainResult = computed<GradeResult | null>(() => explainItem.value?.result ?? null)
const explainPassageKind = computed(() => (
  explainItem.value?.passage && explainItem.value.passageKind ? explainItem.value.passageKind : null
))
const explainFigureSrc = computed(() => figureUrl(explainItem.value?.figure?.imageUrl))
const explainVerdict = computed(() => {
  const current = explainItem.value
  if (!current) return ''
  if (current.choiceNo === null) return '미응답'
  return current.isCorrect ? '정답입니다' : '오답입니다'
})
const explainTone = computed(() => {
  const current = explainItem.value
  if (!current || current.choiceNo === null) return 'bg-slate-500'
  return current.isCorrect ? 'bg-emerald-600' : 'bg-red-600'
})

function explainChoiceText(no: number): string {
  return explainItem.value?.choices?.find(choice => choice.no === no)?.text ?? ''
}

function explainChoiceTone(no: number): string {
  const current = explainResult.value
  if (!current) return 'border-slate-200 bg-white'
  if (no === current.answer) return 'border-emerald-300 bg-emerald-50'
  if (no === current.choiceNo) return 'border-red-300 bg-red-50'
  return 'border-slate-200 bg-white'
}

// ── 불러오기 ─────────────────────────────────────────────────────────
function resetState() {
  session.value = null
  exam.value = null
  slots.value = []
  seq.value = null
  item.value = null
  closedNote.value = null
  loadError.value = null
  itemError.value = null
  saveError.value = null
  savedAt.value = null
  retryChoice.value = undefined
  resumed.value = false
  submitError.value = null
  submitted.value = null
  refreshError.value = null
  explainSeq.value = null
  explainItem.value = null
  explainError.value = null
  showAnalysis.value = false
  loading.value = true
}

async function loadExam(examId: string | null | undefined) {
  if (!examId) return
  try {
    exam.value = await $fetch<ExamDetail>(apiUrl(`/api/exams/${examId}`), { retry: 0, timeout: 10000 })
  } catch {
    // 회차 제목은 없어도 풀이에 지장이 없다 — 회차 id 로 대신 보여준다
    exam.value = null
  }
}

async function loadSession() {
  loading.value = true
  loadError.value = null
  try {
    const data = await $fetch<SessionDetail>(apiUrl(`/api/sessions/${sessionId.value}`), { retry: 0, timeout: 10000 })
    session.value = data
    slots.value = data.items ?? []
    void loadExam(data.examId)
    if (data.mode !== 'exam') {
      closedNote.value = `이 화면은 모의고사(mode=exam) 전용입니다. 지금 세션은 ${sessionModeLabels[data.mode]} 모드입니다.`
      return
    }
    if (data.endReason === 'abandoned') {
      closedNote.value = '중단된 모의고사입니다. 이미 제출한 적이 없어 결과가 없습니다 — 회차 목록에서 새로 시작해 주세요.'
      return
    }
    if (data.examResult) {
      // 이미 제출한 모의고사 — 곧바로 결과 화면으로 연다
      submitted.value = data.examResult
      return
    }
    // 이어서 풀기 — 서버가 정한 다음 문항(선택하지 않은 가장 작은 번호)
    resumed.value = (data.answeredCount ?? 0) > 0
    await openSeq(data.nextSeq ?? 1)
  } catch (caught) {
    loadError.value = describeApiError(caught, base)
  } finally {
    loading.value = false
  }
}

async function loadItem(target: number) {
  const token = ++itemToken
  itemLoading.value = true
  itemError.value = null
  saveError.value = null
  retryChoice.value = undefined
  showAnalysis.value = false
  try {
    const data = await $fetch<SessionItemDetail>(
      apiUrl(`/api/sessions/${sessionId.value}/items/${target}`),
      { retry: 0, timeout: 10000 },
    )
    if (token !== itemToken) return
    item.value = data
    savedAt.value = data.answeredAt ?? null
  } catch (caught) {
    if (token !== itemToken) return
    item.value = null
    itemError.value = describeApiError(caught, base)
  } finally {
    if (token === itemToken) itemLoading.value = false
  }
}

async function openSeq(target: number) {
  if (target === seq.value && item.value) return
  seq.value = target
  await loadItem(target)
}

function retryItem() {
  if (seq.value !== null) void loadItem(seq.value)
}

/** 제출 뒤 세션을 다시 읽어 슬롯의 채점 결과(isCorrect)를 결과 그리드에 채운다 */
async function refreshSession() {
  refreshError.value = null
  try {
    const refreshed = await $fetch<SessionDetail>(apiUrl(`/api/sessions/${sessionId.value}`), { retry: 0, timeout: 10000 })
    session.value = refreshed
    slots.value = refreshed.items ?? slots.value
  } catch {
    refreshError.value = '문항별 채점 표시를 다시 불러오지 못했습니다.'
  }
}

// ── 선택 저장(PUT) ───────────────────────────────────────────────────
function setSlotChoice(target: number, choiceNo: number | null) {
  const slot = slotFor(target)
  if (slot) slot.choiceNo = choiceNo
}

async function selectChoice(choiceNo: number | null) {
  const target = seq.value
  if (target === null || saving.value || submitting.value || isResultView.value) return
  const previous = slotFor(target)?.choiceNo ?? null
  if (previous === choiceNo && !saveError.value) return

  const token = ++saveToken
  // 먼저 화면에 반영해 그리드·진행률이 곧바로 따라온다(실패하면 되돌린다)
  setSlotChoice(target, choiceNo)
  saving.value = true
  saveError.value = null
  retryChoice.value = undefined
  try {
    const saved = await $fetch<SlotSaveResult>(
      apiUrl(`/api/sessions/${sessionId.value}/items/${target}/answer`),
      { method: 'PUT', body: { choiceNo }, retry: 0, timeout: 15000 },
    )
    if (token !== saveToken) return
    setSlotChoice(target, saved.choiceNo ?? null)
    if (item.value?.seq === target) item.value.choiceNo = saved.choiceNo ?? null
    savedAt.value = saved.answeredAt ?? null
  } catch (caught) {
    if (token !== saveToken) return
    setSlotChoice(target, previous)
    const info = describeApiError(caught, base)
    if (info.status === 409) {
      // 제출된·중단된 모의고사 — 세션을 다시 읽어 결과 화면이나 안내로 보낸다
      await loadSession()
      if (!closedNote.value && !submitted.value) closedNote.value = info.detail
    } else {
      retryChoice.value = choiceNo
      saveError.value = info.detail || info.title
    }
  } finally {
    if (token === saveToken) saving.value = false
  }
}

function retrySave() {
  const choiceNo = retryChoice.value
  if (choiceNo === undefined) return
  retryChoice.value = undefined
  saveError.value = null
  void selectChoice(choiceNo)
}

// ── 문항 이동 ────────────────────────────────────────────────────────
function moveBy(delta: number) {
  const target = (seq.value ?? 1) + delta
  if (target < 1 || target > itemCount.value) return
  void openSeq(target)
}

// ── 최종 제출(POST) ──────────────────────────────────────────────────
async function submitExam() {
  if (submitting.value) return
  submitting.value = true
  submitError.value = null
  try {
    const data = await $fetch<ExamResult>(apiUrl(`/api/sessions/${sessionId.value}/submit`), {
      method: 'POST',
      retry: 0,
      timeout: 20000,
    })
    confirmOpen.value = false
    submitted.value = data
    resumed.value = false
    seq.value = null
    item.value = null
    await refreshSession()
  } catch (caught) {
    confirmOpen.value = false
    const info = describeApiError(caught, base)
    if (info.status === 400 || info.status === 409) closedNote.value = info.detail
    else submitError.value = info
  } finally {
    submitting.value = false
  }
}

// ── 결과: 문항 해설 재조회(GET — 원장을 늘리지 않는다) ───────────────
async function openExplanation(target: number) {
  const token = ++explainToken
  explainSeq.value = target
  explainLoading.value = true
  explainError.value = null
  showAnalysis.value = false
  try {
    const data = await $fetch<SessionItemDetail>(
      apiUrl(`/api/sessions/${sessionId.value}/items/${target}`),
      { retry: 0, timeout: 10000 },
    )
    if (token !== explainToken) return
    explainItem.value = data
    await nextTick()
    explainPanel.value?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  } catch (caught) {
    if (token !== explainToken) return
    explainItem.value = null
    explainError.value = describeApiError(caught, base)
  } finally {
    if (token === explainToken) explainLoading.value = false
  }
}

function retryExplanation() {
  if (explainSeq.value !== null) void openExplanation(explainSeq.value)
}

// ── 생명주기 ─────────────────────────────────────────────────────────
onMounted(async () => {
  gridOpen.value = window.matchMedia('(min-width: 640px)').matches
  await loadSession()
})

watch(sessionId, () => {
  itemToken++
  explainToken++
  resetState()
  loadSession()
})

useHead({ title: () => `${title.value} 모의고사 — 정보처리기사 필기` })
</script>

<template>
  <div class="min-h-screen bg-white text-slate-900">
    <header class="sticky top-0 z-30 border-b border-slate-200 bg-white/95 backdrop-blur">
      <div class="mx-auto max-w-3xl px-4 py-3 sm:px-6">
        <div class="flex items-center gap-3">
          <NuxtLink to="/" class="btn-quiet shrink-0" data-tap>
            ← 홈으로
          </NuxtLink>
          <p v-if="isResultView" class="ml-auto shrink-0 text-sm font-semibold text-slate-700 sm:hidden" data-testid="exam-result-progress-mobile">
            모의고사 결과
          </p>
          <p
            v-else-if="itemCount"
            class="ml-auto shrink-0 text-sm font-semibold text-slate-700 sm:hidden"
            data-testid="exam-progress-mobile"
          >
            문항 {{ seq ?? '—' }} / {{ itemCount }}
          </p>
          <p class="hidden min-w-0 flex-1 truncate text-sm text-slate-600 sm:block" data-testid="exam-progress">
            {{ title }} · 모의고사<template v-if="isResultView"> · 결과</template><template v-else-if="itemCount"> · 문항 {{ seq ?? '—' }} / {{ itemCount }}</template>
          </p>
          <span v-if="!isResultView && itemCount" class="shrink-0 text-xs text-slate-500">
            미응답 {{ unansweredCount }}문항
          </span>
        </div>
        <p class="mt-0.5 truncate text-xs text-slate-500 sm:hidden" data-testid="exam-context-mobile">
          {{ title }} · 모의고사
        </p>
        <div
          v-if="!isResultView && itemCount"
          class="mt-2 h-2 w-full overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          :aria-valuenow="percent"
          aria-valuemin="0"
          aria-valuemax="100"
          aria-label="응답 진행률"
        >
          <div class="h-full rounded-full bg-blue-600 transition-all" :style="{ width: `${percent}%` }" />
        </div>
      </div>
    </header>

    <main class="mx-auto max-w-3xl px-4 py-6 sm:px-6 sm:py-8">
      <!-- 로딩 -->
      <section
        v-if="loading"
        class="h-64 animate-pulse rounded-2xl border border-slate-200 bg-slate-50"
        data-testid="exam-loading"
        aria-busy="true"
      >
        <span class="sr-only">모의고사를 불러오는 중입니다</span>
      </section>

      <!-- 네트워크·서버 오류 -->
      <section
        v-else-if="loadError"
        class="rounded-2xl border border-red-200 bg-red-50 p-5"
        data-testid="exam-error"
        role="alert"
      >
        <h1 class="text-base font-semibold text-red-900">
          {{ loadError.title }}
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-red-800">
          {{ loadError.detail }}
        </p>
        <pre
          v-if="loadError.command"
          class="mt-3 overflow-x-auto rounded-lg bg-red-900 p-3 text-xs text-red-50"
        >{{ loadError.command }}</pre>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <button type="button" class="btn-primary" data-tap @click="loadSession">
            다시 시도
          </button>
          <NuxtLink to="/exams" class="btn-secondary" data-tap>
            회차 목록
          </NuxtLink>
        </div>
      </section>

      <!-- 풀이할 수 없는 세션(중단·비-exam) -->
      <section
        v-else-if="closedNote"
        class="rounded-2xl border border-amber-200 bg-amber-50 p-5"
        data-testid="exam-closed"
        role="alert"
      >
        <h1 class="text-base font-semibold text-amber-900">
          {{ session?.endReason === 'abandoned' ? '중단된 모의고사입니다' : '이 세션은 모의고사가 아닙니다' }}
        </h1>
        <p class="mt-1 text-sm leading-relaxed text-amber-800">
          {{ closedNote }}
        </p>
        <div class="mt-4 flex flex-col gap-2 sm:flex-row">
          <NuxtLink v-if="canOpenPractice" :to="`/sessions/${sessionId}`" class="btn-primary" data-tap>
            연습 화면으로
          </NuxtLink>
          <NuxtLink to="/exams" class="btn-secondary" data-tap>
            회차 목록
          </NuxtLink>
          <NuxtLink to="/" class="btn-secondary" data-tap>
            홈으로
          </NuxtLink>
        </div>
      </section>

      <!-- 결과 화면 — 요약 → 과목별 점수 → 문항 그리드 → 문항별 해설 -->
      <template v-else-if="result">
        <section
          class="rounded-2xl border p-5 sm:p-6"
          :class="result.passed ? 'border-emerald-200 bg-emerald-50' : 'border-amber-200 bg-amber-50'"
          data-testid="exam-result-summary"
        >
          <div class="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span
              class="rounded-full px-3 py-1 text-sm font-bold text-white"
              :class="result.passed ? 'bg-emerald-600' : 'bg-amber-600'"
              data-testid="exam-result-verdict"
            >
              {{ result.passed ? '합격 기준 충족' : '합격 기준 미달' }}
            </span>
            <p class="text-sm text-slate-700">
              평균 <strong class="text-xl" data-testid="exam-result-average">{{ result.averageScore }}</strong>점
              <span class="text-xs text-slate-500">· 문항당 5점</span>
            </p>
          </div>
          <p class="mt-2 text-xs leading-relaxed text-slate-600">
            매 과목 40점 이상, 전 과목 평균 60점 이상이면 합격 기준을 충족합니다(정보처리기사 필기).
            <template v-if="submitTimeLabel"> 제출 {{ submitTimeLabel }}.</template>
          </p>
          <dl class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <div class="rounded-xl bg-white/80 px-3 py-2">
              <dt class="text-xs text-slate-500">전체 문항</dt>
              <dd class="text-sm font-semibold text-slate-900" data-testid="exam-result-itemcount">{{ result.itemCount }}</dd>
            </div>
            <div class="rounded-xl bg-white/80 px-3 py-2">
              <dt class="text-xs text-slate-500">응답 / 미응답</dt>
              <dd class="text-sm font-semibold text-slate-900" data-testid="exam-result-answered">
                {{ result.answeredCount }} / {{ result.unansweredCount }}
              </dd>
            </div>
            <div class="rounded-xl bg-white/80 px-3 py-2">
              <dt class="text-xs text-slate-500">정답</dt>
              <dd class="text-sm font-semibold text-emerald-700" data-testid="exam-result-correct">{{ result.correctCount }}</dd>
            </div>
            <div class="rounded-xl bg-white/80 px-3 py-2">
              <dt class="text-xs text-slate-500">오답(미응답 제외)</dt>
              <dd class="text-sm font-semibold text-red-700" data-testid="exam-result-wrong">{{ result.wrongCount }}</dd>
            </div>
          </dl>
        </section>

        <section class="mt-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6" data-testid="exam-result-subjects">
          <h2 class="text-sm font-semibold text-slate-900">
            과목별 점수
          </h2>
          <ul class="mt-2 divide-y divide-slate-100">
            <li
              v-for="row in result.bySubject"
              :key="row.subjectCode"
              class="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm"
              :data-testid="`exam-subject-${row.subjectCode}`"
            >
              <span class="min-w-0 flex-1 text-slate-800">{{ subjectLabel(row.subjectCode) }}</span>
              <span class="text-slate-600">정답 {{ row.correct }}</span>
              <span class="font-semibold text-slate-900" :data-testid="`exam-subject-score-${row.subjectCode}`">{{ row.score }}점</span>
              <span
                class="rounded-full px-2 py-0.5 text-xs font-semibold"
                :class="row.passed ? 'bg-emerald-100 text-emerald-800' : 'bg-red-100 text-red-800'"
              >
                {{ row.passed ? '40점 이상' : '40점 미만' }}
              </span>
            </li>
          </ul>
          <p class="mt-2 text-xs leading-relaxed text-slate-500">
            과목 만점 100점(문항당 5점) · 40점 미만 과목이 하나라도 있으면 불합격입니다.
          </p>
        </section>

        <section class="mt-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6" data-testid="exam-result-grid">
          <h2 class="text-sm font-semibold text-slate-900">
            문항 번호 · 채점 결과
          </h2>
          <p class="mt-2 mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
            <span class="inline-flex items-center gap-1.5">
              <span class="inline-block h-4 w-4 rounded-full bg-emerald-600" aria-hidden="true" />정답
            </span>
            <span class="inline-flex items-center gap-1.5">
              <span class="inline-block h-4 w-4 rounded-full bg-red-600" aria-hidden="true" />오답
            </span>
            <span class="inline-flex items-center gap-1.5">
              <span class="inline-block h-4 w-4 rounded-full border-2 border-dashed border-slate-300" aria-hidden="true" />미응답
            </span>
          </p>
          <p
            v-if="refreshError"
            class="mb-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-relaxed text-amber-800"
            data-testid="exam-result-refresh-error"
            role="status"
          >
            {{ refreshError }}
            <button type="button" class="ml-2 underline" data-tap @click="refreshSession">다시 불러오기</button>
          </p>
          <ExamQuestionGrid :cells="gridCells" mode="result" :current-seq="explainSeq" @select="openExplanation" />
          <p class="mt-3 text-xs leading-relaxed text-slate-500">
            번호를 누르면 그 문항과 해설을 아래에 보여줍니다. 해설 조회는 풀이 기록을 늘리지 않습니다.
          </p>
        </section>

        <section
          ref="explainPanel"
          class="mt-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6"
          data-testid="exam-explain"
        >
          <h2 class="text-sm font-semibold text-slate-900">
            문항 해설
          </h2>
          <p v-if="explainSeq === null" class="mt-2 text-sm text-slate-600">
            위 그리드에서 문항 번호를 고르면 문항·정답·해설이 여기에 표시됩니다.
          </p>
          <div
            v-else-if="explainLoading"
            class="mt-3 h-40 animate-pulse rounded-xl border border-slate-200 bg-slate-50"
            data-testid="exam-explain-loading"
            aria-busy="true"
          >
            <span class="sr-only">문항을 불러오는 중입니다</span>
          </div>
          <div
            v-else-if="explainError"
            class="mt-3 rounded-xl border border-red-200 bg-red-50 p-4 text-sm leading-relaxed text-red-800"
            data-testid="exam-explain-error"
            role="alert"
          >
            <p class="font-semibold">{{ explainError.title }}</p>
            <p class="mt-1">{{ explainError.detail }}</p>
            <button type="button" class="btn-secondary mt-3" data-tap @click="retryExplanation">
              다시 시도
            </button>
          </div>
          <template v-else-if="explainItem">
            <div class="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span class="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700">{{ explainItem.seq }} / {{ itemCount }}</span>
              <span v-if="explainItem.subjectName" class="rounded-full bg-slate-100 px-2.5 py-1">{{ explainItem.subjectName }}</span>
              <span v-if="explainItem.difficulty" class="rounded-full bg-slate-100 px-2.5 py-1">난이도 {{ explainItem.difficulty }}</span>
              <span
                class="rounded-full px-2.5 py-1 font-semibold text-white"
                :class="explainTone"
                data-testid="exam-explain-verdict"
              >
                {{ explainVerdict }}
              </span>
            </div>

            <h3 class="mt-3 text-base leading-relaxed font-semibold text-slate-900" data-testid="exam-explain-stem">
              {{ explainItem.stem }}
            </h3>

            <QuestionPassage
              v-if="explainPassageKind && explainItem.passage"
              :text="explainItem.passage"
              :kind="explainPassageKind"
            />

            <figure v-if="explainFigureSrc" class="mt-4">
              <img
                :src="explainFigureSrc"
                :alt="explainItem.figure?.alt || '문항 도식'"
                class="mx-auto max-w-full rounded-xl border border-slate-200 bg-white"
                data-testid="exam-explain-figure"
              >
              <figcaption v-if="explainItem.figure?.alt" class="mt-2 text-xs leading-relaxed text-slate-500">
                {{ explainItem.figure.alt }}
              </figcaption>
            </figure>

            <ol class="mt-4 flex flex-col gap-2">
              <li
                v-for="choice in explainItem.choices ?? []"
                :key="choice.no"
                class="flex items-start gap-2 rounded-xl border p-3 text-sm"
                :class="explainChoiceTone(choice.no)"
              >
                <span class="min-w-0 flex-1 font-medium whitespace-pre-line text-slate-900">
                  {{ choice.no }}. {{ choice.text }}
                </span>
                <span
                  v-if="explainResult && choice.no === explainResult.answer"
                  class="shrink-0 rounded-full bg-emerald-600 px-2 py-0.5 text-xs font-semibold text-white"
                >
                  정답
                </span>
                <span
                  v-else-if="explainResult && choice.no === explainResult.choiceNo"
                  class="shrink-0 rounded-full bg-red-600 px-2 py-0.5 text-xs font-semibold text-white"
                >
                  내 답
                </span>
              </li>
            </ol>

            <p
              v-if="explainResult && explainResult.choiceNo === null"
              class="mt-3 rounded-xl border border-slate-300 bg-slate-50 px-3 py-2 text-sm text-slate-700"
              data-testid="exam-explain-unanswered"
            >
              이 문항은 <strong>미응답</strong>으로 제출되었습니다 — 정답은 {{ explainResult.answer }}번입니다.
            </p>

            <h4 class="mt-4 text-sm font-semibold text-slate-900">
              해설
            </h4>
            <p
              class="mt-1 text-sm leading-relaxed whitespace-pre-line text-slate-800"
              data-testid="exam-explain-text"
            >
              {{ explainResult?.explanation }}
            </p>

            <p v-if="explainResult?.keyPoint" class="mt-3 rounded-xl bg-slate-50 px-3 py-2 text-sm leading-relaxed text-slate-700">
              <span class="font-semibold text-slate-900">핵심 개념</span> — {{ explainResult.keyPoint }}
            </p>

            <div class="mt-4 overflow-hidden rounded-xl border border-slate-200">
              <button
                type="button"
                class="flex min-h-11 w-full items-center justify-between gap-2 px-4 py-3 text-left text-sm font-semibold text-slate-800"
                :aria-expanded="showAnalysis"
                aria-controls="exam-explain-analysis"
                data-tap
                data-testid="exam-explain-analysis-toggle"
                @click="showAnalysis = !showAnalysis"
              >
                <span>보기별 해설 {{ explainResult?.choicesAnalysis?.length ?? 0 }}개 {{ showAnalysis ? '접기' : '보기' }}</span>
                <span aria-hidden="true">{{ showAnalysis ? '▲' : '▼' }}</span>
              </button>
              <ul
                v-if="showAnalysis"
                id="exam-explain-analysis"
                class="divide-y divide-slate-100 border-t border-slate-200"
                data-testid="exam-explain-analysis"
              >
                <li v-for="entry in explainResult?.choicesAnalysis ?? []" :key="entry.no" class="flex gap-3 px-4 py-3">
                  <span
                    class="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold text-white"
                    :class="entry.correct ? 'bg-emerald-600' : 'bg-slate-400'"
                  >
                    {{ entry.no }}
                  </span>
                  <div class="min-w-0">
                    <p class="text-sm font-medium whitespace-pre-line text-slate-900">
                      {{ explainChoiceText(entry.no) }}
                      <span v-if="entry.no === explainResult?.choiceNo" class="ml-1 text-xs font-semibold text-blue-700">(내가 고른 보기)</span>
                    </p>
                    <p class="mt-0.5 text-sm leading-relaxed text-slate-600">
                      {{ entry.why }}
                    </p>
                  </div>
                </li>
              </ul>
            </div>
          </template>
        </section>
      </template>

      <!-- 풀이 화면 — 문항 → 선택 → 이전/다음 → 제출 → 번호 그리드 -->
      <template v-else-if="session">
        <!-- 선택 저장 상태 -->
        <p
          class="mb-4 rounded-xl border px-4 py-2 text-xs leading-relaxed"
          :class="saveError ? 'border-red-200 bg-red-50 text-red-800' : 'border-slate-200 bg-slate-50 text-slate-600'"
          data-testid="exam-save-status"
          role="status"
          aria-live="polite"
        >
          <template v-if="saving">선택을 저장하는 중…</template>
          <template v-else-if="saveError">
            선택을 저장하지 못했습니다 — {{ saveError }}
            <button type="button" class="ml-1 font-semibold underline" data-tap data-testid="exam-save-retry" @click="retrySave">
              다시 시도
            </button>
          </template>
          <template v-else-if="savedAt">보기를 저장했습니다 ({{ formatTime(savedAt) }}) — 제출 전에는 언제든 바꿀 수 있습니다.</template>
          <template v-else>보기를 고르면 바로 저장됩니다. 제출 전에는 언제든 바꿀 수 있습니다.</template>
        </p>

        <!-- 문항 로딩 -->
        <section
          v-if="itemLoading && !item"
          class="h-64 animate-pulse rounded-2xl border border-slate-200 bg-slate-50"
          data-testid="exam-item-loading"
          aria-busy="true"
        >
          <span class="sr-only">문항을 불러오는 중입니다</span>
        </section>

        <section
          v-else-if="itemError"
          class="rounded-2xl border border-red-200 bg-red-50 p-5"
          data-testid="exam-item-error"
          role="alert"
        >
          <h2 class="text-base font-semibold text-red-900">
            {{ itemError.title }}
          </h2>
          <p class="mt-1 text-sm leading-relaxed text-red-800">
            {{ itemError.detail }}
          </p>
          <button type="button" class="btn-secondary mt-3" data-tap @click="retryItem">
            다시 시도
          </button>
        </section>

        <template v-else-if="item">
          <p
            v-if="resumed"
            class="mb-4 rounded-xl border border-blue-200 bg-blue-50 px-4 py-2 text-xs leading-relaxed text-blue-800"
            data-testid="exam-resume"
          >
            이어서 풀기 — 전에 고른 {{ answeredCount }}문항은 그대로 두고, 선택하지 않은 {{ seq }}번 문항부터 이어집니다.
          </p>

          <article class="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6" data-testid="exam-item">
            <div class="flex flex-wrap items-center gap-2 text-xs text-slate-500">
              <span class="rounded-full bg-slate-100 px-2.5 py-1 font-semibold text-slate-700" data-testid="exam-item-seq">
                {{ seq }} / {{ itemCount }}
              </span>
              <span v-if="item.subjectName" class="rounded-full bg-slate-100 px-2.5 py-1">{{ item.subjectName }}</span>
              <span v-if="item.difficulty" class="rounded-full bg-slate-100 px-2.5 py-1">난이도 {{ item.difficulty }}</span>
              <span v-for="tag in item.tags" :key="tag" class="rounded-full bg-slate-100 px-2.5 py-1">{{ tag }}</span>
            </div>

            <h1 class="mt-4 text-lg leading-relaxed font-semibold text-slate-900 sm:text-xl" data-testid="exam-stem">
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
                data-testid="exam-figure"
              >
              <figcaption v-if="item.figure?.alt" class="mt-2 text-xs leading-relaxed text-slate-500">
                {{ item.figure.alt }}
              </figcaption>
            </figure>
            <p v-else-if="item.figure?.needed" class="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3 text-xs text-slate-500">
              이 문항에는 도식이 있지만 이미지 경로가 없습니다.
            </p>

            <!-- 보기 선택 — 고르면 즉시 저장(제출 전 자유 수정) -->
            <fieldset class="mt-5" :disabled="saving || submitting">
              <legend class="sr-only">보기 선택 — 고르면 바로 저장됩니다</legend>
              <div class="flex flex-col gap-2">
                <label
                  v-for="choice in choices"
                  :key="choice.no"
                  class="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm transition"
                  :class="currentChoice === choice.no
                    ? 'border-blue-500 bg-blue-50 ring-1 ring-blue-500'
                    : 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'"
                  data-tap
                  :data-testid="`exam-choice-${choice.no}`"
                >
                  <input
                    type="radio"
                    name="exam-choice"
                    class="mt-0.5 h-5 w-5 shrink-0 accent-blue-600"
                    :value="choice.no"
                    :checked="currentChoice === choice.no"
                    :disabled="saving || submitting"
                    @change="selectChoice(choice.no)"
                  >
                  <span class="min-w-0 flex-1 font-medium whitespace-pre-line text-slate-900">
                    {{ choice.no }}. {{ choice.text }}
                  </span>
                </label>
              </div>
            </fieldset>

            <div class="mt-3 flex flex-wrap items-center gap-3">
              <button
                v-if="currentChoice !== null"
                type="button"
                class="btn-secondary"
                data-tap
                data-testid="exam-clear"
                :disabled="saving || submitting"
                @click="selectChoice(null)"
              >
                선택 해제
              </button>
              <p class="text-xs leading-relaxed text-slate-500">
                정답·해설은 최종 제출 뒤에 확인할 수 있습니다.
              </p>
            </div>
          </article>

          <!-- 이전·다음 문항 -->
          <div class="mt-4 flex items-center justify-between gap-2">
            <button
              type="button"
              class="btn-secondary"
              data-tap
              data-testid="exam-prev"
              :disabled="!canPrev || itemLoading"
              @click="moveBy(-1)"
            >
              ← 이전 문항
            </button>
            <button
              type="button"
              class="btn-secondary"
              data-tap
              data-testid="exam-next"
              :disabled="!canNext || itemLoading"
              @click="moveBy(1)"
            >
              다음 문항 →
            </button>
          </div>

          <!-- 최종 제출 -->
          <section
            class="mt-4 rounded-2xl border p-5 sm:p-6"
            :class="unansweredCount > 0 ? 'border-amber-200 bg-amber-50' : 'border-slate-200 bg-slate-50'"
            data-testid="exam-submit-panel"
          >
            <h2 class="text-sm font-semibold text-slate-900">
              최종 제출
            </h2>
            <p class="mt-1 text-sm leading-relaxed text-slate-700">
              응답 {{ answeredCount }} / {{ itemCount }}문항
              <template v-if="unansweredCount > 0">
                · <strong class="text-amber-900">미응답 {{ unansweredCount }}문항</strong>
              </template>
              <template v-else> · 미응답 없음</template>
            </p>
            <p class="mt-1 text-xs leading-relaxed text-slate-500">
              제출하면 전 문항이 한 번에 채점되고 결과·해설을 볼 수 있습니다. 제한시간은 없습니다.
            </p>
            <button
              type="button"
              class="btn-primary mt-3 w-full sm:w-auto"
              data-tap
              data-testid="exam-submit"
              :disabled="submitting || saving"
              @click="confirmOpen = true"
            >
              모의고사 제출
            </button>
            <p
              v-if="submitError"
              class="mt-3 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm leading-relaxed text-red-800"
              data-testid="exam-submit-error"
              role="alert"
            >
              {{ submitError.title }} — {{ submitError.detail }}
              다시 눌러도 같은 결과가 나옵니다(제출은 한 번만 반영됩니다).
            </p>
          </section>

          <!-- 번호 그리드 — 임의 문항으로 이동 -->
          <section class="mt-4 rounded-2xl border border-slate-200 bg-white p-5 sm:p-6" data-testid="exam-grid-panel">
            <button
              type="button"
              class="flex min-h-11 w-full items-center justify-between gap-2 text-left"
              :aria-expanded="gridOpen"
              aria-controls="exam-grid"
              data-tap
              data-testid="exam-grid-toggle"
              @click="gridOpen = !gridOpen"
            >
              <span class="text-sm font-semibold text-slate-900">
                문항 번호
                <span class="font-normal text-slate-500">· 선택 {{ answeredCount }} · 미응답 {{ unansweredCount }}</span>
              </span>
              <span aria-hidden="true">{{ gridOpen ? '▲' : '▼' }}</span>
            </button>
            <div v-if="gridOpen" id="exam-grid" class="mt-4">
              <p class="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
                <span class="inline-flex items-center gap-1.5">
                  <span class="inline-block h-4 w-4 rounded-full bg-blue-600" aria-hidden="true" />선택됨
                </span>
                <span class="inline-flex items-center gap-1.5">
                  <span class="inline-block h-4 w-4 rounded-full border-2 border-dashed border-slate-300" aria-hidden="true" />미응답
                </span>
                <span class="inline-flex items-center gap-1.5">
                  <span class="inline-block h-4 w-4 rounded-full ring-2 ring-slate-900 ring-offset-1" aria-hidden="true" />지금 보는 문항
                </span>
              </p>
              <ExamQuestionGrid :cells="gridCells" mode="taking" :current-seq="seq" @select="openSeq" />
              <p class="mt-3 text-xs leading-relaxed text-slate-500">
                번호를 누르면 그 문항으로 이동합니다(방향키로도 옮길 수 있습니다).
              </p>
            </div>
          </section>
        </template>
      </template>
    </main>

    <!-- 최종 제출 확인 — 미응답 문항 수를 강조한다 -->
    <AppConfirmDialog
      :open="confirmOpen"
      :busy="submitting"
      title="모의고사를 제출할까요?"
      confirm-label="제출하기"
      busy-label="제출 중…"
      cancel-label="계속 풀기"
      @confirm="submitExam"
      @cancel="confirmOpen = false"
    >
      <p>제출하면 전 문항이 한 번에 채점되고 답을 바꿀 수 없습니다. 결과와 해설은 바로 확인할 수 있습니다.</p>
      <p
        v-if="unansweredCount > 0"
        class="mt-3 flex items-baseline justify-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-3 py-2 text-amber-900"
        data-testid="submit-unanswered"
      >
        <span class="text-sm">미응답</span>
        <strong class="text-2xl">{{ unansweredCount }}</strong>
        <span class="text-sm">문항</span>
      </p>
      <p
        v-else
        class="mt-3 rounded-xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-center text-sm text-emerald-800"
        data-testid="submit-unanswered"
      >
        미응답 없이 {{ answeredCount }}문항을 모두 골랐습니다.
      </p>
    </AppConfirmDialog>
  </div>
</template>
