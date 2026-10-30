export const count = (value: number) => new Intl.NumberFormat().format(value)

export function timestamp(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds)) return 'Unknown'
  const value = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(value / 3600)
  return `${hours ? `${hours}:` : ''}${String(Math.floor(value / 60) % 60).padStart(2, '0')}:${String(value % 60).padStart(2, '0')}`
}

export function episodeTitle(value: string | null | undefined): string {
  if (!value) return 'Uploaded video'
  const match = value.match(/(?:s)?(\d{1,2})(?:x|e)(\d{1,2})/i)
  return match ? `Season ${Number(match[1])} · Episode ${Number(match[2])}` : value
}

export function sceneTitle(value: string | null | undefined): string {
  return value?.replace(/^(?:s)?\d{1,2}(?:x|e)\d{1,2}\s*[-–:]?\s*/i, '').trim() || 'Uploaded video'
}

export function excerpt(value: string, limit = 180): string {
  const cleaned = value
    .replace(/^\s*#{1,6}\s*\*{0,2}[^\n]*?:\*{0,2}\s*$/gm, '')
    .replace(/[#*_`]/g, '')
    .replace(/\uFFFD/g, '')
    .replace(/\s+/g, ' ')
    .trim()
  return cleaned.length > limit ? `${cleaned.slice(0, limit).trimEnd()}…` : cleaned
}

export function dateTime(unix: number): string {
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(unix * 1000))
}

export function humanize(value: string): string {
  const text = value.replace(/[_-]/g, ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

export function message(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
