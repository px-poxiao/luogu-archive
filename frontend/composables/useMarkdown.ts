/**
 * Markdown 渲染（前端）
 *
 * 后端返回原 Markdown 字符串，前端渲染成 HTML + KaTeX 公式。
 * 洛谷专有语法在这里做前端兜底渲染。
 */
import MarkdownIt from 'markdown-it'
// @ts-ignore - @vscode/markdown-it-katex 没有类型
import mdKatex from '@vscode/markdown-it-katex'

let _md: MarkdownIt | null = null

function normalizeDisplayMath(src: string): string {
  const lines = (src || '').replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  const out: string[] = []
  let inFence = false
  let fenceMarker = ''
  let inMath = false

  for (const raw of lines) {
    const fence = raw.match(/^(\s*)(`{3,}|~{3,})/)
    if (fence) {
      const marker = fence[2]
      if (!inFence) {
        inFence = true
        fenceMarker = marker
      } else if (marker.startsWith(fenceMarker)) {
        inFence = false
        fenceMarker = ''
      }
      out.push(raw)
      continue
    }

    if (inFence) {
      out.push(raw)
      continue
    }

    if (inMath) {
      const close = raw.indexOf('$$')
      if (close >= 0) {
        const before = raw.slice(0, close).trimEnd()
        const after = raw.slice(close + 2).trim()
        if (before) out.push(before)
        out.push('$$')
        if (after) out.push(after)
        inMath = false
      } else {
        out.push(raw)
      }
      continue
    }

    const open = raw.match(/^(\s*)\$\$(.*)$/)
    if (!open) {
      out.push(raw)
      continue
    }

    const indent = open[1]
    const rest = open[2]
    const close = rest.indexOf('$$')
    out.push(`${indent}$$`)
    if (close >= 0) {
      const body = rest.slice(0, close).trim()
      const after = rest.slice(close + 2).trim()
      if (body) out.push(body)
      out.push(`${indent}$$`)
      if (after) out.push(after)
    } else {
      if (rest.trim()) out.push(rest.trimEnd())
      inMath = true
    }
  }

  if (inMath) out.push('$$')
  return out.join('\n')
}

/**
 * 洛谷 container 语法（官方手册）：
 *
 *   :::info[标题]{open}     —— 折叠框，四种类型：info / success / warning / error
 *   :::info[标题]            —— 不带 {open} 则默认折叠
 *   :::epigraph[——署名]     —— 右对齐引言，非折叠
 *   :::align{center}         —— 居中块
 *   :::align{right}          —— 右对齐块
 *   :::
 *
 * 嵌套：最内层用 3 个冒号，每往外一层多一个冒号（开关配对同数量）。
 *   ::::info[外]
 *   :::info[内]
 *   :::
 *   ::::
 *
 * 标题支持行内 LaTeX 等正常 inline 解析。
 */
type Kind = 'info' | 'success' | 'warning' | 'error' | 'epigraph' | 'align'

const FOLD_KINDS = new Set<Kind>(['info', 'success', 'warning', 'error'])

/** 解析容器开头：`::::info[标题]{open}` 之类，失败返回 null */
function parseOpener(line: string): {
  fence: number
  kind: Kind
  title: string
  options: string
} | null {
  // 至少 3 个冒号，全行以冒号开头
  const m = line.match(/^(:{3,})\s*([a-zA-Z][a-zA-Z0-9_-]*)\s*(\[[^\]]*\])?\s*(\{[^}]*\})?\s*$/)
  if (!m) return null
  const [, colons, kindRaw, bracket, brace] = m
  const kind = kindRaw.toLowerCase() as Kind
  if (kind !== 'info' && kind !== 'success' && kind !== 'warning'
    && kind !== 'error' && kind !== 'epigraph' && kind !== 'align') {
    return null
  }
  const title = bracket ? bracket.slice(1, -1) : ''
  const options = brace ? brace.slice(1, -1).trim() : ''
  return { fence: colons.length, kind, title, options }
}

/** 判断一行是否是对应 fence 长度的纯闭合（与 opener 同数量冒号，后面无文字） */
function isCloser(line: string, fence: number): boolean {
  const re = new RegExp(`^:{${fence}}\\s*$`)
  return re.test(line)
}

/**
 * 自定义 block ruler：吃掉 `:::kind[title]{opts}` ... `:::` 段，生成 container_open/close token。
 * 内部内容用 md.block.tokenize 递归解析（保证支持嵌套）。
 */
function containerRule(md: MarkdownIt) {
  md.block.ruler.before('fence', 'luogu_container', (state: any, startLine: number, endLine: number, silent: boolean) => {
    const pos = state.bMarks[startLine] + state.tShift[startLine]
    const max = state.eMarks[startLine]
    const line = state.src.slice(pos, max)
    const open = parseOpener(line)
    if (!open) return false
    if (silent) return true

    // 找到同 fence 的闭合
    let nextLine = startLine + 1
    let found = false
    while (nextLine < endLine) {
      const ln = state.src.slice(
        state.bMarks[nextLine] + state.tShift[nextLine],
        state.eMarks[nextLine],
      )
      if (isCloser(ln, open.fence)) {
        found = true
        break
      }
      nextLine++
    }
    if (!found) return false

    const oldParent = state.parentType
    const oldLineMax = state.lineMax
    state.parentType = 'luogu_container'
    state.lineMax = nextLine

    const tokenOpen = state.push('luogu_container_open', '', 1)
    tokenOpen.markup = ':'.repeat(open.fence)
    tokenOpen.block = true
    tokenOpen.info = JSON.stringify(open)
    tokenOpen.map = [startLine, nextLine]

    // 关键：递归解析内容行（启用嵌套）
    state.md.block.tokenize(state, startLine + 1, nextLine)

    const tokenClose = state.push('luogu_container_close', '', -1)
    tokenClose.markup = ':'.repeat(open.fence)
    tokenClose.block = true

    state.parentType = oldParent
    state.lineMax = oldLineMax
    state.line = nextLine + 1
    return true
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] })

  md.renderer.rules.luogu_container_open = (tokens, idx) => {
    const info: ReturnType<typeof parseOpener> = JSON.parse(tokens[idx].info || '{}')
    if (!info) return ''
    const { kind, title, options } = info
    const safeTitle = md.renderInline(title || '')

    if (FOLD_KINDS.has(kind)) {
      const open = /\bopen\b/i.test(options)
      const shown = safeTitle || defaultTitle(kind)
      return `<details class="lg-callout lg-callout-${kind}"${open ? ' open' : ''}>`
        + `<summary>${shown}</summary>\n`
    }
    if (kind === 'epigraph') {
      // 署名放在容器末尾的右下角；此处仅开壳
      return `<div class="lg-epigraph"${title ? ` data-source="${escapeAttr(title)}"` : ''}>\n`
    }
    if (kind === 'align') {
      const dir = /right/i.test(options) ? 'right' : /center/i.test(options) ? 'center' : 'left'
      return `<div class="lg-align" style="text-align:${dir}">\n`
    }
    return ''
  }

  md.renderer.rules.luogu_container_close = (tokens, idx) => {
    // 简单收尾；区分类型用 markup（不太好拿 info），用通用 </div> / </details> 都不行。
    // 改法：把 kind 塞在 close token 的 info 里。
    const info = (tokens[idx] as any).__kind as Kind | undefined
    if (info && FOLD_KINDS.has(info)) return '</details>\n'
    return '</div>\n'
  }

  // 让 close token 能拿到自己所属的 kind
  md.core.ruler.after('block', 'luogu_container_pair', (state: any) => {
    const stack: Kind[] = []
    for (const tok of state.tokens) {
      if (tok.type === 'luogu_container_open') {
        const info = JSON.parse(tok.info || '{}')
        stack.push(info.kind)
      } else if (tok.type === 'luogu_container_close') {
        tok.__kind = stack.pop()
      }
    }
  })
}

function defaultTitle(kind: Kind): string {
  switch (kind) {
    case 'info': return '提示'
    case 'success': return '成功'
    case 'warning': return '警告'
    case 'error': return '错误'
    default: return ''
  }
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function bilibiliEmbedUrl(src: string): string | null {
  const raw = (src || '').trim()
  if (!raw.toLowerCase().startsWith('bilibili:')) return null

  let body = raw.slice('bilibili:'.length).trim()
  if (!body) return null

  let query = ''
  const queryIndex = body.indexOf('?')
  if (queryIndex >= 0) {
    query = body.slice(queryIndex + 1)
    body = body.slice(0, queryIndex)
  }

  let bvid = ''
  let aid = ''
  let cid = ''
  let page = '1'

  const applyQuery = (q: string) => {
    const params = new URLSearchParams(q)
    bvid = params.get('bvid') || params.get('BV') || bvid
    aid = params.get('aid') || params.get('av') || aid
    cid = params.get('cid') || cid
    page = params.get('p') || params.get('page') || page
  }

  if (/^https?:\/\//i.test(body) || body.startsWith('//')) {
    try {
      const url = new URL(body.startsWith('//') ? `https:${body}` : body)
      const pathMatch = url.pathname.match(/\/video\/(BV[0-9A-Za-z]{10,}|av\d+)/i)
      if (pathMatch) body = pathMatch[1]
      applyQuery(url.search.slice(1))
    } catch {
      return null
    }
  }
  if (query) applyQuery(query)

  const bvMatch = body.match(/^(BV[0-9A-Za-z]{10,})$/i)
  const avMatch = body.match(/^(?:av)?(\d+)$/i)
  if (bvMatch) {
    bvid = bvMatch[1]
  } else if (avMatch) {
    aid = avMatch[1]
  }

  if (!bvid && !aid) return null

  const params = new URLSearchParams({
    isOutside: 'true',
    autoplay: '0',
    page: String(Math.max(1, Number.parseInt(page, 10) || 1)),
  })
  if (bvid) params.set('bvid', bvid)
  if (aid) params.set('aid', aid)
  if (cid) params.set('cid', cid)
  return `https://player.bilibili.com/player.html?${params.toString()}`
}

function build(): MarkdownIt {
  const md = new MarkdownIt({
    html: false,
    breaks: true,
    linkify: true,
    typographer: false,
  })
  md.use(mdKatex.default || mdKatex, {
    throwOnError: false,
    errorColor: '#f44',
    enableBareBlocks: true,
    enableMathBlockInHtml: true,
    enableMathInlineInHtml: true,
  })
  containerRule(md)

  // 洛谷 @[name](/user/uid) 简单渲染为带颜色占位的 link
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

  const origImage = md.renderer.rules.image ||
    ((tokens, idx, opts, _env, self) => self.renderToken(tokens, idx, opts))
  md.renderer.rules.image = (tokens, idx, opts, env, self) => {
    const src = tokens[idx].attrGet('src') || ''
    const embedUrl = bilibiliEmbedUrl(src)
    if (!embedUrl) return origImage(tokens, idx, opts, env, self)

    const alt = self.renderInlineAsText(tokens[idx].children || [], opts, env)
    const title = tokens[idx].attrGet('title') || alt || 'Bilibili video'
    return `<span class="lg-bilibili" role="group" aria-label="${escapeAttr(title)}">`
      + '<span class="lg-bilibili-frame">'
      + `<iframe src="${escapeAttr(embedUrl)}" title="${escapeAttr(title)}" loading="lazy" `
      + 'allow="fullscreen; picture-in-picture" allowfullscreen></iframe>'
      + '</span>'
      + (alt ? `<span class="lg-bilibili-caption">${md.utils.escapeHtml(alt)}</span>` : '')
      + '</span>'
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
    const allowed = ['/article/', '/paste/', '/user/', '/judgement', '/feed']
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
  const render = (src: string) => _md!.render(normalizeDisplayMath(src || ''))
  return { render }
}
