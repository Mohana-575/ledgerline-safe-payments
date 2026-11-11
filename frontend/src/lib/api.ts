const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? (import.meta.env.PROD ? '' : '/api')

export class ApiError extends Error {
  readonly status: number
  readonly data: unknown

  constructor(message: string, status: number, data?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.data = data
  }
}

export interface ApiRequestOptions extends Omit<RequestInit, 'headers'> {
  headers?: HeadersInit
  idempotencyKey?: string
}

function responseMessage(data: unknown, fallback: string): string {
  if (typeof data === 'string' && data.length > 0) return data
  if (typeof data === 'object' && data !== null && 'detail' in data) {
    const detail = data.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail
        .map((item) => {
          if (typeof item === 'object' && item !== null && 'msg' in item) {
            return String(item.msg)
          }
          return String(item)
        })
        .join('; ')
    }
  }
  if (typeof data === 'object' && data !== null && 'message' in data) {
    const message = data.message
    if (typeof message === 'string') return message
  }
  return fallback
}

export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { headers: suppliedHeaders, idempotencyKey, ...requestOptions } = options
  const headers = new Headers(suppliedHeaders)

  if (typeof requestOptions.body === 'string' && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (idempotencyKey !== undefined) {
    headers.set('Idempotency-Key', idempotencyKey)
  }

  let response: Response
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...requestOptions,
      headers,
      credentials: 'include',
    })
  } catch (error) {
    throw new ApiError(
      error instanceof Error ? error.message : 'Unable to reach the server',
      0,
      error,
    )
  }

  const responseText = await response.text()
  let data: unknown
  if (responseText) {
    try {
      data = JSON.parse(responseText)
    } catch {
      data = responseText
    }
  }

  if (!response.ok) {
    throw new ApiError(
      responseMessage(data, response.statusText || 'Request failed'),
      response.status,
      data,
    )
  }

  if (responseText && typeof data === 'string') {
    throw new ApiError('The server returned an invalid response', response.status, data)
  }

  return data as T
}
