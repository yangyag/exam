<script setup lang="ts">
// 확인 대화상자 — 새로 구성처럼 되돌릴 수 없는 동작 전에 한 번 묻는다.
const props = defineProps<{
  open: boolean
  title: string
  body: string
  confirmLabel?: string
  cancelLabel?: string
  busy?: boolean
}>()

const emit = defineEmits<{
  confirm: []
  cancel: []
}>()

const confirmButton = ref<HTMLButtonElement | null>(null)
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

function onKeydown(event: KeyboardEvent) {
  if (!props.open || event.key !== 'Escape') return
  event.preventDefault()
  emit('cancel')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <div v-if="open" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-slate-900/40" @click="emit('cancel')" />
      <div
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        class="relative w-full max-w-sm rounded-2xl bg-white p-5 shadow-xl"
        data-testid="confirm-dialog"
      >
        <h2 class="text-base font-semibold text-slate-900">
          {{ title }}
        </h2>
        <p class="mt-2 text-sm leading-relaxed text-slate-600">
          {{ body }}
        </p>
        <div class="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-end">
          <button
            ref="confirmButton"
            type="button"
            class="btn-primary sm:order-2"
            data-tap
            :disabled="busy"
            @click="emit('confirm')"
          >
            {{ busy ? '구성 중…' : (confirmLabel ?? '확인') }}
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
