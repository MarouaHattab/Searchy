import { useCallback, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { streamAnswer, type AnswerRequest } from '../../services/api'
import type { SearchAnswer } from '../../types'

type PartialAnswer = Pick<SearchAnswer, 'answer' | 'claims' | 'citations'>

export function answerQueryKey(body: AnswerRequest) {
  return [
    'search-answer',
    body.query,
    body.scene_ids.join(','),
    body.collection_id ?? '',
    body.character_ids?.join(',') ?? '',
    body.search_id ?? '',
  ]
}

export function useAnswer(body: AnswerRequest) {
  const client = useQueryClient()
  const key = answerQueryKey(body)
  const signature = JSON.stringify(key)
  const active = useRef(signature)
  active.current = signature
  const controller = useRef<AbortController | null>(null)
  const [draft, setDraft] = useState<{ key: string; value: PartialAnswer } | null>(null)
  const [stopped, setStopped] = useState('')
  const result = useQuery({
    queryKey: key,
    queryFn: async ({ signal }) => {
      const request = new AbortController()
      controller.current = request
      return streamAnswer(
        body,
        {
          onDelta: (value) => {
            if (active.current === signature && !request.signal.aborted)
              setDraft({ key: signature, value })
          },
        },
        AbortSignal.any([signal, request.signal])
      )
    },
    enabled: !!body.query && !!body.scene_ids.length && stopped !== signature,
    retry: false,
    staleTime: Infinity,
    gcTime: 60 * 60_000,
  })
  const cancel = useCallback(() => {
    setStopped(signature)
    controller.current?.abort()
    void client.cancelQueries({ queryKey: key })
  }, [client, signature])
  return {
    answer: result.data,
    partial: draft?.key === signature ? draft.value : undefined,
    pending: result.isFetching && !result.data,
    failed: result.isError,
    stopped: stopped === signature,
    cancel,
    retry: () => {
      setStopped('')
      void result.refetch()
    },
  }
}
