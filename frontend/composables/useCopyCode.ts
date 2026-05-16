/**
 * 给 .lg-content pre 块自动注入一键复制按钮。
 * 用法：在组件里拿到 v-html 的容器 ref，`useCopyCode(containerRef)`
 * SSR 环境不做事，hydrate 后在客户端扫 DOM。
 */
export function useCopyCode(containerRef: Ref<HTMLElement | null | undefined>) {
  if (import.meta.server) return

  function attach(el: HTMLElement) {
    el.querySelectorAll<HTMLPreElement>('pre').forEach((pre) => {
      if (pre.dataset.copyBound === '1') return
      pre.dataset.copyBound = '1'
      pre.style.position ||= 'relative'

      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'code-copy-btn'
      btn.textContent = '复制'
      btn.addEventListener('click', async () => {
        const code = pre.querySelector('code')
        const text = (code?.textContent ?? pre.textContent ?? '').replace(/\n$/, '')
        try {
          await navigator.clipboard.writeText(text)
          btn.textContent = '已复制'
          btn.classList.add('ok')
        } catch {
          btn.textContent = '失败'
          btn.classList.add('err')
        }
        setTimeout(() => {
          btn.textContent = '复制'
          btn.classList.remove('ok', 'err')
        }, 1500)
      })
      pre.appendChild(btn)
    })
  }

  // 组件挂载 + 后续 v-html 变动时重新绑定
  const run = () => {
    const el = containerRef.value
    if (el) attach(el)
  }

  onMounted(() => {
    run()
    const el = containerRef.value
    if (!el) return
    const mo = new MutationObserver(run)
    mo.observe(el, { childList: true, subtree: true })
    onBeforeUnmount(() => mo.disconnect())
  })
}
