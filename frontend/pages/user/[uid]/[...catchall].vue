<!--
  /user/<uid>/* 一律重定向到 /user/<uid>。
  老链接、错敲的子路径都 fold 回去，避免 404。
-->
<script setup lang="ts">
const route = useRoute()
const uid = route.params.uid as string
// SSR 阶段返回 301，CSR 也会随这个 navigateTo 跳走
await navigateTo(`/user/${uid}`, { redirectCode: 301 })
</script>

<template>
  <div />
</template>
