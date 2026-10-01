/** 统一请求封装：拼后端地址、控制超时、把失败原因留给页面。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const DEFAULT_TIMEOUT_MS = 10_000

export class RequestTimeoutError extends Error {
  readonly timeoutMs: number

  constructor(timeoutMs: number) {
    super(`接口请求超时：${timeoutMs / 1000} 秒内未收到响应，请检查网络后重试`)
    this.name = 'RequestTimeoutError'
    this.timeoutMs = timeoutMs
  }
}

export function request(
  path: string,
  init?: RequestInit,
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeoutMs)
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
    signal: controller.signal,
  })
    .finally(() => clearTimeout(timer))
    .catch((error: unknown) => {
      if (error instanceof Error && error.name === 'AbortError') {
        throw new RequestTimeoutError(timeoutMs)
      }
      const detail = error instanceof Error ? error.message : '请求未送达'
      throw new Error(`接口请求失败：${detail}`)
    })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}
