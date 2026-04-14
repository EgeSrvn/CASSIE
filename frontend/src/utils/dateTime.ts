const SERVER_TIMESTAMP_WITHOUT_TIMEZONE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?$/
const SERVER_TIMESTAMP_WITH_TIMEZONE = /[zZ]|[+-]\d{2}:\d{2}$/

const getBrowserTimeZone = (): string | undefined => {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
  } catch {
    return undefined
  }
}

export const parseServerDate = (value?: string | null): Date | null => {
  if (!value) return null

  const normalized = value.trim()
  if (!normalized) return null

  if (SERVER_TIMESTAMP_WITH_TIMEZONE.test(normalized)) {
    const parsed = new Date(normalized)
    return Number.isNaN(parsed.getTime()) ? null : parsed
  }

  const match = normalized.match(SERVER_TIMESTAMP_WITHOUT_TIMEZONE)
  if (match) {
    const [, year, month, day, hour, minute, second, fractional = '0'] = match
    const milliseconds = Number(fractional.slice(0, 3).padEnd(3, '0'))
    const parsedUtc = new Date(Date.UTC(
      Number(year),
      Number(month) - 1,
      Number(day),
      Number(hour),
      Number(minute),
      Number(second),
      milliseconds
    ))
    return Number.isNaN(parsedUtc.getTime()) ? null : parsedUtc
  }

  const parsed = new Date(normalized)
  return Number.isNaN(parsed.getTime()) ? null : parsed
}

export const formatLocalDateTime = (value?: string | null): string => {
  const parsed = parseServerDate(value)
  if (!parsed) return '-'

  const browserTimeZone = getBrowserTimeZone()
  return new Intl.DateTimeFormat(undefined, {
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
    second: '2-digit',
    ...(browserTimeZone ? { timeZone: browserTimeZone } : {}),
  }).format(parsed)
}

export const getDurationMs = (start?: string | null, end?: string | null): number | null => {
  const startDate = parseServerDate(start)
  if (!startDate) return null

  const endDate = end ? parseServerDate(end) : new Date()
  if (!endDate) return null

  return Math.max(0, endDate.getTime() - startDate.getTime())
}

export const formatDurationClock = (start?: string | null, end?: string | null): string | null => {
  const durationMs = getDurationMs(start, end)
  if (durationMs === null) return null

  const totalSeconds = Math.floor(durationMs / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  return [hours, minutes, seconds].map(value => String(value).padStart(2, '0')).join(':')
}
