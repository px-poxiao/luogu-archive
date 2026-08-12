<script setup lang="ts">
const model = defineModel<string>({ required: true })
defineProps<{
  label: string
  placeholder?: string
  maxlength?: number
}>()

const mode = ref<'write' | 'preview'>('write')
const { render } = useMarkdown()
const previewHtml = computed(() => render(model.value || ''))
</script>

<template>
  <div class="markdown-editor">
    <div class="editor-head">
      <label>{{ label }}</label>
      <div class="mode-tabs" role="tablist" aria-label="编辑模式">
        <button type="button" :class="{ active: mode === 'write' }" @click="mode = 'write'">编辑</button>
        <button type="button" :class="{ active: mode === 'preview' }" @click="mode = 'preview'">预览</button>
      </div>
    </div>
    <textarea
      v-if="mode === 'write'"
      v-model="model"
      :placeholder="placeholder"
      :maxlength="maxlength"
      rows="12"
    />
    <div v-else class="preview lg-content" v-html="previewHtml" />
  </div>
</template>

<style scoped>
.markdown-editor { display: grid; gap: 8px; }
.editor-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.editor-head label { font-weight: 600; }
.mode-tabs { display: flex; border-bottom: 1px solid var(--border); }
.mode-tabs button {
  border: 0;
  border-bottom: 2px solid transparent;
  background: transparent;
  color: var(--text-muted);
  padding: 5px 12px;
  cursor: pointer;
}
.mode-tabs button.active { border-bottom-color: var(--link); color: var(--link); }
textarea {
  width: 100%;
  min-height: 220px;
  box-sizing: border-box;
  resize: vertical;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  padding: 12px;
  font: inherit;
  line-height: 1.6;
}
.preview { min-height: 220px; border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
</style>
