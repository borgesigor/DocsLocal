export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

export async function request<T>(
  path: string,
  options?: RequestInit
): Promise<T> {
  const headers = new Headers(options?.headers)
  if (options?.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json")
  }
  const response = await fetch(`/api/v1${path}`, { ...options, headers })
  const result = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new ApiError(
      result?.error?.message ?? `Erro ${response.status}`,
      response.status
    )
  }
  return result as T
}
