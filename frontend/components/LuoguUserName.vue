<!--
  用户名显示（带颜色 + badge + 违规脱敏）

  props:
    user: { uid, name, color, badge, avatar }
    hidden: boolean   后端指示"当前名被隐藏"时为 true
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
  <span v-if="user">
    <component
      :is="noLink ? 'span' : NuxtLink"
      v-if="!noLink"
      :to="`/user/${user.uid}`"
      class="lg-name"
      :data-color="user.color"
      :data-hidden="hidden ? '1' : undefined"
    >{{ displayName }}</component>
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
