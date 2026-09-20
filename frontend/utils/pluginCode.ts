/** 完整代码超过该大小时不允许复制，只保留文件下载。 */
export const PLUGIN_CODE_COPY_MAX_BYTES = 100 * 1024

/** 二进制插件体积上限，必须与后端 BINARY_FILE_MAX_BYTES 保持一致。 */
export const PLUGIN_BINARY_MAX_BYTES = 10 * 1024 * 1024

/** 后端 BINARY_ALLOWED_SUFFIXES 的前端副本，只用于提前提示，判定仍以后端为准。 */
export const PLUGIN_BINARY_ALLOWED_SUFFIXES = ['.zip', '.crx', '.xpi']

export function isBinaryCode(codeEncoding?: string | null): boolean {
  return codeEncoding === 'base64'
}

/** 由 base64 长度反推原始字节数，避免为了显示体积而解码整个文件。 */
export function base64ByteLength(base64: string): number {
  if (!base64) return 0
  const padding = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0
  return Math.floor((base64.length * 3) / 4) - padding
}

/** File -> 纯 base64：去掉 data URL 前缀，与后端 PluginSnapshot.code 的约定一致。 */
export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onerror = () => reject(reader.error ?? new Error('读取文件失败'))
    reader.onload = () => {
      const result = String(reader.result || '')
      const comma = result.indexOf(',')
      resolve(comma >= 0 ? result.slice(comma + 1) : result)
    }
    reader.readAsDataURL(file)
  })
}

/** 分块转换，避免大文件用 spread 铺参数爆栈。 */
export function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkBytes = 0x8000
  for (let offset = 0; offset < bytes.length; offset += chunkBytes) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkBytes))
  }
  return btoa(binary)
}

export function base64ToBytes(base64: string): Uint8Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  return bytes
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MiB`
}
