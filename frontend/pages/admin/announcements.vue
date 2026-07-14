<script setup lang="ts">
definePageMeta({ layout: 'admin' })

type Announcement = {
  id: number
  title: string
  summary: string
  content: string
  is_published: boolean
  published_at: string | null
  created_at: string
  updated_at: string
}

type AnnouncementForm = {
  title: string
  summary: string
  content: string
  is_published: boolean
}

const admin = useAdminStore()
const api = useAdminApi()
const announcements = ref<Announcement[]>([])
const loading = ref(true)
const saving = ref(false)
const editingId = ref<number | null>(null)
const form = ref<AnnouncementForm>(emptyForm())

function emptyForm(): AnnouncementForm {
  return {
    title: '',
    summary: '',
    content: '',
    is_published: true,
  }
}

async function load() {
  loading.value = true
  try {
    announcements.value = await api<Announcement[]>('/admin/announcements')
  } catch (error: any) {
    if (error?.status === 401 || error?.statusCode === 401) {
      admin.clear()
      await navigateTo('/admin/login')
      return
    }
    alert(error?.data?.message || '公告加载失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  if (!admin.isLoggedIn) {
    navigateTo('/admin/login')
    return
  }
  load()
})

function edit(item: Announcement) {
  editingId.value = item.id
  form.value = {
    title: item.title,
    summary: item.summary,
    content: item.content,
    is_published: item.is_published,
  }
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

function resetForm() {
  editingId.value = null
  form.value = emptyForm()
}

async function save() {
  const body = {
    title: form.value.title.trim(),
    summary: form.value.summary.trim(),
    content: form.value.content.trim(),
    is_published: form.value.is_published,
  }
  if (!body.title || !body.summary || !body.content) {
    alert('请填写标题、摘要和正文')
    return
  }

  saving.value = true
  try {
    if (editingId.value === null) {
      await api('/admin/announcements', { method: 'POST', body })
    } else {
      await api(`/admin/announcements/${editingId.value}`, { method: 'PUT', body })
    }
    resetForm()
    await load()
  } catch (error: any) {
    alert(error?.data?.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function togglePublished(item: Announcement) {
  const action = item.is_published ? 'unpublish' : 'publish'
  try {
    await api(`/admin/announcements/${item.id}/${action}`, { method: 'POST' })
    await load()
  } catch (error: any) {
    alert(error?.data?.message || '操作失败')
  }
}

async function remove(item: Announcement) {
  if (!window.confirm(`确定彻底删除公告“${item.title}”吗？`)) return
  try {
    await api(`/admin/announcements/${item.id}`, { method: 'DELETE' })
    if (editingId.value === item.id) resetForm()
    await load()
  } catch (error: any) {
    alert(error?.data?.message || '删除失败')
  }
}

function formatTime(value: string | null) {
  if (!value) return '-'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}
</script>

<template>
  <div class="announcement-admin">
    <div class="page-head">
      <div>
        <h1>站点公告</h1>
        <p>首页仅显示已发布公告，按最近发布时间排序。</p>
      </div>
      <button v-if="editingId !== null" type="button" @click="resetForm">
        取消编辑
      </button>
    </div>

    <section class="editor" aria-labelledby="announcement-editor-title">
      <h2 id="announcement-editor-title">
        {{ editingId === null ? '新建公告' : `编辑公告 #${editingId}` }}
      </h2>
      <div class="field-grid">
        <label>
          <span>标题</span>
          <input v-model="form.title" maxlength="200" placeholder="公告标题">
        </label>
        <label>
          <span>首页摘要</span>
          <input v-model="form.summary" maxlength="500" placeholder="一行说明公告内容">
        </label>
        <label class="content-field">
          <span>正文</span>
          <textarea v-model="form.content" maxlength="20000" rows="7" placeholder="公告完整内容" />
        </label>
      </div>
      <div class="editor-actions">
        <label class="publish-check">
          <input v-model="form.is_published" type="checkbox">
          <span>保存后立即发布到首页</span>
        </label>
        <button class="primary" type="button" :disabled="saving" @click="save">
          {{ saving ? '保存中...' : editingId === null ? '保存公告' : '更新公告' }}
        </button>
      </div>
    </section>

    <section class="announcement-list" aria-labelledby="announcement-list-title">
      <div class="list-head">
        <h2 id="announcement-list-title">全部公告</h2>
        <span>{{ announcements.length }} 条</span>
      </div>

      <div v-if="loading" class="empty">加载中...</div>
      <div v-else-if="!announcements.length" class="empty">
        暂无公告
      </div>
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>状态</th>
              <th>公告</th>
              <th>发布时间</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in announcements" :key="item.id">
              <td>
                <span class="status" :class="item.is_published ? 'published' : 'draft'">
                  {{ item.is_published ? '已发布' : '草稿' }}
                </span>
              </td>
              <td class="announcement-copy">
                <strong>{{ item.title }}</strong>
                <small>{{ item.summary }}</small>
              </td>
              <td class="time">{{ formatTime(item.published_at) }}</td>
              <td class="time">{{ formatTime(item.updated_at) }}</td>
              <td>
                <div class="row-actions">
                  <button type="button" @click="edit(item)">编辑</button>
                  <button type="button" @click="togglePublished(item)">
                    {{ item.is_published ? '撤下' : '发布' }}
                  </button>
                  <button class="danger" type="button" @click="remove(item)">删除</button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<style scoped>
.announcement-admin { display: grid; gap: 22px; }
.page-head,
.list-head,
.editor-actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.page-head h1,
.editor h2,
.list-head h2 { margin: 0; }
.page-head p {
  margin: 4px 0 0;
  color: var(--text-muted);
}
.editor,
.announcement-list {
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}
.editor { padding: 20px; }
.editor h2 { margin-bottom: 16px; font-size: 19px; }
.field-grid { display: grid; gap: 14px; }
.field-grid label { display: grid; gap: 5px; }
.field-grid label > span {
  color: var(--text-muted);
  font-size: 13px;
  font-weight: 600;
}
input,
textarea {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 9px 11px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}
textarea { resize: vertical; min-height: 150px; }
input:focus,
textarea:focus {
  outline: 2px solid color-mix(in srgb, var(--link) 25%, transparent);
  border-color: var(--link);
}
.editor-actions { margin-top: 16px; }
.publish-check {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.publish-check input { width: 16px; height: 16px; }
button {
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 7px 12px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
}
button:hover { border-color: var(--link); }
button:disabled { cursor: not-allowed; opacity: 0.55; }
button.primary {
  border-color: var(--link);
  background: var(--link);
  color: #fff;
  font-weight: 700;
}
button.danger { color: var(--lg-red); }
.list-head {
  min-height: 54px;
  padding: 0 16px;
  border-bottom: 1px solid var(--border);
}
.list-head h2 { font-size: 18px; }
.list-head span,
.time { color: var(--text-muted); font-size: 13px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th,
td {
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
tbody tr:last-child td { border-bottom: 0; }
th {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 650;
  white-space: nowrap;
}
.status {
  display: inline-block;
  min-width: 48px;
  border-radius: 3px;
  padding: 2px 7px;
  text-align: center;
  font-size: 12px;
}
.status.published {
  background: color-mix(in srgb, var(--lg-green) 16%, transparent);
  color: var(--lg-green);
}
.status.draft {
  background: var(--hover);
  color: var(--text-muted);
}
.announcement-copy { min-width: 280px; }
.announcement-copy strong,
.announcement-copy small { display: block; }
.announcement-copy small {
  max-width: 520px;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 13px;
}
.row-actions { display: flex; gap: 7px; white-space: nowrap; }
.empty {
  padding: 36px 16px;
  color: var(--text-muted);
  text-align: center;
}
@media (max-width: 640px) {
  .page-head,
  .editor-actions { align-items: stretch; flex-direction: column; }
  .page-head button,
  .editor-actions button { width: 100%; }
  .publish-check { min-height: 38px; }
}
</style>
