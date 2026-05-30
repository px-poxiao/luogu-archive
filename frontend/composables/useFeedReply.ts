/**
 * 犇犇“回复”：把原内容按洛谷引用格式复制到剪贴板。
 *
 * 复制出的文本 = ` || @[发送者名称] : ` + 原犇犇内容
 * 洛谷引用语义：`||` 之后是被引用内容，用户粘贴后在最前面补自己的话。
 *
 * 原内容里的 @ 提及是 markdown 形式 `@[名字](/user/uid)`，复制时压成纯 `@名字`，
 * 避免粘贴出去带一长串链接语法。
 */
export function useFeedReply() {
  /** 把 `@[name](/user/123)` 压成 `@name` */
  function flattenMentions(text: string): string {
    return (text ?? '').replace(
      /@\[([^\]]{1,64})\]\(\/user\/\d+\)/g,
      (_, name) => `@${name}`,
    )
  }

  async function copyReply(content: string, senderName: string): Promise<boolean> {
    const prefix = ` || @${senderName ?? ''} : `
    const text = prefix + flattenMentions(content ?? '')
    try {
      if (import.meta.client && navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text)
        return true
      }
      // 兜底：textarea + execCommand（老浏览器 / 非安全上下文）
      if (import.meta.client) {
        const ta = document.createElement('textarea')
        ta.value = text
        ta.style.position = 'fixed'
        ta.style.opacity = '0'
        document.body.appendChild(ta)
        ta.select()
        const ok = document.execCommand('copy')
        document.body.removeChild(ta)
        return ok
      }
      return false
    } catch {
      return false
    }
  }

  return { copyReply }
}
