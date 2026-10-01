/**
 * Markdown 渲染（前端）
 *
 * 后端返回原 Markdown 字符串，前端渲染成 HTML + KaTeX 公式。
 * 洛谷专有语法在这里做前端兜底渲染。
 */
import MarkdownIt from 'markdown-it'
import type Token from 'markdown-it/lib/token.mjs'
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
  const m = line.match(/^(:{3,})\s*([a-zA-Z][a-zA-Z0-9_-]*)(.*)$/)
  if (!m) return null
  const [, colons, kindRaw, tail] = m
  const kind = kindRaw.toLowerCase() as Kind
  if (kind !== 'info' && kind !== 'success' && kind !== 'warning'
    && kind !== 'error' && kind !== 'epigraph' && kind !== 'align') {
    return null
  }
  // 标题允许链接中的方括号以及转义字符，不能在第一个右括号处提前结束。
  let rest = tail.trim()
  let title = ''
  if (rest.startsWith('[')) {
    let depth = 1
    let end = 1
    for (; end < rest.length; end++) {
      if (rest[end] === '\\') { end++; continue }
      if (rest[end] === '[') depth++
      if (rest[end] === ']' && --depth === 0) break
    }
    if (depth !== 0) return null
    title = rest.slice(1, end)
    rest = rest.slice(end + 1).trim()
  }
  if (rest && !/^\{[^}]*\}$/.test(rest)) return null
  const options = rest ? rest.slice(1, -1).trim() : ''
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
    if (state.sCount[startLine] - state.blkIndent >= 4) return false
    const pos = state.bMarks[startLine] + state.tShift[startLine]
    const max = state.eMarks[startLine]
    const line = state.src.slice(pos, max)
    const open = parseOpener(line)
    if (!open) return false
    if (silent) return true

    // 找到同 fence 的闭合
    let nextLine = startLine + 1
    let found = false
    let codeFence = ''
    while (nextLine < endLine) {
      const ln = state.src.slice(
        state.bMarks[nextLine] + state.tShift[nextLine],
        state.eMarks[nextLine],
      )
      // 代码示例中的冒号只是代码，不能提前关闭外层折叠框。
      const codeMarker = ln.match(/^(`{3,}|~{3,})(.*)$/)
      if (codeMarker) {
        if (!codeFence) codeFence = codeMarker[1]
        else if (codeMarker[1][0] === codeFence[0]
          && codeMarker[1].length >= codeFence.length && !codeMarker[2].trim()) codeFence = ''
        nextLine++
        continue
      }
      if (!codeFence && isCloser(ln, open.fence)) {
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
    tokenClose.info = tokenOpen.info

    state.parentType = oldParent
    state.lineMax = oldLineMax
    state.line = nextLine + 1
    return true
  }, { alt: ['paragraph', 'reference', 'blockquote', 'list'] })

  md.renderer.rules.luogu_container_open = (tokens, idx) => {
    const info: ReturnType<typeof parseOpener> = JSON.parse(tokens[idx].info || '{}')
    if (!info) return ''
    const { kind, title, options } = info
    // 手册中的标题允许用双美元符号写公式；在行内标题中按行内公式处理。
    const safeTitle = md.renderInline((title || '').replace(/\$\$([^]*?)\$\$/g, (_, body) => `$${body.trim()}$`))

    if (FOLD_KINDS.has(kind)) {
      const open = /\bopen\b/i.test(options)
      const shown = safeTitle || defaultTitle(kind)
      return `<details class="lg-callout lg-callout-${kind}"${open ? ' open' : ''}>`
        + `<summary>${shown}</summary>\n`
    }
    if (kind === 'epigraph') {
      // 署名放在容器末尾的右下角；此处仅开壳
      return '<div class="lg-epigraph">\n'
    }
    if (kind === 'align') {
      const dir = /right/i.test(options) ? 'right' : /center/i.test(options) ? 'center' : 'left'
      return `<div class="lg-align" style="text-align:${dir}">\n`
    }
    return ''
  }

  md.renderer.rules.luogu_container_close = (tokens, idx) => {
    const { kind, title } = JSON.parse(tokens[idx].info)
    if (FOLD_KINDS.has(kind)) return '</details>\n'
    if (kind === 'epigraph' && title) {
      return `<footer class="lg-epigraph-source">${md.renderInline(title)}</footer></div>\n`
    }
    return '</div>\n'
  }

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

interface TableCell {
  open: Token
  inline: Token
  indexes: number[]
  column: number
  width: number
  height: number
  marker: string
}

/** 在 Markdown token 上合并单元格，避免对含公式、链接的 HTML 做字符串替换。 */
function mergeTableCells(tokens: Token[], start: number, end: number): Set<number> {
  const rows: TableCell[][] = []
  for (let i = start + 1; i < end; i++) {
    if (tokens[i].type !== 'tr_open') continue
    const cells: TableCell[] = []
    while (++i < end && tokens[i].type !== 'tr_close') {
      if (tokens[i].type !== 'td_open' && tokens[i].type !== 'th_open') continue
      const open = tokens[i]
      const indexes = [i]
      const column = cells.length
      const inline = tokens[++i]
      indexes.push(i, ++i)
      const marker = inline.children?.length === 1 && inline.children[0].type === 'text'
        ? inline.content.trim() : ''
      cells.push({ open, inline, indexes, column, width: 1, height: 1, marker })
    }
    rows.push(cells)
  }

  const removed = new Set<number>()
  const owners: TableCell[][] = []
  for (const cells of rows) {
    const row: TableCell[] = []
    // 先处理横向合并，让后面的竖向合并能检查完整的矩形范围。
    for (const cell of cells) {
      const left = row[cell.column - 1]
      if (cell.marker === '<' && left) {
        left.width++
        left.open.attrSet('colspan', String(left.width))
        cell.indexes.forEach(index => removed.add(index))
        row[cell.column] = left
      } else {
        row[cell.column] = cell
      }
    }

    const above = owners[owners.length - 1]
    for (const cell of new Set(row)) {
      if (cell.marker !== '^' || !above || cell.open.type !== 'td_open') continue
      const target = above[cell.column]
      // 只合并同宽、相邻的正文单元格；无效标记保留原样，不破坏表格。
      if (!target || target.open.type !== 'td_open' || target.column !== cell.column
        || target.width !== cell.width
        || !row.slice(cell.column, cell.column + cell.width).every(owner => owner === cell)
        || !above.slice(cell.column, cell.column + cell.width).every(owner => owner === target)) continue
      target.height++
      target.open.attrSet('rowspan', String(target.height))
      cell.indexes.forEach(index => removed.add(index))
      for (let column = cell.column; column < cell.column + cell.width; column++) row[column] = target
    }
    owners.push(row)
  }
  return removed
}

function extendedMarkdownRules(md: MarkdownIt) {
  md.block.ruler.before('paragraph', 'luogu_cute_table', (state: any, start: number, _end: number, silent: boolean) => {
    if (state.sCount[start] - state.blkIndent >= 4) return false
    const line = state.src.slice(state.bMarks[start] + state.tShift[start], state.eMarks[start])
    if (!/^::cute-table\{tuack\}\s*$/.test(line)) return false
    if (silent) return true
    const token = state.push('luogu_cute_table', '', 0)
    token.content = line
    token.block = true
    token.map = [start, start + 1]
    state.line = start + 1
    return true
  }, { alt: ['paragraph'] })
  md.renderer.rules.luogu_cute_table = (tokens, index) => `<p>${md.utils.escapeHtml(tokens[index].content)}</p>\n`

  md.core.ruler.after('inline', 'luogu_extended_blocks', (state: any) => {
    const tokens: Token[] = state.tokens
    const removed = new Set<number>()
    const lists: Token[] = []
    for (let i = 0; i < tokens.length; i++) {
      const token = tokens[i]
      if (token.type === 'table_open') {
        if (tokens[i - 1]?.type === 'luogu_cute_table') {
          token.attrJoin('class', 'lg-cute-table')
          removed.add(i - 1)
        }
        let end = i + 1
        while (end < tokens.length && tokens[end].type !== 'table_close') end++
        for (const index of mergeTableCells(tokens, i, end)) removed.add(index)
      }
      if (token.type === 'bullet_list_open' || token.type === 'ordered_list_open') lists.push(token)
      if (token.type === 'bullet_list_close' || token.type === 'ordered_list_close') lists.pop()
      if (token.type !== 'list_item_open' || tokens[i + 1]?.type !== 'paragraph_open') continue
      const inline = tokens[i + 2]
      const first = inline?.children?.[0]
      const task = first?.type === 'text' ? first.content.match(/^\[([ xX])\]\s+/) : null
      if (!task) continue
      first!.content = first!.content.slice(task[0].length)
      // 复选框只展示归档状态，禁止用户在缓存内容里改动任务状态。
      const checkbox = new state.Token('html_inline', '', 0)
      checkbox.content = `<input class="lg-task-checkbox" type="checkbox" disabled${task[1].toLowerCase() === 'x' ? ' checked' : ''}> `
      inline.children!.unshift(checkbox)
      token.attrJoin('class', 'lg-task-item')
      const list = lists[lists.length - 1]
      if (list && !list.attrGet('class')?.split(' ').includes('lg-task-list')) list.attrJoin('class', 'lg-task-list')
    }
    state.tokens = tokens.filter((_token, index) => !removed.has(index))
  })

  const originalFence = md.renderer.rules.fence!
  md.renderer.rules.fence = (tokens, index, options, env, renderer) => {
    const token = tokens[index]
    const parameters = token.info.trim().split(/\s+/)
    const numbered = parameters.includes('line-numbers')
    const range = parameters.find(parameter => /^lines=\d+-\d+$/.test(parameter))
    if (!numbered && !range) return originalFence(tokens, index, options, env, renderer)
    const language = parameters[0] && !parameters[0].includes('=') && parameters[0] !== 'line-numbers'
      ? parameters[0] : 'cpp'
    const [from, to] = range ? range.slice(6).split('-').map(Number) : [0, 0]
    const lines = token.content.replace(/\n$/, '').split('\n')
    // 行号放在 data 属性和伪元素里，复制代码时不会混进源码。
    const html = lines.map((line, i) => {
      const highlighted = i + 1 >= from && i + 1 <= to
      return `<span class="lg-code-line${highlighted ? ' is-highlighted' : ''}" data-line="${i + 1}">${md.utils.escapeHtml(line)}</span>`
    }).join('\n') + '\n'
    return `<pre class="lg-code-block${numbered ? ' has-line-numbers' : ''}"><code class="language-${escapeAttr(language)}">${html}</code></pre>\n`
  }

  // 大表格在正文内部横向滚动，避免手机上被整页的溢出保护裁掉。
  const tableOpen = md.renderer.rules.table_open || ((tokens, index, options, _env, renderer) => renderer.renderToken(tokens, index, options))
  const tableClose = md.renderer.rules.table_close || ((tokens, index, options, _env, renderer) => renderer.renderToken(tokens, index, options))
  md.renderer.rules.table_open = (...args) => `<div class="lg-table-scroll">${tableOpen(...args)}`
  md.renderer.rules.table_close = (...args) => `${tableClose(...args)}</div>\n`
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
  md.use(mdKatex, {
    throwOnError: false,
    errorColor: '#f44',
    enableBareBlocks: true,
    enableMathBlockInHtml: true,
    enableMathInlineInHtml: true,
  })
  containerRule(md)
  extendedMarkdownRules(md)

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
    const allowed = ['/article/', '/paste/', '/discuss/', '/user/', '/judgement', '/feed']
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
