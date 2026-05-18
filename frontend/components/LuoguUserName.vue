<!--
  用户名显示（带颜色 + 称号 + 钩子 + 气球 + 违规脱敏）

  props:
    user: { uid, name, color, badge, avatar, ccf_level?, xcpc_level?, is_admin? }
    hidden: boolean   后端指示"当前名被隐藏"时为 true
    showBadge: boolean   是否显示称号 / 钩子 / 气球
    noLink: boolean   为 true 时不包链接（避免在用户主页自己链自己）

  显示顺序（与洛谷一致）：用户名 → 称号 → 钩子 → 气球
  显示规则（钩子气球颜色规则相同）：
    钩子 ccf_level：0-2 不显示，3-5 绿，6-7 蓝，8+ 金
    气球 xcpc_level：0-2 不显示，3-5 绿，6-7 蓝，8+ 金
    称号 badge 颜色 = 用户名颜色（背景填充 + 白字）
-->
<script setup lang="ts">
interface LuoguUserBrief {
  uid: number
  name: string
  color: string
  badge: string | null
  avatar: string | null
  ccf_level?: number
  xcpc_level?: number
  is_admin?: boolean
}

const props = defineProps<{
  user: LuoguUserBrief | null | undefined
  hidden?: boolean
  showBadge?: boolean
  noLink?: boolean
}>()

const displayName = computed(() => {
  if (!props.user) return ''
  return props.hidden ? `UID ${props.user.uid}` : props.user.name
})

function levelTier(lv: number | undefined): 'green' | 'blue' | 'top' | null {
  if (!lv || lv < 3) return null
  if (lv <= 5) return 'green'
  if (lv <= 7) return 'blue'
  return 'top'
}

const ccfTier = computed(() => levelTier(props.user?.ccf_level))
const xcpcTier = computed(() => levelTier(props.user?.xcpc_level))
</script>

<template>
  <span v-if="user" class="lg-user-wrap">
    <NuxtLink
      v-if="!noLink"
      :to="`/user/${user.uid}`"
      class="lg-name"
      :data-color="user.color"
      :data-hidden="hidden ? '1' : undefined"
    >{{ displayName }}</NuxtLink>
    <span
      v-else
      class="lg-name"
      :data-color="user.color"
      :data-hidden="hidden ? '1' : undefined"
    >{{ displayName }}</span>

    <template v-if="showBadge">
      <!-- 称号：背景为用户名颜色，文字白色 -->
      <span
        v-if="user.badge"
        class="lg-badge"
        :data-color="user.color"
        :title="user.is_admin ? '管理员' : ''"
      >{{ user.badge }}</span>

      <!-- 钩子（OI 认证）：fa-badge-check（双色：彩盾 + 白勾） -->
      <span
        v-if="ccfTier"
        class="lg-mark lg-hook"
        :data-tier="ccfTier"
        :title="`OI 认证等级 ${user.ccf_level}`"
        aria-label="钩子"
      >
        <svg viewBox="0 0 512 512" width="14" height="14" aria-hidden="true">
          <!-- 外层盾牌：tier 色 -->
          <path
            fill="currentColor"
            d="M0 256C0 292.8 20.7 324.8 51.1 340.9 41 373.8 49 411 75 437s63.3 34 96.1 23.9C187.2 491.3 219.2 512 256 512s68.8-20.7 84.9-51.1C373.8 471 411 463 437 437s34-63.3 23.9-96.1C491.3 324.8 512 292.8 512 256s-20.7-68.8-51.1-84.9C471 138.2 463 101 437 75s-63.3-34-96.1-23.9C324.8 20.7 292.8 0 256 0s-68.8 20.7-84.9 51.1C138.2 41 101 49 75 75s-34 63.3-23.9 96.1C20.7 187.2 0 219.2 0 256zm152.3 41.6c-9.2-9.5-9-24.7 .6-33.9 9.5-9.2 24.7-8.9 33.9 .6l35.8 37 106.1-145.8c7.8-10.7 22.8-13.1 33.5-5.3 10.7 7.8 13.1 22.8 5.3 33.5L244.7 352.7c-4.2 5.7-10.7 9.4-17.8 9.8-7.1 .5-14-2.2-18.9-7.3l-55.7-57.6z"
          />
          <!-- 内层钩子：白色 -->
          <path
            fill="#fff"
            d="M328.7 155.5c7.8-10.7 22.8-13.1 33.5-5.3 10.7 7.8 13.1 22.8 5.3 33.5L244.7 352.7c-4.2 5.7-10.7 9.4-17.8 9.8-7.1 .5-14-2.2-18.9-7.3l-55.7-57.6c-9.2-9.5-9-24.7 .6-33.9 9.5-9.2 24.7-8.9 33.9 .6l35.8 37 106.1-145.8z"
          />
        </svg>
      </span>

      <!-- 气球（XCPC 认证）：fa-balloon（双色：彩气球 + 白高光） -->
      <span
        v-if="xcpcTier"
        class="lg-mark lg-balloon"
        :data-tier="xcpcTier"
        :title="`XCPC 认证等级 ${user.xcpc_level}`"
        aria-label="气球"
      >
        <svg viewBox="0 0 384 512" width="11" height="14" aria-hidden="true">
          <!-- 气球本体：tier 色 -->
          <path
            fill="currentColor"
            d="M0 192C0 86 86 0 192 0S384 86 384 192c0 128-160 240-160 240l27.9 41.8c2.7 4 4.1 8.8 4.1 13.6 0 13.6-11 24.6-24.6 24.6l-78.9 0c-13.6 0-24.6-11-24.6-24.6 0-4.8 1.4-9.6 4.1-13.6L160 432S0 320 0 192zm104-16c0-39.8 32.2-72 72-72 13.3 0 24-10.7 24-24s-10.7-24-24-24c-66.3 0-120 53.7-120 120 0 13.3 10.7 24 24 24s24-10.7 24-24z"
          />
          <!-- 高光弧：白色 -->
          <path
            fill="#fff"
            d="M56 176c0 13.3 10.7 24 24 24s24-10.7 24-24c0-39.8 32.2-72 72-72 13.3 0 24-10.7 24-24s-10.7-24-24-24C109.7 56 56 109.7 56 176z"
          />
        </svg>
      </span>
    </template>
  </span>
</template>

<style scoped>
.lg-user-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  vertical-align: middle;
}

/* 钩子 / 气球：以 currentColor 上色 */
.lg-mark {
  display: inline-flex;
  align-items: center;
  line-height: 1;
}
.lg-mark[data-tier="green"] { color: var(--lg-green); }
.lg-mark[data-tier="blue"]  { color: var(--lg-blue); }

/* 钩子 / 气球 8+ 都是金 —— 规则跟洛谷一致：3-5 绿、6-7 蓝、8+ 金 */
.lg-mark[data-tier="top"] { color: #f5b400; }
</style>

