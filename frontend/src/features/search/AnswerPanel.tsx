import { useState } from 'react'
import { Check, Copy, LoaderCircle, ScanSearch, Square } from 'lucide-react'
import { Link } from 'react-router'
import { sceneHref } from '../player/navigation'
import type { useAnswer } from './useAnswer'

export function AnswerPanel({
  state,
  origin,
  onOpen,
  retrievalWarnings,
}: {
  state: ReturnType<typeof useAnswer>
  origin: string
  onOpen: () => void
  retrievalWarnings: string[]
}) {
  const { answer, partial, pending, failed, stopped, cancel, retry } = state
  const [copied, setCopied] = useState(false)
  const content = pending ? partial : (answer ?? partial)
  const warnings = [
    ...new Set([...(pending ? [] : (answer?.warnings ?? [])), ...retrievalWarnings]),
  ]
  if (!content && !pending && !failed && !stopped) return null
  return (
    <section className="answer-panel" aria-labelledby="answer-heading" aria-busy={pending}>
      <header className="answer-heading">
        <span className="answer-mark" aria-hidden="true">
          <ScanSearch size={16} />
        </span>
        <h2 id="answer-heading">Searchy AI</h2>
        <span className="answer-meta">
          {pending
            ? 'Checking evidence'
            : answer?.retrieval.graph_used
              ? 'Graph + scene evidence'
              : 'Scene evidence'}
        </span>
        {pending && (
          <button className="answer-action" onClick={cancel} aria-label="Stop answer generation">
            <Square size={14} />
          </button>
        )}
        {!!content?.answer && (
          <button
            className="answer-action"
            aria-label={copied ? 'Answer copied' : 'Copy answer'}
            onClick={() => {
              void navigator.clipboard
                .writeText(content.answer)
                .then(() => setCopied(true))
                .catch(() => undefined)
            }}
          >
            {copied ? <Check size={15} /> : <Copy size={15} />}
          </button>
        )}
      </header>
      {content?.claims.map((claim, index) => (
        <p className="answer-copy answer-reveal" key={`${index}-${claim.text}`}>
          {claim.text}{' '}
          {claim.scene_ids.map((id) => {
            const citation = content.citations.find((c) => c.scene_id === id)
            if (!citation) return null
            return (
              <Link
                key={id}
                className="answer-inline-citation"
                to={sceneHref(id, citation.start, origin)}
                onClick={onOpen}
                title={citation.episode_id ?? citation.label}
              >
                {citation.label}
              </Link>
            )
          })}
        </p>
      ))}
      {pending && (
        <p className="answer-activity" role="status">
          <LoaderCircle size={14} className="spin" />
          {content?.claims.length
            ? 'Checking the next supporting statement…'
            : 'Reading scene and graph evidence…'}
        </p>
      )}
      {(failed || stopped || answer?.status === 'unavailable') && (
        <p className="answer-fallback">
          {stopped ? 'Generation stopped.' : 'The explanation was interrupted.'} Your scene results
          are still available.{' '}
          <button className="text-link" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {answer?.status === 'insufficient_evidence' && (
        <p className="answer-fallback">
          The retrieved evidence does not support an answer to this question. Explore the possible
          matches below or refine your question.
        </p>
      )}
      {!!warnings.length && (
        <details className="answer-evidence">
          <summary>Evidence details · {warnings.length} limitations</summary>
          <ul className="answer-notes">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
