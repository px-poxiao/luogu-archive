<script setup lang="ts">
const api = useApi()

interface JudgementGroup {
  group_key: string
  reason: string
  revoked_permission: number
  added_permission: number
  time_start: string
  time_end: string
  users: Array<{ uid: number; name: string; color: string; badge: string | null; avatar: string | null }>
  count: number
}

const { data } = await useAsyncData('judgement', () =>
  api<JudgementGroup[]>('/judgement?limit=200'),
)

const expanded = ref<Set<string>>(new Set())
function toggle(k: string) {
  if (expanded.value.has(k)) expanded.value.delete(k)
  else expanded.value.add(k)
}
</script>

<template>
  <div>
    <OriginBanner
      origin-url="https://www.luogu.com.cn/judgement"
      content-type="judgement"
      content-id="all"
    />
    <h1>陶片放逐（封号公示存档）</h1>

    <ul v-if="data && data.length" class="list">
      <li v-for="g in data" :key="g.group_key" :class="{ expanded: expanded.has(g.group_key) }">
        <div class="head" @click="toggle(g.group_key)">
          <span class="count" v-if="g.count > 1">[{{ g.count }} 人]</span>
          <span class="reason">{{ g.reason }}</span>
          <span class="time">{{ g.time_end }}</span>
        </div>

        <div v-if="g.count === 1" class="users">
          <LuoguUserName :user="g.users[0]" show-badge />
        </div>
        <div v-else-if="expanded.has(g.group_key)" class="users">
          <LuoguUserName
            v-for="u in g.users"
            :key="u.uid"
            :user="u"
            class="user-chip"
          />
        </div>
      </li>
    </ul>
    <p v-else class="empty">暂无数据</p>
  </div>
</template>

<style scoped>
.list {
  list-style: none;
  padding: 0;
}
.list li {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 8px;
  padding: 12px 16px;
}
.head {
  display: flex;
  gap: 12px;
  align-items: center;
  cursor: pointer;
  flex-wrap: wrap;
}
.count {
  background: var(--lg-orange);
  color: white;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 12px;
}
.reason {
  flex: 1;
  min-width: 0;
}
.time {
  color: var(--text-muted);
  font-size: 13px;
}
.users {
  margin-top: 10px;
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.user-chip {
  background: var(--hover);
  padding: 3px 10px;
  border-radius: 12px;
}
.empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px;
}
</style>
