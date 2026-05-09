/**
 * Markdown 渲染（前端）
 *
 * 后端返回原 Markdown 字符串，前端渲染成 HTML + KaTeX 公式。
 * 洛谷专有语法（@提及 / 引用回复 / BBCode）由后端渲染管线生成 HTML 时已经处理。
 * 为简化，这里前端再完整渲染一次也能工作（后端的 HTML 渲染主要给搜索和 RSS 用）。
 */
import MarkdownIt from 'markdown-it'
// @ts-ignore - markdown-it-katex 没有类型
import mdKatex from 'markdown-it-katex'

let _md: MarkdownIt | null = null

function build(): MarkdownIt {
  const md = new MarkdownIt({
    html: false,
    breaks: true,
    linkify: true,
    typographer: false,
  })
  md.use(mdKatex, { throwOnError: false, errorColor: '#f44' })

  // 洛谷 @[name](/user/uid) 简单渲染为带颜色占位的 link（后续可增强）
  const mentionRe = /@\[([^\]]{1,64})\]\(\/user\/(\d+)\)/g
  const origText = md.renderer.rules.text || ((tokens, idx) => tokens[idx].content)
  md.renderer.rules.text = (tokens, idx, opts, env, self) => {
    const content = tokens[idx].content
    if (!mentionRe.test(content)) {
      return origText.call(self, tokens, idx, opts, env, self)
    }
    return content.replace(
      mentionRe,
      (_, name, uid) =>
        `<a class="lg-user-mention" href="/user/${uid}" data-uid="${uid}">@${md.utils.escapeHtml(name)}</a>`,
    )
  }

  // 链接改写（前端双保险）
  const origLinkOpen = md.renderer.rules.link_open ||
    ((tokens, idx, opts, _env, self) => self.renderToken(tokens, idx, opts))
  md.renderer.rules.link_open = (tokens, idx, opts, env, self) => {
    const hrefIdx = tokens[idx].attrIndex('href')
    if (hrefIdx >= 0) {
      const href = tokens[idx].attrs![hrefIdx][1]
      const rewritten = rewriteLuoguHref(href)
      if (rewritten !== href) {
        tokens[idx].attrs![hrefIdx][1] = rewritten
      } else if (/^https?:\/\//.test(href)) {
        tokens[idx].attrSet('rel', 'noopener noreferrer')
        tokens[idx].attrSet('target', '_blank')
      }
    }
    return origLinkOpen(tokens, idx, opts, env, self)
  }

  return md
}

function rewriteLuoguHref(href: string): string {
  try {
    const u = new URL(href)
    const hosts = [
      'www.luogu.com.cn', 'luogu.com.cn',
      'www.luogu.com', 'luogu.com',
      'www.luogu.org', 'luogu.org',
    ]
    if (!hosts.includes(u.hostname.toLowerCase())) return href
    const allowed = ['/article/', '/paste/', '/user/', '/problem/', '/judgement', '/feed']
    if (allowed.some(p => u.pathname.startsWith(p)) || u.pathname === '/') {
      return u.pathname + u.search + u.hash
    }
  } catch {
    /* ignore */
  }
  return href
}

export function useMarkdown() {
  if (!_md) _md = build()
  const render = (src: string) => _md!.render(src || '')
  return { render }
}
