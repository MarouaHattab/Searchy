import { useState } from 'react'
import { Check, Copy, LoaderCircle, ScanSearch, Square } from 'lucide-react'
import { Link } from 'react-router'
import { excerpt, timestamp } from '../../lib/format'
import { sceneHref } from '../player/navigation'
import type { useAnswer } from './useAnswer'

export function AnswerPanel({
  state,
  origin,
  onOpen,
  onCite,
  onFollowUp,
  onDismiss,
  followPending = false,
  followError = '',
  title = 'Searchy AI',
  retrievalWarnings,
}: {
  state: ReturnType<typeof useAnswer>
  origin: string
  onOpen: () => void
  onCite?: (sceneId: string) => void
  onFollowUp?: (question: string) => void
  onDismiss?: () => void
  followPending?: boolean
  followError?: string
  title?: string
  retrievalWarnings: string[]
}) {
  const { answer, partial, pending, failed, stopped, cancel, retry } = state
  const [copied, setCopied] = useState(false)
  const [followDraft, setFollowDraft] = useState('')
  const content = pending ? partial : (answer ?? partial)
  const warnings = [
    ...new Set([...(pending ? [] : (answer?.warnings ?? [])), ...retrievalWarnings]),
  ]
  const retrieval = answer?.retrieval
  if (!content && !pending && !failed && !stopped) return null
  return (
    <section className="answer-panel" aria-labelledby={`${title}-heading`} aria-busy={pending}>
      <header className="answer-heading">
        <span className="answer-mark" aria-hidden="true">
          <ScanSearch size={16} />
        </span>
        <h2 id={`${title}-heading`}>{title}</h2>
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
                onClick={() => {
                  onCite?.(id)
                  onOpen()
                }}
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
      {(failed || stopped) && (
        <p className="answer-fallback">
          {stopped ? 'Generation stopped.' : 'The explanation was interrupted.'} Your scene results
          are still available.{' '}
          <button className="text-link" onClick={retry}>
            Try again
          </button>
        </p>
      )}
      {answer?.status === 'unavailable' && (
        <p className="answer-fallback">
          {answer.warnings.find((warning) => /provider|unusable|unavailable/i.test(warning)) ??
            'An explanation could not be generated from the retrieved evidence.'}{' '}
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
      {!!answer?.evidence.length && (
        <details className="answer-evidence">
          <summary>Supporting evidence · {answer.evidence.length}</summary>
          {answer.evidence.slice(0, 6).map((item) => (
            <blockquote key={item.evidence_id}>
              {excerpt(item.text, 320)}
              <button type="button" className="text-link" onClick={() => onCite?.(item.scene_id)}>
                Show in graph
              </button>
            </blockquote>
          ))}
        </details>
      )}
      {!!answer?.relationships.length && (
        <details className="answer-evidence">
          <summary>Graph relationships</summary>
          <ul className="answer-notes answer-relationship-list">
            {answer.relationships.flatMap((item) =>
              item.links.map((link, index) => (
                <li key={`${item.scene_id}:${link.source}:${link.target}:${index}`}>
                  <span>
                    <strong>{link.source}</strong> {link.relation} <strong>{link.target}</strong>
                  </span>
                  {link.evidence[0] && <small>{excerpt(link.evidence[0], 220)}</small>}
                  <small>
                    {link.start != null && link.end != null
                      ? `${timestamp(link.start)} – ${timestamp(link.end)}`
                      : 'No exact interval recorded'}
                    {' · '}
                    {link.verified === true
                      ? 'Source marked verified'
                      : link.verified === false
                        ? 'Unverified source record'
                        : 'Verification not recorded'}
                  </small>
                  <span className="answer-relationship-actions">
                    <button
                      type="button"
                      className="text-link"
                      onClick={() => onCite?.(item.scene_id)}
                    >
                      Show in graph
                    </button>
                    <Link
                      className="text-link"
                      to={sceneHref(item.scene_id, link.start, origin)}
                      onClick={onOpen}
                    >
                      {link.start == null ? 'Open scene' : `Play at ${timestamp(link.start)}`}
                    </Link>
                  </span>
                </li>
              ))
            )}
          </ul>
        </details>
      )}
      {!!answer?.constraints.length && (
        <details className="answer-evidence">
          <summary>Evidence assessment</summary>
          <ul className="answer-notes">
            {answer.constraints.map((item) => (
              <li key={item.label}>
                {item.supported ? 'Supported' : 'Not fully supported'} — {item.label}. {item.detail}
              </li>
            ))}
          </ul>
        </details>
      )}
      {!!warnings.length && (
        <details className="answer-evidence">
          <summary>Limitations · {warnings.length}</summary>
          <ul className="answer-notes">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </details>
      )}
      {retrieval && (
        <details className="answer-evidence">
          <summary>How this answer was retrieved</summary>
          <dl className="answer-retrieval">
            <div>
              <dt>Strategy</dt>
              <dd>{retrieval.strategy}</dd>
            </div>
            <div>
              <dt>Prompt</dt>
              <dd>{retrieval.prompt_version ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Graph schema</dt>
              <dd>{retrieval.graph_schema ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Embedding model</dt>
              <dd>{retrieval.embedding_model ?? 'Not recorded'}</dd>
            </div>
            <div>
              <dt>Answer model</dt>
              <dd>
                {retrieval.llm_provider ?? answer?.provider ?? 'Not recorded'}
                {retrieval.llm_model || answer?.model
                  ? ` / ${retrieval.llm_model ?? answer?.model}`
                  : ''}
              </dd>
            </div>
            <div>
              <dt>Retrieved scenes</dt>
              <dd>{retrieval.scene_ids?.length ?? answer?.citations.length ?? 0}</dd>
            </div>
            {retrieval.elapsed_ms != null && (
              <div>
                <dt>Preparation</dt>
                <dd>{retrieval.elapsed_ms} ms</dd>
              </div>
            )}
          </dl>
        </details>
      )}
      {onFollowUp && !pending && (
        <form
          className="answer-follow"
          onSubmit={(event) => {
            event.preventDefault()
            const question = followDraft.trim()
            if (!question || followPending) return
            onFollowUp(question)
            setFollowDraft('')
          }}
        >
          <label>
            <span className="sr-only">Follow-up question</span>
            <input
              value={followDraft}
              maxLength={240}
              placeholder="Ask a follow-up about this evidence"
              onChange={(event) => setFollowDraft(event.target.value)}
            />
          </label>
          <button className="text-link" disabled={followPending || !followDraft.trim()}>
            {followPending ? 'Searching…' : 'Ask'}
          </button>
        </form>
      )}
      {!!followError && <p className="answer-fallback">{followError}</p>}
      {onDismiss && (
        <button className="text-link" onClick={onDismiss}>
          Return to the original answer
        </button>
      )}
    </section>
  )
}
