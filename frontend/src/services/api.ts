import type {
  Character,
  Job,
  LibraryVideo,
  Readiness,
  SceneDetail,
  SearchRequest,
  SearchResponse,
  Workspace,
} from '../types'

const configuredBase =
  (import.meta.env.VITE_API_URL as string | undefined)?.replace(/\/$/, '') ?? ''
export const apiUrl = (path: string) => `${configuredBase}${path}`
export const thumbnailUrl = (sceneId: string) =>
  apiUrl(`/api/scenes/${encodeURIComponent(sceneId)}/thumbnail`)
export const subtitleUrl = (sceneId: string) =>
  apiUrl(`/api/scenes/${encodeURIComponent(sceneId)}/subtitles.vtt`)

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function errorMessage(body: unknown): string {
  if (typeof body !== 'object' || body === null || !('detail' in body))
    return 'The request could not be completed.'
  const detail = body.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail))
    return detail
      .map((item) => (typeof item?.msg === 'string' ? item.msg : 'Invalid request'))
      .join('. ')
  return 'The request could not be completed.'
}

async function request<T>(path: string, options: RequestInit = {}, readiness = false): Promise<T> {
  let response: Response
  const controller = new AbortController()
  const abort = () => controller.abort(options.signal?.reason)
  const timeout = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    path === '/api/search' ? 90_000 : 30_000
  )
  options.signal?.addEventListener('abort', abort, { once: true })
  if (options.signal?.aborted) abort()
  try {
    response = await fetch(apiUrl(path), { ...options, signal: controller.signal })
    const body: unknown = await response.json().catch((error) => {
      if (controller.signal.aborted) throw error
      return null
    })
    const serviceReport =
      readiness &&
      response.status === 503 &&
      typeof body === 'object' &&
      body !== null &&
      'ready' in body &&
      'services' in body
    if (!response.ok && !serviceReport) throw new ApiError(errorMessage(body), response.status)
    if (body === null || typeof body !== 'object')
      throw new ApiError('The backend returned an unexpected response.', 502)
    return body as T
  } catch (error) {
    if (controller.signal.aborted && !options.signal?.aborted)
      throw new ApiError(
        'This request took too long. The backend may still be loading a model. Try again, or check service status in Settings.',
        408
      )
    if (error instanceof DOMException && error.name === 'AbortError') throw error
    if (error instanceof ApiError) throw error
    throw new ApiError(
      'Searchy could not connect to the backend. Check that the API is running.',
      0
    )
  } finally {
    window.clearTimeout(timeout)
    options.signal?.removeEventListener('abort', abort)
  }
}

function queryString(values: Record<string, string | number | undefined>) {
  const params = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== undefined && value !== '') params.set(key, String(value))
  })
  return params.toString()
}

export const api = {
  workspace: (signal?: AbortSignal) => request<Workspace>('/api/workspace', { signal }),
  readiness: (signal?: AbortSignal) => request<Readiness>('/ready', { signal }, true),
  library: (
    filters: { q?: string; collection_id?: string; limit?: number; offset?: number } = {},
    signal?: AbortSignal
  ) =>
    request<{ items: LibraryVideo[]; total: number }>(`/api/library?${queryString(filters)}`, {
      signal,
    }),
  video: (id: string, signal?: AbortSignal) =>
    request<LibraryVideo>(`/api/videos/${encodeURIComponent(id)}`, { signal }),
  scenes: (videoId: string, offset = 0, signal?: AbortSignal) =>
    request<SceneDetail[]>(
      `/api/videos/${encodeURIComponent(videoId)}/scenes?limit=50&offset=${offset}`,
      { signal }
    ),
  scene: (id: string, signal?: AbortSignal) =>
    request<SceneDetail>(`/api/scenes/${encodeURIComponent(id)}`, { signal }),
  characters: (signal?: AbortSignal) => request<Character[]>('/api/characters', { signal }),
  characterScenes: (id: string, offset = 0, signal?: AbortSignal) =>
    request<SceneDetail[]>(
      `/api/characters/${encodeURIComponent(id)}/scenes?limit=24&offset=${offset}`,
      { signal }
    ),
  jobs: (signal?: AbortSignal) => request<Job[]>('/api/jobs?limit=100', { signal }),
  retryJob: (id: string) =>
    request<Job>(`/api/jobs/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  search: (body: SearchRequest, signal?: AbortSignal) =>
    request<SearchResponse>('/api/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
}

export function uploadVideo(
  file: File,
  collection: string,
  onProgress: (percent: number) => void,
  signal: AbortSignal
): Promise<Job> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new DOMException('Upload cancelled', 'AbortError'))
      return
    }
    const xhr = new XMLHttpRequest()
    const abort = () => xhr.abort()
    const clean = () => signal.removeEventListener('abort', abort)
    xhr.open('POST', apiUrl('/api/videos/upload'))
    xhr.responseType = 'json'
    xhr.timeout = 30 * 60 * 1000
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100))
    }
    xhr.onload = () => {
      clean()
      if (xhr.status >= 200 && xhr.status < 300 && xhr.response?.job_id)
        resolve(xhr.response as Job)
      else reject(new ApiError(errorMessage(xhr.response), xhr.status))
    }
    xhr.onerror = () => {
      clean()
      reject(
        new ApiError(
          'Upload interrupted. Check your connection and Processing Jobs before trying again.',
          0
        )
      )
    }
    xhr.ontimeout = () => {
      clean()
      reject(new ApiError('Upload timed out. Check Processing Jobs before trying again.', 408))
    }
    xhr.onabort = () => {
      clean()
      reject(new DOMException('Upload cancelled', 'AbortError'))
    }
    signal.addEventListener('abort', abort, { once: true })
    const data = new FormData()
    data.append('file', file)
    data.append('collection_id', collection)
    xhr.send(data)
  })
}
