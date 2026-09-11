<script setup lang="ts">
// 모의고사 문항 번호 그리드 — 100문항 중 아무 번호로나 바로 이동한다(설계 3.2절).
// 풀이 중에는 선택 여부만 보여주고(채운 원 = 선택됨, 빈 원 = 미응답) 정답은 드러내지 않는다.
// 제출 뒤에는 정답·오답·미응답을 색으로 구분한다.
type GridCell = {
  seq: number
  /** 고른 보기 번호(모의고사에서는 null 이 미응답) */
  choiceNo: number | null
  /** 제출 뒤 채점 결과(풀이 중에는 null) */
  isCorrect: boolean | null
}

const props = defineProps<{
  cells: GridCell[]
  /** taking = 풀이 중(정답 비공개), result = 제출 뒤 결과 */
  mode: 'taking' | 'result'
  currentSeq?: number | null
}>()

const emit = defineEmits<{ select: [seq: number] }>()

/** 방향키 위·아래 이동 단위(데스크톱 10열 기준) */
const ARROW_STEP = 10

const buttons = new Map<number, HTMLButtonElement>()
// 로빙 tabindex — 그리드 전체가 키보드 탭 정지 1개가 되고, 방향키로 안에서 움직인다
const focusSeq = ref<number>(props.currentSeq ?? props.cells[0]?.seq ?? 1)

watch(
  () => props.currentSeq,
  (value) => {
    if (value) focusSeq.value = value
  },
)

type CellState = 'unanswered' | 'chosen' | 'correct' | 'wrong'

function cellState(cell: GridCell): CellState {
  if (props.mode === 'result') {
    if (cell.choiceNo === null) return 'unanswered'
    // 채점 결과를 못 받은 슬롯(재조회 실패)은 정오답을 단정하지 않는다
    if (cell.isCorrect === null) return 'chosen'
    return cell.isCorrect ? 'correct' : 'wrong'
  }
  return cell.choiceNo === null ? 'unanswered' : 'chosen'
}

const stateClasses: Record<CellState, string> = {
  unanswered: 'border-2 border-dashed border-slate-300 bg-white text-slate-600 hover:border-slate-400 hover:bg-slate-50',
  chosen: 'border-2 border-blue-600 bg-blue-600 font-bold text-white hover:bg-blue-700',
  correct: 'border-2 border-emerald-600 bg-emerald-600 font-bold text-white',
  wrong: 'border-2 border-red-600 bg-red-600 font-bold text-white',
}

const stateLabels: Record<CellState, string> = {
  unanswered: '미응답',
  chosen: '선택됨',
  correct: '정답',
  wrong: '오답',
}

/** 방향키·Home·End 로 옮기면 그 문항을 바로 연다(문항 이동이 목적이라 한 번에 움직인다) */
function move(target: number) {
  const clamped = Math.min(Math.max(target, 1), props.cells.length)
  focusSeq.value = clamped
  emit('select', clamped)
  nextTick(() => buttons.get(clamped)?.focus())
}

function onKeydown(cell: GridCell, event: KeyboardEvent) {
  if (event.key === 'ArrowRight') move(cell.seq + 1)
  else if (event.key === 'ArrowLeft') move(cell.seq - 1)
  else if (event.key === 'ArrowDown') move(cell.seq + ARROW_STEP)
  else if (event.key === 'ArrowUp') move(cell.seq - ARROW_STEP)
  else if (event.key === 'Home') move(1)
  else if (event.key === 'End') move(props.cells.length)
  else return
  event.preventDefault()
}

function setButton(seq: number, el: unknown) {
  if (el instanceof HTMLButtonElement) buttons.set(seq, el)
  else buttons.delete(seq)
}
</script>

<template>
  <div
    class="grid grid-cols-6 justify-items-center gap-x-3 gap-y-2 sm:grid-cols-10 sm:gap-x-4"
    role="group"
    :aria-label="mode === 'result' ? '문항 번호와 채점 결과' : '문항 번호'"
  >
    <button
      v-for="cell in cells"
      :key="cell.seq"
      :ref="(el) => setButton(cell.seq, el)"
      type="button"
      class="flex h-11 w-11 items-center justify-center rounded-full text-sm transition focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:outline-none"
      :class="[stateClasses[cellState(cell)], cell.seq === currentSeq ? 'ring-2 ring-slate-900 ring-offset-2' : '']"
      :tabindex="cell.seq === focusSeq ? 0 : -1"
      :aria-current="cell.seq === currentSeq ? 'true' : undefined"
      :aria-label="`${cell.seq}번 문항 — ${stateLabels[cellState(cell)]}`"
      data-tap
      :data-testid="`exam-grid-${cell.seq}`"
      :data-state="cellState(cell)"
      @click="emit('select', cell.seq)"
      @keydown="onKeydown(cell, $event)"
    >
      {{ cell.seq }}
    </button>
  </div>
</template>
