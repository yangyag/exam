<script setup lang="ts">
// 확인 대화상자 — 새로 구성·모의고사 제출처럼 되돌릴 수 없는 동작 전에 한 번 묻는다.
// 본문은 기본 슬롯으로 대체할 수 있다(모의고사 제출처럼 수치를 강조해야 할 때).
const props = defineProps<{
  open: boolean
  title: string
  body?: string
  confirmLabel?: string
  cancelLabel?: string
  /** 진행 중일 때 확인 버튼 문구 */
  busyLabel?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const confirmButton = ref<HTMLButtonElement | null>(null)
const dialog = ref<HTMLElement | null>(null)
// 대화상자를 닫을 때 원래 포커스로 돌려준다(키보드 사용자)
let lastActive: HTMLElement | null = null

watch(
  () => props.open,
  async (open) => {
    if (open) {
      lastActive = document.activeElement as HTMLElement | null
      await nextTick()
      confirmButton.value?.focus()
    } else {
      lastActive?.focus()
      lastActive = null
    }
  },
)

// 대화상자 안의 포커스 가능한 요소 — Tab 순환 범위
function focusables(): HTMLElement[] {
  const root = dialog.value
  if (!root) return []
  return Array.from(
    root.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    ),
  ).filter((el) => el.offsetParent !== null)
}

function onKeydown(event: KeyboardEvent) {
  if (!props.open) return

  if (event.key === 'Escape') {
    event.preventDefault()
    emit('cancel')
    return
  }
  if (event.key !== 'Tab') return

  // aria-modal 을 선언했으므로 Tab 이 배경으로 빠져나가면 안 된다 — 마지막에서 처음으로 되돌린다
  const items = focusables()
  if (items.length === 0) return
  const first = items[0]
  const last = items[items.length - 1]
  const active = document.activeElement
  const inside = active instanceof HTMLElement && Boolean(dialog.value?.contains(active))

  if (event.shiftKey && (active === first || !inside)) {
    event.preventDefault()
    last?.focus()
  } else if (!event.shiftKey && (active === last || !inside)) {
    event.preventDefault()
    first?.focus()
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-slate-900/40" @click="emit('cancel')" />
      <div
        ref="dialog"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        class="relative w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl"
        data-testid="confirm-dialog"
      >
        <h2 class="text-base font-semibold text-slate-900">
          {{ title }}
        </h2>
        <div class="mt-2 text-sm leading-relaxed text-slate-600">
          <slot>{{ body }}</slot>
        </div>
        <div class="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button
            ref="confirmButton"
            type="button"
            class="btn-primary sm:order-2"
            data-tap
            :disabled="busy"
            @click="emit('confirm')"
          >
            {{ busy ? (busyLabel ?? '처리 중…') : (confirmLabel ?? '확인') }}
          </button>
          <button
            type="button"
            class="btn-secondary sm:order-1"
            data-tap
            :disabled="busy"
            @click="emit('cancel')"
          >
            {{ cancelLabel ?? '취소' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
