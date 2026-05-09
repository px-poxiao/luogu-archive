<script setup lang="ts">
definePageMeta({ layout: 'admin' })

const admin = useAdminStore()
const api = useAdminApi()

const stats = ref<any>(null)
const loading = ref(true)

onMounted(async () => {
  if (!admin.isLoggedIn) {
    navigateTo('/admin/login')
    return
  }
  try {
    stats.value = await api('/admin/stats')
  } catch (e: any) {
    if (e?.status === 401) navigateTo('/admin/login')
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-if="loading" class="loading">加载中...</div>
  <div v-else-if="stats">
    <h1>爬虫健康看板（近 24 小时）</h1>

    <section class="grid">
      <div class="card">
        <h3>按任务状态</h3>
        <ul>
          <li v-for="(v, k) in stats.by_status" :key="k">
            <span>{{ k }}</span> <b>{{ v }}</b>
          </li>
        </ul>
      </div>
      <div class="card">
        <h3>按任务类型</h3>
        <ul>
          <li v-for="(v, k) in stats.by_task_type" :key="k">
            <span>{{ k }}</span> <b>{{ v }}</b>
          </li>
        </ul>
      </div>
      <div class="card">
        <h3>队列长度（待消费）</h3>
        <ul>
          <li v-for="(v, k) in stats.queue_lengths" :key="k">
            <span>{{ k }}</span> <b>{{ v }}</b>
          </li>
        </ul>
      </div>
    </section>

    <p class="muted">数据刷新时间：{{ stats.now }}</p>
  </div>
</template>

<style scoped>
.loading { padding: 30px; color: var(--text-muted); text-align: center; }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 16px;
  margin: 20px 0;
}
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 16px;
}
.card h3 { margin-top: 0; }
.card ul { list-style: none; padding: 0; }
.card li {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  border-bottom: 1px dashed var(--border);
}
.muted { color: var(--text-muted); font-size: 13px; }
</style>
