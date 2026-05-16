/**
 * 时间显示工具。后端存 UTC 字符串（含 Z 或 +00:00），前端统一转北京时间显示。
 *
 * 用法：
 *   const { format, fromNow, smart } = useTime()
 *   format(t)              // 2026-05-16 21:34
 *   format(t, 'MM-DD HH:mm')
 *   fromNow(t)             // 3 分钟前
 *   smart(t)               // 24h 内相对时间，否则绝对时间
 *
 * 注：dayjs 插件的注册放在本模块顶层，确保 SSR 和客户端两端都生效，
 *      不依赖 Nuxt plugin 的加载顺序。
 */
import dayjs from 'dayjs'
import 'dayjs/locale/zh-cn'
import utc from 'dayjs/plugin/utc'
import timezone from 'dayjs/plugin/timezone'
import relativeTime from 'dayjs/plugin/relativeTime'

// 模块顶层注册插件，幂等
dayjs.extend(utc)
dayjs.extend(timezone)
dayjs.extend(relativeTime)
dayjs.locale('zh-cn')

const TZ = 'Asia/Shanghai'

function toBJ(t: string | Date | number | null | undefined) {
  if (t == null || t === '') return null
  return dayjs.utc(t).tz(TZ)
}

export function useTime() {
  function format(t: any, fmt = 'YYYY-MM-DD HH:mm') {
    const d = toBJ(t)
    return d ? d.format(fmt) : ''
  }
  function fromNow(t: any) {
    const d = toBJ(t)
    return d ? d.fromNow() : ''
  }
  function smart(t: any) {
    const d = toBJ(t)
    if (!d) return ''
    const now = dayjs().tz(TZ)
    return now.diff(d, 'hour') < 24 ? d.fromNow() : d.format('YYYY-MM-DD HH:mm')
  }
  return { format, fromNow, smart, toBJ }
}
