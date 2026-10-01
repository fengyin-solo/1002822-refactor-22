/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const REQUEST_TIMEOUT_MS = 10_000

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
    signal: controller.signal,
  })
    .catch((error: unknown) => {
      if (error instanceof DOMException && error.name === 'AbortError') {
        throw new Error(`接口请求超时：${path} 超过 ${REQUEST_TIMEOUT_MS / 1000} 秒未响应`)
      }
      const detail = error instanceof Error ? error.message : '请求未送达'
      throw new Error(`接口请求失败：${detail}`)
    })
    .finally(() => clearTimeout(timer))
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
