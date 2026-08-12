<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'

const model = defineModel<PluginSnapshot>({ required: true })
const props = defineProps<{ tags: PluginTag[]; adminFields?: boolean }>()

const adminAnalysis = computed({
  get: () => model.value.admin_request_analysis || '',
  set: value => { model.value.admin_request_analysis = value || null },
})

const adminLevelEnabled = computed({
  get: () => model.value.admin_request_level !== null && model.value.admin_request_level !== undefined,
  set: (enabled: boolean) => {
    model.value.admin_request_level = enabled ? model.value.user_request_level : null
  },
})

const codeBytes = computed(() => new TextEncoder().encode(model.value.code || '').length)
const codeTooLarge = computed(() => codeBytes.value > 5 * 1024 * 1024)
const codeSizeText = computed(() => {
  if (codeBytes.value < 1024) return `${codeBytes.value} B`
  if (codeBytes.value < 1024 * 1024) return `${(codeBytes.value / 1024).toFixed(1)} KiB`
  return `${(codeBytes.value / 1024 / 1024).toFixed(2)} MiB`
})

function toggleTag(tagId: number, checked: boolean) {
  const values = new Set(model.value.tag_ids)
  checked ? values.add(tagId) : values.delete(tagId)
  model.value.tag_ids = [...values]
}
</script>

<template>
  <div class="snapshot-form">
    <section class="form-section">
      <h2>基本信息</h2>
      <label>
        <span>简短介绍（可选）</span>
        <textarea
          v-model.trim="model.summary"
          maxlength="50"
          rows="3"
          placeholder="留空时从文章正文中自动生成"
        />
      </label>
      <fieldset>
        <legend>功能标签（可不选）</legend>
        <div class="choice-row">
          <label v-for="tag in props.tags" :key="tag.id" class="check-option">
            <input
              type="checkbox"
              :checked="model.tag_ids.includes(tag.id)"
              @change="toggleTag(tag.id, ($event.target as HTMLInputElement).checked)"
            >
            <span>{{ tag.name }}</span>
          </label>
        </div>
      </fieldset>
    </section>

    <section class="form-section">
      <div class="section-heading">
        <h2>代码</h2>
        <span :class="{ danger: codeTooLarge }">{{ codeSizeText }} / 5 MiB</span>
      </div>
      <label class="version-field">
        <span>代码版本</span>
        <input v-model.trim="model.version" maxlength="64" placeholder="例如 1.0.0" required>
      </label>
      <label>
        <span>代码内容</span>
        <textarea v-model="model.code" class="code-input" rows="18" spellcheck="false" required />
      </label>
      <label>
        <span>下载文件名</span>
        <input v-model.trim="model.download_filename" maxlength="128" placeholder="plugin.user.js" required>
      </label>
    </section>

    <section class="form-section">
      <h2>运行与兼容</h2>
      <div class="form-grid two">
        <label>
          <span>运行方式</span>
          <select v-model="model.runtime_mode">
            <option value="userscript">用户脚本</option>
            <option value="extension">浏览器扩展</option>
            <option value="bookmarklet">书签脚本</option>
            <option value="other">其他</option>
          </select>
        </label>
        <label>
          <span>最后验证日期</span>
          <input v-model="model.last_verified_on" type="date" required>
        </label>
      </div>
      <fieldset>
        <legend>兼容设备</legend>
        <div class="choice-row">
          <label class="check-option"><input v-model="model.supports_desktop" type="checkbox"><span>桌面端</span></label>
          <label class="check-option"><input v-model="model.supports_mobile" type="checkbox"><span>移动端</span></label>
        </div>
      </fieldset>
    </section>

    <section class="form-section">
      <h2>请求说明</h2>
      <div class="level-editor" :class="`level-${model.user_request_level}`">
        <div class="level-heading">
          <span>用户提交的请求等级</span>
          <PluginRequestLevelBadge :level="model.user_request_level" />
        </div>
        <input v-model.number="model.user_request_level" type="range" min="0" max="3" step="1" aria-label="用户提交的请求等级">
        <div class="level-ticks" aria-hidden="true"><span>0</span><span>1</span><span>2</span><span>3</span></div>
      </div>
      <p class="field-help">
        建议说明访问的域名或接口、触发方式、单次请求数量、周期刷新或并发行为，以及是否读取 Cookie、Token、localStorage 或向第三方发送数据。
      </p>
      <PluginMarkdownEditor
        v-model="model.user_request_analysis"
        label="上传者请求分析"
        :maxlength="20000"
        placeholder="使用 Markdown 描述插件的网络请求行为"
      />

      <template v-if="adminFields">
        <label class="admin-level-toggle">
          <input v-model="adminLevelEnabled" type="checkbox">
          <span>由管理员调整请求等级</span>
        </label>
        <div
          v-if="adminLevelEnabled"
          class="level-editor admin-level"
          :class="`level-${model.admin_request_level ?? model.user_request_level}`"
        >
          <div class="level-heading">
            <span>管理员请求等级</span>
            <PluginRequestLevelBadge :level="model.admin_request_level ?? model.user_request_level" />
          </div>
          <input v-model.number="model.admin_request_level" type="range" min="0" max="3" step="1" aria-label="管理员请求等级">
          <div class="level-ticks" aria-hidden="true"><span>0</span><span>1</span><span>2</span><span>3</span></div>
        </div>
        <PluginMarkdownEditor
          v-model="adminAnalysis"
          label="管理组请求分析"
          :maxlength="20000"
          placeholder="管理组人工审核结论（可留空）"
        />
      </template>
    </section>
  </div>
</template>

<style scoped>
.snapshot-form { display: grid; gap: 28px; }
.form-section { display: grid; gap: 16px; padding-bottom: 26px; border-bottom: 1px solid var(--border); }
.form-section:last-child { border-bottom: 0; padding-bottom: 0; }
h2 { margin: 0; font-size: 19px; }
.section-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; }
.section-heading span { color: var(--text-muted); font-size: 13px; }
.section-heading .danger { color: var(--lg-red); font-weight: 600; }
.version-field { width: min(360px, 100%); }
.form-grid { display: grid; gap: 16px; }
.form-grid.two { grid-template-columns: repeat(2, minmax(0, 1fr)); }
label { display: grid; gap: 7px; }
label > span, legend { font-size: 14px; font-weight: 600; }
input, textarea, select {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  padding: 9px 10px;
  font: inherit;
}
textarea { resize: vertical; line-height: 1.55; }
.code-input { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 13px; tab-size: 2; }
fieldset { margin: 0; padding: 0; border: 0; }
legend { margin-bottom: 8px; }
.choice-row { display: flex; flex-wrap: wrap; gap: 8px 16px; }
.check-option { display: inline-flex; grid-template-columns: none; align-items: center; gap: 7px; font-weight: 400; }
.check-option input { width: 16px; height: 16px; margin: 0; }
.check-option span { font-weight: 400; }
.field-help { margin: -6px 0 0; color: var(--text-muted); font-size: 13px; }
.level-editor { --level-color: #2da44e; display: grid; gap: 8px; padding: 13px 15px 10px; border: 1px solid color-mix(in srgb, var(--level-color) 55%, var(--border)); border-radius: 8px; background: color-mix(in srgb, var(--level-color) 7%, var(--surface)); }
.level-editor.level-1 { --level-color: #7aa61f; }
.level-editor.level-2 { --level-color: #c69200; }
.level-editor.level-3 { --level-color: #d1242f; }
.level-heading { display: flex; align-items: center; justify-content: space-between; gap: 14px; font-size: 14px; font-weight: 600; }
.level-editor input[type="range"] { width: 100%; padding: 0; border: 0; accent-color: var(--level-color); cursor: pointer; }
.level-ticks { display: flex; justify-content: space-between; padding: 0 2px; color: var(--text-muted); font-size: 11px; }
.admin-level-toggle { display: inline-flex; grid-template-columns: none; align-items: center; justify-self: start; gap: 8px; }
.admin-level-toggle input { width: 16px; height: 16px; margin: 0; }
@media (max-width: 700px) {
  .form-grid.two { grid-template-columns: 1fr; }
}
</style>
