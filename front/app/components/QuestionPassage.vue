<script setup lang="ts">
// 지문(passage) 렌더 — 자료 처리 정책상 표·코드도 텍스트로 복원돼 있다(AGENTS.md).
//   code  : 줄바꿈·들여쓰기 보존(고정폭)
//   table : 행은 줄바꿈, 열은 ' | ' 구분 — 고정폭으로 정렬을 살린다
//   text  : 문단(줄바꿈은 그대로 살리되 폭에 맞춰 흘린다)
defineProps<{
  text: string
  kind: 'code' | 'table' | 'text'
}>()

const kindLabel: Record<'code' | 'table' | 'text', string> = {
  code: '코드',
  table: '표',
  text: '지문',
}
</script>

<template>
  <div
    class="mt-4 overflow-hidden rounded-xl border border-slate-200 bg-slate-50"
    :data-testid="`passage-${kind}`"
  >
    <p class="border-b border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-500">
      {{ kindLabel[kind] }}
    </p>
    <pre
      v-if="kind === 'code' || kind === 'table'"
      class="overflow-x-auto px-3 py-3 font-mono text-[13px] leading-relaxed whitespace-pre text-slate-800"
    >{{ text }}</pre>
    <p v-else class="px-3 py-3 text-sm leading-relaxed whitespace-pre-line text-slate-800">
      {{ text }}
    </p>
  </div>
</template>
