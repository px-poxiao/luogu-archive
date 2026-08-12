<script setup lang="ts">
const props = defineProps<{ level: number; compact?: boolean }>()
const { requestLevel } = usePluginLabels()
const meta = computed(() => requestLevel(props.level))
</script>

<template>
  <span class="request-level" :class="[meta.className, { compact }]">
    <span class="dot" aria-hidden="true" />
    {{ meta.label }}
  </span>
</template>

<style scoped>
.request-level {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 26px;
  padding: 2px 9px;
  border: 1px solid currentColor;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.level-0 { color: #2da44e; }
.level-1 { color: #779c20; }
.level-2 { color: #b88700; }
.level-3 { color: #cf222e; }
.compact { min-height: 22px; padding: 1px 7px; font-size: 12px; }
.dark .level-0 { color: #56d364; }
.dark .level-1 { color: #a8c94a; }
.dark .level-2 { color: #e3b341; }
.dark .level-3 { color: #ff7b72; }
</style>
