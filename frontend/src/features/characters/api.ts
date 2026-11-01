import { request } from '../../services/api'
import type { Job } from '../../types'
import type { CharacterCreate, CharacterMatch, CustomCharacter, ReferenceChange } from './types'

const path = (id: string) => `/api/characters/${encodeURIComponent(id)}`
const json = (method: string, body: unknown) => ({
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

export const characterApi = {
  create: (body: CharacterCreate) =>
    request<CustomCharacter>('/api/characters', json('POST', body)),
  detail: (id: string, signal?: AbortSignal) => request<CustomCharacter>(path(id), { signal }),
  update: (id: string, body: { name: string; description: string; collection_id?: string }) =>
    request<CustomCharacter>(path(id), json('PATCH', body)),
  delete: (id: string) => request<{ id: string; deleted: boolean }>(path(id), { method: 'DELETE' }),
  addReferences: (id: string, files: File[]) => {
    const body = new FormData()
    files.forEach((file) => body.append('files', file))
    return request<ReferenceChange>(`${path(id)}/references`, { method: 'POST', body })
  },
  removeReference: (id: string, reference: string) =>
    request<ReferenceChange>(`${path(id)}/references/${encodeURIComponent(reference)}`, {
      method: 'DELETE',
    }),
  replaceReference: (id: string, reference: string, file: File) => {
    const body = new FormData()
    body.append('file', file)
    return request<ReferenceChange>(
      `${path(id)}/references/${encodeURIComponent(reference)}/replace`,
      { method: 'POST', body }
    )
  },
  recognize: (id: string) => request<Job>(`${path(id)}/recognize`, { method: 'POST' }),
  matches: (id: string, signal?: AbortSignal, offset = 0) =>
    request<CharacterMatch[]>(`${path(id)}/matches?limit=100&offset=${offset}`, { signal }),
  review: (id: string, match: string, status: 'accepted' | 'rejected') =>
    request<CharacterMatch>(
      `${path(id)}/matches/${encodeURIComponent(match)}`,
      json('PATCH', { status })
    ),
}

export function validateReferenceFiles(files: File[], existing = 0): string {
  if (files.length + existing > 5) return 'A character can have at most five reference images.'
  for (const file of files) {
    if (!/^image\/(jpeg|png|webp)$/.test(file.type) || !/\.(jpe?g|png|webp)$/i.test(file.name))
      return 'Choose JPEG, PNG or WebP reference images.'
    if (file.size === 0) return 'This image is empty. Choose another reference.'
    if (file.size > 10 * 1024 * 1024) return 'Each reference image must be 10 MB or smaller.'
  }
  return ''
}
