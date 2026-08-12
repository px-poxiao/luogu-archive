<script setup lang="ts">
const props = defineProps<{ level: number; compact?: boolean }>()
const { requestLevel } = usePluginLabels()
const meta = computed(() => requestLevel(props.level))
</script>

<template>
  <span
    class="request-level"
    :class="[meta.className, { compact }]"
    :title="`请求等级 ${level}：${meta.label}`"
    :aria-label="`请求等级 ${level}：${meta.label}`"
  >
    <span class="label">请求等级</span>
    <span class="number" aria-hidden="true">{{ level }}</span>
  </span>
</template>

<style scoped>
.request-level {
  --level-color: #2da44e;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 30px;
  padding: 2px 4px 2px 11px;
  border: 1px solid var(--level-color);
  border-radius: 999px;
  background: color-mix(in srgb, var(--level-color) 8%, var(--surface));
  color: var(--level-color);
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.number { display: inline-grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; background: var(--level-color); color: #fff; line-height: 1; }
.level-1 { --level-color: #7aa61f; }
.level-2 { --level-color: #c69200; }
.level-3 { --level-color: #d1242f; }
.compact { min-height: 25px; gap: 6px; padding-left: 9px; font-size: 12px; }
.compact .number { width: 20px; height: 20px; }
.dark .level-0 { --level-color: #56d364; }
.dark .level-1 { --level-color: #a8c94a; }
.dark .level-2 { --level-color: #e3b341; }
.dark .level-3 { --level-color: #ff7b72; }
</style>
