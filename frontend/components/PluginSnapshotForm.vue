<script setup lang="ts">
import type { PluginSnapshot, PluginTag } from '~/types/plugin'
import {
  PLUGIN_BINARY_ALLOWED_SUFFIXES,
  PLUGIN_BINARY_MAX_BYTES,
  PLUGIN_CODE_COPY_MAX_BYTES,
  base64ByteLength,
  fileToBase64,
  formatBytes,
  isBinaryCode,
} from '~/utils/pluginCode'

const model = defineModel<PluginSnapshot>({ required: true })
const props = defineProps<{ tags: PluginTag[] }>()

const binaryMode = computed(() => isBinaryCode(model.value.code_encoding))
const pickedFileName = ref('')
const fileError = ref('')
const reading = ref(false)

// 二进制模式下 code 是 base64，体积必须按解码后的字节算。
const codeBytes = computed(() => (binaryMode.value
  ? base64ByteLength(model.value.code || '')
  : new TextEncoder().encode(model.value.code || '').length))
const codeTooLarge = computed(() => codeBytes.value
  > (binaryMode.value ? PLUGIN_BINARY_MAX_BYTES : 5 * 1024 * 1024))
const copyRestricted = computed(() => !binaryMode.value && codeBytes.value > PLUGIN_CODE_COPY_MAX_BYTES)
const codeSizeText = computed(() => formatBytes(codeBytes.value))
const sizeLimitText = computed(() => (binaryMode.value ? formatBytes(PLUGIN_BINARY_MAX_BYTES) : '5 MiB'))

function switchToText() {
  model.value.code = ''
  model.value.code_encoding = 'text'
  pickedFileName.value = ''
  fileError.value = ''
}

function switchToBinary() {
  model.value.code = ''
  model.value.code_encoding = 'base64'
  pickedFileName.value = ''
  fileError.value = ''
}

async function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  fileError.value = ''
  const dot = file.name.lastIndexOf('.')
  const suffix = dot >= 0 ? file.name.slice(dot).toLowerCase() : ''
  if (!PLUGIN_BINARY_ALLOWED_SUFFIXES.includes(suffix)) {
    fileError.value = `只支持 ${PLUGIN_BINARY_ALLOWED_SUFFIXES.join(' / ')} 格式`
    input.value = ''
    return
  }
  if (file.size > PLUGIN_BINARY_MAX_BYTES) {
    fileError.value = `文件不能超过 ${formatBytes(PLUGIN_BINARY_MAX_BYTES)}`
    input.value = ''
    return
  }
  reading.value = true
  try {
    model.value.code = await fileToBase64(file)
    model.value.code_encoding = 'base64'
    model.value.download_filename = file.name
    pickedFileName.value = file.name
  } catch {
    fileError.value = '读取文件失败，请重试'
  } finally {
    reading.value = false
  }
}

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
        <h2>插件内容</h2>
        <span :class="{ danger: codeTooLarge }">{{ codeSizeText }} / {{ sizeLimitText }}</span>
      </div>
      <fieldset>
        <legend>内容形式</legend>
        <div class="choice-row">
          <label class="check-option">
            <input type="radio" :checked="!binaryMode" @change="switchToText">
            <span>文本代码</span>
          </label>
          <label class="check-option">
            <input type="radio" :checked="binaryMode" @change="switchToBinary">
            <span>二进制文件</span>
          </label>
        </div>
      </fieldset>
      <label class="version-field">
        <span>版本号</span>
        <input v-model.trim="model.version" maxlength="64" placeholder="例如 1.0.0" required>
      </label>

      <template v-if="!binaryMode">
        <label>
          <span>代码内容</span>
          <textarea v-model="model.code" class="code-input" rows="18" spellcheck="false" required />
        </label>
        <p v-if="copyRestricted" class="copy-limit-note">
          完整代码超过 100 KiB，发布后公开页面将禁用复制，只允许下载。
        </p>
      </template>

      <template v-else>
        <label class="file-field">
          <span>插件文件</span>
          <input type="file" accept=".zip,.crx,.xpi" :disabled="reading" @change="onFileChange">
        </label>
        <p class="field-help">
          支持 {{ PLUGIN_BINARY_ALLOWED_SUFFIXES.join(' / ') }}，单个文件不超过
          {{ formatBytes(PLUGIN_BINARY_MAX_BYTES) }}。二进制内容无法在线预览，管理员审核时会下载检查。
        </p>
        <p v-if="reading" class="file-picked">正在读取文件……</p>
        <p v-else-if="pickedFileName" class="file-picked">已选择：{{ pickedFileName }}（{{ codeSizeText }}）</p>
        <p v-else-if="model.code" class="file-picked">
          已载入当前版本文件：{{ model.download_filename }}（{{ codeSizeText }}），重新选择文件即可替换。
        </p>
        <p v-if="fileError" class="file-error">{{ fileError }}</p>
      </template>

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
.copy-limit-note { margin: -4px 0 0; padding: 9px 11px; border-left: 4px solid var(--lg-red); background: color-mix(in srgb, var(--lg-red) 8%, var(--surface)); color: var(--text-muted); font-size: 13px; }
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
.file-field input[type="file"] { padding: 8px 10px; cursor: pointer; }
.file-picked { margin: -4px 0 0; color: var(--text-muted); font-size: 13px; }
.file-error { margin: -4px 0 0; padding: 9px 11px; border-left: 4px solid var(--lg-red); background: color-mix(in srgb, var(--lg-red) 8%, var(--surface)); color: var(--lg-red); font-size: 13px; }
@media (max-width: 700px) {
  .form-grid.two { grid-template-columns: 1fr; }
}
</style>
