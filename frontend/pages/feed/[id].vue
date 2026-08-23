<script setup lang="ts">
interface FeedItem {
  id: number
  type: number
  time: string
  content_md: string
  merged_suffix_md: string | null
  merged_from_id: number | null
  merged_link_md?: string[]
  merged_image_md?: string[]
  user: { uid: number; name: string; color: string; badge: string | null; avatar: string | null } | null
}

const route = useRoute()
const api = useApi()
const { smart } = useTime()
const { render } = useMarkdown()
const feedId = String(route.params.id)
const contentRef = ref<HTMLElement | null>(null)
const completionTip = '此内容由洛谷档案馆根据回复链自动补全'

const { data: feed, pending, error } = useLazyAsyncData(
  `feed-${feedId}`,
  () => api<FeedItem>(`/feed/${feedId}`),
  { server: false },
)

function markMergedMedia(html: string, links: string[], images: string[]) {
  let marked = html
  for (const link of links) {
    const anchor = render(link).match(/<a\b[^>]*>[\s\S]*?<\/a>/i)?.[0]
    if (!anchor || !marked.includes(anchor)) continue
    marked = marked.replace(anchor, `<span class="feed-completion-wrap" tabindex="0"><span class="feed-auto-merged-link">${anchor}</span><span class="feed-completion-popover" role="tooltip">${completionTip}</span></span>`)
  }
  for (const imageMd of images) {
    const image = render(imageMd).match(/<img\b[^>]*>/i)?.[0]
    if (!image || !marked.includes(image)) continue
    marked = marked.replace(image, `<span class="feed-completion-wrap feed-auto-merged-image" tabindex="0">${image}<span class="feed-completion-popover" role="tooltip">${completionTip}</span></span>`)
  }
  return marked
}

function renderMergedSuffix(content: string, mergedSuffix: string) {
  const prefix = content.slice(0, Math.max(0, content.length - mergedSuffix.length))
  const prefixHtml = render(prefix)
  const suffixHtml = render(mergedSuffix)
  const suffixParagraph = suffixHtml.match(/^<p>([\s\S]*)<\/p>\s*$/)
  if (!mergedSuffix.startsWith('\n') && suffixParagraph && /<\/p>\s*$/.test(prefixHtml)) {
    const marked = `<span class="feed-completion-wrap" tabindex="0"><span class="feed-auto-merged">${suffixParagraph[1]}</span><span class="feed-completion-popover" role="tooltip">${completionTip}</span></span>`
    return prefixHtml.replace(/<\/p>\s*$/, `${marked}</p>`)
  }
  return prefixHtml + `<div class="feed-completion-wrap feed-completion-block" tabindex="0"><div class="feed-auto-merged">${suffixHtml}</div><span class="feed-completion-popover" role="tooltip">${completionTip}</span></div>`
}

function feedHtml(item: FeedItem) {
  let html = item.merged_suffix_md
    ? renderMergedSuffix(item.content_md, item.merged_suffix_md)
    : render(item.content_md)
  html = markMergedMedia(html, item.merged_link_md || [], item.merged_image_md || [])
  return html
}

useCopyCode(contentRef)
</script>

<template>
  <div class="feed-detail">
    <LoadingPanel v-if="pending" title="loading……" text="" />
    <div v-else-if="error" class="error-box">
      <h2>{{ error.data?.message || '犇犇加载失败' }}</h2>
    </div>
    <article v-else-if="feed" class="feed-item">
      <NuxtLink v-if="feed.user" :to="`/user/${feed.user.uid}`" class="avatar-link">
        <img v-if="feed.user.avatar" :src="feed.user.avatar" alt="" class="avatar">
        <div v-else class="avatar avatar-fallback" :data-color="feed.user.color">{{ (feed.user.name || '?').charAt(0).toUpperCase() }}</div>
      </NuxtLink>
      <div v-else class="avatar avatar-fallback" data-color="Gray">?</div>
      <div class="body">
        <header class="meta">
          <LuoguUserName :user="feed.user" show-badge />
          <span class="time">{{ smart(feed.time) }}</span>
        </header>
        <div ref="contentRef" class="lg-content content" v-html="feedHtml(feed)" />
        <footer class="feed-foot">
          <NuxtLink :to="`/feed/${feed.id}`" class="feed-id">#{{ feed.id }}</NuxtLink>
          <FeedReplyButton :content="feed.content_md" :sender-name="feed.user?.name" />
        </footer>
      </div>
    </article>
  </div>
</template>

<style scoped>
.feed-detail{max-width:100%;padding-top:4px}.feed-item{display:flex;gap:14px;padding:18px 20px;border:1px solid var(--border);border-radius:8px;background:var(--surface)}
.avatar-link{flex-shrink:0;text-decoration:none}.avatar{display:block;width:48px;height:48px;border-radius:50%;object-fit:cover;background:var(--bg)}.avatar-fallback{display:flex;align-items:center;justify-content:center;color:#fff;font-size:18px;font-weight:600;background:var(--lg-gray)}
.avatar-fallback[data-color="Blue"]{background:var(--lg-blue)}.avatar-fallback[data-color="Green"]{background:var(--lg-green)}.avatar-fallback[data-color="Orange"]{background:var(--lg-orange)}.avatar-fallback[data-color="Red"]{background:var(--lg-red)}.avatar-fallback[data-color="Purple"]{background:var(--lg-purple)}.avatar-fallback[data-color="Cyan"]{background:var(--lg-cyan)}.avatar-fallback[data-color="Black"]{background:var(--lg-black)}.avatar-fallback[data-color="Cheater"]{background:var(--lg-cheater-tag)}
.body{min-width:0;flex:1;overflow-wrap:anywhere;word-break:break-word}.meta{display:flex;align-items:baseline;flex-wrap:wrap;gap:10px;margin-bottom:8px}.time{color:var(--text-muted);font-size:12px}.content{font-size:15px;line-height:1.65;overflow-wrap:anywhere;word-break:break-word}.content :deep(img){max-width:100%;height:auto}.feed-foot{display:flex;align-items:center;gap:10px;margin-top:10px}.feed-id{color:var(--text-muted);font-family:ui-monospace,"SF Mono",Consolas,monospace;font-size:11px;opacity:.55}
.content :deep(.feed-completion-wrap){position:relative;display:inline;cursor:help;outline:none}.content :deep(.feed-completion-block){display:block;width:fit-content;max-width:100%}.content :deep(.feed-auto-merged),.content :deep(.feed-auto-merged-link),.content :deep(.feed-auto-merged-link a){text-decoration-line:underline;text-decoration-color:#7db9e8;text-decoration-thickness:2px;text-underline-offset:3px}.content :deep(.feed-auto-merged-image){display:inline-block;max-width:100%;box-shadow:0 2px 0 #7db9e8}.content :deep(.feed-auto-merged-image img){display:block}.content :deep(.feed-completion-popover){position:absolute;z-index:30;top:calc(100% + 9px);left:50%;display:none;width:max-content;max-width:280px;padding:8px 10px;transform:translateX(-50%);border:1px solid var(--border);border-radius:5px;background:var(--surface);color:var(--text);box-shadow:0 8px 22px rgba(0,0,0,.16);font-size:12px;line-height:1.55;white-space:normal;pointer-events:none}.content :deep(.feed-completion-wrap:hover>.feed-completion-popover),.content :deep(.feed-completion-wrap:focus-within>.feed-completion-popover){display:block}
.error-box{padding:28px;border:1px solid var(--border);border-radius:8px;background:var(--surface);text-align:center}@media(max-width:768px){.feed-item{gap:11px;padding:14px}.avatar{width:42px;height:42px}}
</style>
