import { queryOptions } from '@tanstack/react-query'
import { api } from './api'

export const workspaceQuery = queryOptions({
  queryKey: ['workspace'],
  queryFn: ({ signal }) => api.workspace(signal),
  refetchInterval: 15_000,
})
export const jobsQuery = queryOptions({
  queryKey: ['jobs'],
  queryFn: ({ signal }) => api.jobs(signal),
  refetchInterval: 5_000,
})
export const charactersQuery = queryOptions({
  queryKey: ['characters'],
  queryFn: ({ signal }) => api.characters(signal),
  staleTime: 60_000,
})
export const readinessQuery = queryOptions({
  queryKey: ['readiness'],
  queryFn: ({ signal }) => api.readiness(signal),
  refetchInterval: 30_000,
  retry: false,
})
