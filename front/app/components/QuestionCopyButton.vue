<script setup lang="ts">
import type { SessionItemDetail } from '~/types/api'

// 문항 텍스트를 클립보드로 복사하는 버튼 — 연습·모의고사 문항 카드가 같이 쓴다.
// 복사하는 것은 화면에 보이는 것뿐이다: 문제 문장 → 지문(코드·표·본문) → 보기 4개.
// 정답·해설(answer·explanation·choicesAnalysis)은 조회 응답에 없거나 채점 뒤에만 오므로 여기서 넣지 않는다.
// 그림이 있는 문항은 텍스트만 복사하면 뜻이 달라지므로 복사하지 않고 안내만 보여준다.
const props = defineProps<{
  stem: string
  passage?: string | null
  choices?: SessionItemDetail['choices']
  /** figure.needed — 그림이 있어 복사할 수 없는 문항인지 */
  figureNeeded: boolean
}>()

// 안내 문구를 보여주는 시간(ms). "잠깐 표시"라 복사 후 저절로 사라진다.
const NOTE_MS = 3000

const note = ref('')
const noteTone = ref<'done' | 'blocked'>('done')
let noteTimer: ReturnType<typeof setTimeout> | null = null

/** 화면에 보이는 순서 그대로 — 문제 문장, 지문, 보기 4개를 빈 줄로 나눈다. */
function copyText(): string {
  const blocks = [props.stem]
  if (props.passage) blocks.push(props.passage)
  blocks.push(...(props.choices ?? []).map((choice) => `${choice.no}. ${choice.text}`))
  return blocks.join('\n\n')
}

function showNote(message: string, tone: 'done' | 'blocked'): void {
  note.value = message
  noteTone.value = tone
  if (noteTimer) clearTimeout(noteTimer)
  noteTimer = setTimeout(() => { note.value = '' }, NOTE_MS)
}

async function copy(): Promise<void> {
  if (props.figureNeeded) {
    showNote('그림이 있는 문항은 복사할 수 없습니다.', 'blocked')
    return
  }
  try {
    await navigator.clipboard.writeText(copyText())
    showNote('복사됨', 'done')
  } catch {
    // 보안 컨텍스트가 아니거나 클립보드 권한이 거부된 경우
    showNote('복사하지 못했습니다.', 'blocked')
  }
}

onBeforeUnmount(() => {
  if (noteTimer) clearTimeout(noteTimer)
})
</script>

<template>
  <div class="flex flex-wrap items-center gap-2">
    <button
      type="button"
      class="btn-quiet border border-slate-300 hover:border-slate-400"
      data-testid="question-copy"
      data-tap
      @click="copy"
    >
      복사
    </button>
    <!-- role=status — 안내 문구가 바뀌면 보조기술이 읽는다. 비어 있을 때도 자리를 지킨다 -->
    <span
      class="text-xs font-medium"
      :class="noteTone === 'blocked' ? 'text-amber-700' : 'text-emerald-700'"
      data-testid="question-copy-note"
      role="status"
    >{{ note }}</span>
  </div>
</template>
