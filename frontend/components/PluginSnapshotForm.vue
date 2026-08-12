<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'

const model = defineModel<PluginSnapshot>({ required: true })
const props = defineProps<{ tags: PluginTag[]; adminFields?: boolean }>()

const adminAnalysis = computed({
  get: () => model.value.admin_request_analysis || '',
  set: value => { model.value.admin_request_analysis = value || null },
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
      <div class="form-grid two">
        <label>
          <span>插件名称</span>
          <input v-model.trim="model.name" maxlength="80" required>
        </label>
        <label>
          <span>代码版本</span>
          <input v-model.trim="model.version" maxlength="64" placeholder="例如 1.0.0" required>
        </label>
      </div>
      <label>
        <span>简短介绍</span>
        <textarea v-model.trim="model.summary" maxlength="300" rows="3" required />
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
      <label>
        <span>生效页面</span>
        <textarea v-model.trim="model.target_pages" rows="3" maxlength="5000" placeholder="说明会在哪些页面生效" required />
      </label>
      <div class="form-grid two">
        <label>
          <span>最低适配日期（可选）</span>
          <input v-model="model.min_compatible_date" type="date">
        </label>
        <label>
          <span>兼容说明</span>
          <textarea v-model.trim="model.compatibility_notes" rows="3" maxlength="5000" placeholder="与最低适配日期至少填写一项" />
        </label>
      </div>
    </section>

    <section class="form-section">
      <h2>请求说明</h2>
      <label>
        <span>用户提交的请求等级</span>
        <select v-model.number="model.user_request_level">
          <option :value="0">0 · 无请求</option>
          <option :value="1">1 · 少请求</option>
          <option :value="2">2 · 中等请求</option>
          <option :value="3">3 · 较多请求</option>
        </select>
      </label>
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
        <label>
          <span>管理员请求等级（留空则沿用用户等级）</span>
          <select v-model="model.admin_request_level">
            <option :value="null">不调整</option>
            <option :value="0">0 · 无请求</option>
            <option :value="1">1 · 少请求</option>
            <option :value="2">2 · 中等请求</option>
            <option :value="3">3 · 较多请求</option>
          </select>
        </label>
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
@media (max-width: 700px) {
  .form-grid.two { grid-template-columns: 1fr; }
}
</style>
