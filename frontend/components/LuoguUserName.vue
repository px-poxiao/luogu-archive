<!--
  用户名显示（带颜色 + badge + 违规脱敏）

  props:
    user: { uid, name, color, badge, avatar }
    hidden: boolean   后端指示"当前名被隐藏"时为 true
    showBadge: boolean
    noLink: boolean   为 true 时不包链接（避免在用户主页自己链自己）
-->
<script setup lang="ts">
interface LuoguUserBrief {
  uid: number
  name: string
  color: string
  badge: string | null
  avatar: string | null
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

    <span
      v-if="showBadge && user.badge"
      class="lg-badge"
      :data-color="user.color"
    >{{ user.badge }}</span>
  </span>
</template>

<style scoped>
.lg-user-wrap {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
</style>
