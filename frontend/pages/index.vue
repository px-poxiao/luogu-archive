<script setup lang="ts">
definePageMeta({ layout: 'default' })

type JumpType = 'article' | 'paste' | 'user'
type Announcement = {
  id: number
  title: string
  summary: string
  content: string
  published_at: string
}

const inputId = ref('')
const selectedType = ref<JumpType>('article')
const showAllAnnouncements = ref(false)
const expandedAnnouncementId = ref<number | null>(null)
const api = useApi()

const { data: announcementData } = await useAsyncData<Announcement[]>(
  'home-announcements',
  async () => {
    try {
      return await api<Announcement[]>('/site/announcements', {
        query: { limit: 10 },
      })
    } catch {
      return []
    }
  },
)

const announcements = computed(() => announcementData.value || [])

const visibleAnnouncements = computed(() => (
  showAllAnnouncements.value ? announcements.value : announcements.value.slice(0, 1)
))

const jumpTypes: Array<{
  key: JumpType
  label: string
  placeholder: string
  icon: string
}> = [
  {
    key: 'article',
    label: '文章',
    placeholder: '例如 abcdef12',
    icon: 'M4 5h16M4 10h16M4 15h10M4 20h7',
  },
  {
    key: 'paste',
    label: '剪贴板',
    placeholder: '例如 xy123abc',
    icon: 'M8 4h8l2 2v14H6V6l2-2zM9 9h6M9 13h6M9 17h4',
  },
  {
    key: 'user',
    label: '用户',
    placeholder: '例如 1',
    icon: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21c0-4.2 3.6-7 8-7s8 2.8 8 7',
  },
]

const primaryLinks = [
  {
    to: '/feed',
    title: '伪全网犇',
    meta: '“洛谷微博”',
    icon: 'M4 5h16v10H8l-4 4V5z',
  },
  {
    to: '/judgement',
    title: '陶片放逐',
    meta: '封禁公示归档',
    icon: 'M4 14l5-5 4 4 7-7M4 20h16',
  },
  {
    to: '/problem/list',
    title: '题目库',
    meta: '题解开放状态',
    icon: 'M6 4h10l4 4v12H6V4zM9 14h6M9 18h6',
  },
]

const activeType = computed(() => jumpTypes.find((item) => item.key === selectedType.value)!)

onMounted(() => {
  const saved = localStorage.getItem('quick-jump-type') as JumpType | null
  if (saved && jumpTypes.some((item) => item.key === saved)) {
    selectedType.value = saved
  }
})

function setType(t: JumpType) {
  selectedType.value = t
  if (process.client) localStorage.setItem('quick-jump-type', t)
}

function go(type?: JumpType) {
  const targetType = type || selectedType.value
  const value = inputId.value.trim()
  if (!value) return
  setType(targetType)
  navigateTo(`/${targetType}/${encodeURIComponent(value)}`)
}

function toggleAnnouncement(id: number) {
  expandedAnnouncementId.value = expandedAnnouncementId.value === id ? null : id
}

function announcementDate(value: string) {
  return value.slice(0, 10)
}

</script>

<template>
  <div class="home-page">
    <PageHero
      title="洛谷档案馆"
      subtitle="第三方存档：保存文章、剪贴板、犇犇、陶片放逐和题目信息。"
    />

    <section
      v-if="announcements.length"
      class="announcement-panel"
      aria-labelledby="announcement-title"
    >
      <header class="announcement-head">
        <div class="announcement-heading">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              d="M18 8a6 6 0 00-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <h2 id="announcement-title">站点公告</h2>
          <span>{{ announcements.length }} 条</span>
        </div>
        <button
          type="button"
          class="announcement-all"
          :aria-expanded="showAllAnnouncements"
          aria-controls="announcement-list"
          @click="showAllAnnouncements = !showAllAnnouncements"
        >
          <span>{{ showAllAnnouncements ? '收起公告' : '全部公告' }}</span>
          <svg viewBox="0 0 24 24" aria-hidden="true" :class="{ expanded: showAllAnnouncements }">
            <path
              d="M9 6l6 6-6 6"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </header>

      <div id="announcement-list" class="announcement-list">
        <article
          v-for="(announcement, index) in visibleAnnouncements"
          :key="announcement.id"
          class="announcement-item"
          :class="{ latest: index === 0 }"
        >
          <span class="announcement-dot" aria-hidden="true" />
          <button
            type="button"
            class="announcement-content"
            :aria-expanded="expandedAnnouncementId === announcement.id"
            :aria-controls="`announcement-detail-${announcement.id}`"
            @click="toggleAnnouncement(announcement.id)"
          >
            <span class="announcement-main">
              <strong>{{ announcement.title }}</strong>
              <small>{{ announcement.summary }}</small>
            </span>
            <time :datetime="announcement.published_at">
              {{ announcementDate(announcement.published_at) }}
            </time>
            <span class="announcement-toggle" title="展开公告">
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                :class="{ expanded: expandedAnnouncementId === announcement.id }"
              >
                <path
                  d="M6 9l6 6 6-6"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                />
              </svg>
            </span>
          </button>
          <p
            v-if="expandedAnnouncementId === announcement.id"
            :id="`announcement-detail-${announcement.id}`"
            class="announcement-detail"
          >
            {{ announcement.content }}
          </p>
        </article>
      </div>
    </section>

    <section class="home-board">
      <div class="jump-panel" aria-label="快速跳转">
        <div class="jump-head">
          <div>
            <h2>快速跳转</h2>
            <p>输入原站 ID，直接打开本站收录页；未收录时会触发后台抓取。</p>
          </div>
        </div>

        <div class="jump-tabs" role="tablist" aria-label="内容类型">
          <button
            v-for="item in jumpTypes"
            :key="item.key"
            type="button"
            class="jump-tab"
            :class="{ active: selectedType === item.key }"
            :aria-selected="selectedType === item.key"
            @click="setType(item.key)"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                :d="item.icon"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span>{{ item.label }}</span>
          </button>
        </div>

        <form class="jump-form" @submit.prevent="go()">
          <label class="input-wrap">
            <span>{{ activeType.label }} ID</span>
            <input
              v-model="inputId"
              :placeholder="activeType.placeholder"
              autocomplete="off"
              spellcheck="false"
            >
          </label>
          <button class="go-btn" type="submit" :disabled="!inputId.trim()">
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path
                d="M5 12h13M13 6l6 6-6 6"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
                stroke-linejoin="round"
              />
            </svg>
            <span>打开</span>
          </button>
        </form>
      </div>

      <div class="quick-grid" aria-label="快速入口">
        <NuxtLink
          v-for="link in primaryLinks"
          :key="link.to"
          :to="link.to"
          class="quick-entry"
        >
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path
              :d="link.icon"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
          <span>
            <strong>{{ link.title }}</strong>
            <small>{{ link.meta }}</small>
          </span>
        </NuxtLink>
      </div>
    </section>
  </div>
</template>

<style scoped>
.home-page {
  min-height: calc(100vh - 190px);
  padding-bottom: 44px;
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 22px;
}

.announcement-panel {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
}

.announcement-panel::before {
  position: absolute;
  inset: 0 auto 0 0;
  width: 3px;
  background: #c7922d;
  content: '';
}

.announcement-head {
  min-height: 58px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 20px 0 22px;
  border-bottom: 1px solid var(--border);
}

.announcement-heading,
.announcement-all,
.announcement-content {
  display: flex;
  align-items: center;
}

.announcement-heading {
  min-width: 0;
  gap: 10px;
}

.announcement-heading > svg {
  width: 21px;
  height: 21px;
  color: #c7922d;
  flex: 0 0 auto;
}

.announcement-heading h2 {
  margin: 0;
  font-size: 17px;
  line-height: 1.3;
}

.announcement-heading span {
  color: var(--text-muted);
  font-size: 13px;
}

.announcement-all {
  gap: 5px;
  border: 0;
  padding: 7px 0 7px 10px;
  background: transparent;
  color: var(--link);
  cursor: pointer;
  font: inherit;
  font-size: 14px;
}

.announcement-all svg,
.announcement-toggle svg {
  width: 18px;
  height: 18px;
  transition: transform 0.18s ease;
}

.announcement-all svg.expanded {
  transform: rotate(90deg);
}

.announcement-list {
  padding-left: 22px;
}

.announcement-item {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  border-top: 1px solid var(--border);
}

.announcement-item:first-child {
  border-top: 0;
}

.announcement-dot {
  position: absolute;
  top: 29px;
  left: 0;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--text-muted);
}

.announcement-item.latest .announcement-dot {
  background: var(--link);
}

.announcement-content {
  width: 100%;
  min-width: 0;
  gap: 18px;
  border: 0;
  padding: 17px 18px 17px 22px;
  background: transparent;
  color: var(--text);
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.announcement-content:hover {
  background: color-mix(in srgb, var(--link) 4%, transparent);
}

.announcement-main {
  min-width: 0;
  flex: 1;
}

.announcement-main strong,
.announcement-main small {
  display: block;
}

.announcement-main strong {
  overflow: hidden;
  font-size: 16px;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.announcement-main small {
  margin-top: 4px;
  color: var(--text-muted);
  font-size: 13px;
  line-height: 1.45;
}

.announcement-content time {
  flex: 0 0 auto;
  color: var(--text-muted);
  font-size: 13px;
}

.announcement-toggle {
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text-muted);
}

.announcement-toggle svg.expanded {
  transform: rotate(180deg);
}

.announcement-detail {
  margin: -5px 72px 18px 22px;
  padding-top: 13px;
  border-top: 1px dashed var(--border);
  color: var(--text-muted);
  font-size: 14px;
  white-space: pre-wrap;
}

.home-board {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 360px;
  gap: 22px;
  min-height: clamp(430px, calc(100vh - 330px), 680px);
}

.jump-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: clamp(24px, 3.2vw, 42px);
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.jump-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 26px;
}

.jump-head h2 {
  margin: 0;
  font-size: clamp(24px, 3vw, 36px);
  line-height: 1.15;
}

.jump-head p {
  margin: 10px 0 0;
  color: var(--text-muted);
  font-size: 16px;
}

.jump-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  margin-bottom: 22px;
}

.jump-tab {
  min-height: 46px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0 18px;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font: inherit;
  font-size: 15px;
}

.jump-tab:hover,
.jump-tab.active {
  color: var(--link);
  border-color: var(--link);
  background: color-mix(in srgb, var(--link) 8%, transparent);
}

.jump-tab svg,
.go-btn svg {
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
}

.jump-form {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 14px;
  align-items: end;
}

.input-wrap {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.input-wrap span {
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 650;
}

.input-wrap input {
  width: 100%;
  min-height: 54px;
  box-sizing: border-box;
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 8px 12px;
  background: var(--surface);
  color: var(--text);
  font: inherit;
}

.input-wrap input:focus {
  outline: 2px solid color-mix(in srgb, var(--link) 28%, transparent);
  border-color: var(--link);
}

.go-btn {
  align-self: end;
  min-height: 54px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 1px solid var(--link);
  border-radius: 6px;
  padding: 0 24px;
  background: var(--link);
  color: #fff;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
}

.go-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.quick-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}

.quick-entry {
  display: grid;
  grid-template-columns: 70px minmax(0, 1fr);
  align-items: center;
  gap: 22px;
  min-height: 0;
  padding: 26px;
  border: 1px solid var(--border);
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  transition: border-color 0.15s, background 0.15s, transform 0.12s;
}

.quick-entry:hover {
  border-color: var(--link);
  background: color-mix(in srgb, var(--link) 4%, var(--surface));
  transform: translateY(-1px);
  text-decoration: none;
}

.quick-entry svg {
  width: 70px;
  height: 70px;
  padding: 16px;
  box-sizing: border-box;
  border-radius: 8px;
  background: var(--hover);
  color: var(--link);
}

.quick-entry strong,
.quick-entry small {
  display: block;
}

.quick-entry small {
  color: var(--text-muted);
  font-size: 14px;
  margin-top: 6px;
}

.quick-entry strong {
  font-size: 20px;
  line-height: 1.25;
}

@media (max-width: 980px) {
  .home-page {
    min-height: auto;
  }

  .home-board {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    min-height: auto;
  }

  .jump-panel {
    grid-column: 1 / -1;
    min-height: 330px;
  }
}

@media (max-width: 640px) {
  .home-page {
    padding-top: 0;
  }

  .jump-panel {
    padding: 16px;
    min-height: auto;
  }

  .announcement-head {
    min-height: 54px;
    padding: 0 14px 0 17px;
  }

  .announcement-heading {
    gap: 8px;
  }

  .announcement-heading h2 {
    font-size: 16px;
  }

  .announcement-all span {
    font-size: 13px;
  }

  .announcement-list {
    padding-left: 17px;
  }

  .announcement-dot {
    top: 26px;
  }

  .announcement-content {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px 12px;
    padding: 15px 12px 15px 17px;
  }

  .announcement-main {
    grid-column: 1 / -1;
  }

  .announcement-main strong {
    white-space: normal;
  }

  .announcement-content time {
    align-self: center;
  }

  .announcement-toggle {
    width: 30px;
    height: 30px;
    justify-self: end;
  }

  .announcement-detail {
    margin: -2px 12px 15px 17px;
  }

  .jump-head {
    display: grid;
  }

  .jump-form {
    grid-template-columns: 1fr;
  }

  .home-board,
  .quick-grid {
    grid-template-columns: 1fr;
    gap: 12px;
  }

  .quick-entry {
    min-height: 96px;
    padding: 16px;
    gap: 14px;
    grid-template-columns: 48px minmax(0, 1fr);
  }

  .quick-entry svg {
    width: 48px;
    height: 48px;
    padding: 10px;
  }

  .go-btn {
    width: 100%;
  }

}
</style>
