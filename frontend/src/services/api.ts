import type {
  Character,
  EvidenceGraph,
  Job,
  LibraryVideo,
  Readiness,
  SceneDetail,
  SearchRequest,
  SearchResponse,
  SearchAnswer,
  SearchContext,
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

export async function request<T>(
  path: string,
  options: RequestInit = {},
  readiness = false
): Promise<T> {
  let response: Response
  const controller = new AbortController()
  const abort = () => controller.abort(options.signal?.reason)
  const timeout = window.setTimeout(
    () => controller.abort(new DOMException('Request timed out', 'TimeoutError')),
    path.startsWith('/api/search') ? 90_000 : 30_000
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
  session: (id: string, signal?: AbortSignal) =>
    request<{ request: SearchRequest; response: SearchResponse; answer: SearchAnswer | null }>(
      `/api/search/sessions/${encodeURIComponent(id)}`,
      { signal }
    ),
  answer: (
    body: { query: string; scene_ids: string[]; collection_id?: string; character_ids?: string[] },
    signal?: AbortSignal
  ) =>
    request<SearchAnswer>('/api/search/answer', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  context: (body: AnswerRequest, signal?: AbortSignal) =>
    request<SearchContext>('/api/search/context', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal,
    }),
  graph: (
    body: { scene_ids: string[]; collection_id?: string; query?: string },
    signal?: AbortSignal
  ) =>
    request<EvidenceGraph>('/api/search/graph', {
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

export interface AnswerRequest {
  query: string
  scene_ids: string[]
  collection_id?: string
  character_ids?: string[]
  search_id?: string
}

export interface AnswerStreamHandlers {
  onDelta: (value: Pick<SearchAnswer, 'answer' | 'claims' | 'citations'>) => void
}

export async function streamAnswer(
  body: AnswerRequest,
  handlers: AnswerStreamHandlers,
  signal: AbortSignal
): Promise<SearchAnswer> {
  const timeout = AbortSignal.timeout(120_000)
  const combined = AbortSignal.any([signal, timeout])
  const response = await fetch(apiUrl('/api/search/answer/stream'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal: combined,
  })
  if (!response.ok)
    throw new ApiError(errorMessage(await response.json().catch(() => null)), response.status)
  if (!response.body) throw new ApiError('The answer stream is unavailable.', 502)
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: SearchAnswer | null = null
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        const event = /^event: (.+)$/m.exec(frame)?.[1]?.trim()
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (!event || !data) continue
        const payload = JSON.parse(data)
        if (
          event === 'delta' &&
          typeof payload.text === 'string' &&
          Array.isArray(payload.claims) &&
          Array.isArray(payload.citations)
        )
          handlers.onDelta({
            answer: payload.text,
            claims: payload.claims,
            citations: payload.citations,
          })
        else if (
          event === 'answer' &&
          ['generated', 'unavailable', 'insufficient_evidence'].includes(payload.status) &&
          Array.isArray(payload.citations)
        )
          final = payload as SearchAnswer
        else if (event === 'error')
          throw new ApiError(String(payload.detail ?? 'The answer stream failed.'), 502)
      }
      if (done) break
      if (buffer.length > 1_000_000)
        throw new ApiError('The answer exceeded the response size limit.', 502)
    }
  } finally {
    await reader.cancel().catch(() => undefined)
  }
  if (!final)
    throw new ApiError('The answer stream ended early. Your scene results remain available.', 502)
  return final
}

export interface ChatSource {
  number: number
  scene_id: string
  label: string
  start: number | null
  end: number | null
  timestamp_basis: string
  available: boolean
  snippet: string
}

export interface ChatReply {
  conversation_id: string
  answer: string
  sources: ChatSource[]
  warnings: string[]
  model: string | null
}

export interface ChatStreamHandlers {
  onSources?: (sources: ChatSource[], warnings: string[]) => void
  onDelta?: (text: string) => void
}

export async function streamChat(
  body: { question: string; conversation_id?: string; collection_id?: string },
  handlers: ChatStreamHandlers,
  signal: AbortSignal
): Promise<ChatReply> {
  const response = await fetch(apiUrl('/api/chat/stream'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal: AbortSignal.any([signal, AbortSignal.timeout(300_000)]),
  })
  if (!response.ok)
    throw new ApiError(errorMessage(await response.json().catch(() => null)), response.status)
  if (!response.body) throw new ApiError('The chat stream is unavailable.', 502)

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let final: ChatReply | null = null
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        boundary = buffer.indexOf('\n\n')
        const event = /^event: (.+)$/m.exec(frame)?.[1]?.trim()
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (!event || !data) continue
        const payload = JSON.parse(data)
        if (event === 'sources')
          handlers.onSources?.(payload.sources ?? [], payload.warnings ?? [])
        else if (event === 'delta' && typeof payload.text === 'string')
          handlers.onDelta?.(payload.text)
        else if (event === 'answer' && typeof payload.answer === 'string')
          final = payload as ChatReply
        else if (event === 'error')
          throw new ApiError(String(payload.detail ?? 'The chat stream failed.'), 502)
      }
      if (done) break
    }
  } finally {
    await reader.cancel().catch(() => undefined)
  }
  if (!final) throw new ApiError('The chat stream ended early.', 502)
  return final
}

export interface ChatConversation {
  id: string
  created: number
  updated: number
  title: string
  first_question: string | null
  turns: number
}

export interface ChatMessage {
  id: string
  created: number
  role: 'user' | 'assistant'
  content: string
  data: { sources?: ChatSource[]; model?: string }
}

export async function listConversations(): Promise<ChatConversation[]> {
  return request<ChatConversation[]>('/api/chat/conversations')
}

export async function loadConversation(
  id: string
): Promise<{ conversation_id: string; messages: ChatMessage[] }> {
  return request(`/api/chat/conversations/${encodeURIComponent(id)}`)
}

export async function deleteConversation(id: string): Promise<{ deleted: boolean }> {
  return request(`/api/chat/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' })
}
