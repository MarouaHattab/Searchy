import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Check, Copy, LoaderCircle, ScanSearch } from 'lucide-react'
import Markdown from 'react-markdown'
import { Link } from 'react-router'
import { api } from '../../services/api'
import { timestamp } from '../../lib/format'

function useAnswerReveal(text: string) {
  const [visible, setVisible] = useState(text)
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)')
    if (!text || preference.matches) {
      setVisible(text)
      return
    }
    const words = text.match(/\S+\s*/g) ?? []
    const started = performance.now()
    setVisible('')
    const reveal = () => {
      const progress = Math.min(1, (performance.now() - started) / 650)
      setVisible(words.slice(0, Math.ceil(words.length * progress)).join(''))
      if (progress === 1) window.clearInterval(timer)
    }
    const timer = window.setInterval(reveal, 35)
    const showAll = () => {
      if (preference.matches) {
        window.clearInterval(timer)
        setVisible(text)
      }
    }
    preference.addEventListener('change', showAll)
    return () => {
      window.clearInterval(timer)
      preference.removeEventListener('change', showAll)
    }
  }, [text])
  return visible
}

export function AnswerPanel({
  query,
  sceneIds,
  collection,
  characterId,
}: {
  query: string
  sceneIds: string[]
  collection: string
  characterId: string
}) {
  const answer = useQuery({
    queryKey: ['search-answer', query, sceneIds, collection, characterId],
    queryFn: ({ signal }) =>
      api.answer(
        {
          query,
          scene_ids: sceneIds,
          collection_id: collection || undefined,
          character_ids: characterId ? [characterId] : undefined,
        },
        signal
      ),
    retry: false,
    staleTime: 10 * 60_000,
  })
  const text = answer.data?.markdown ?? ''
  const visible = useAnswerReveal(text)
  const [copied, setCopied] = useState(false)
  const [copyError, setCopyError] = useState(false)
  const [expanded, setExpanded] = useState(false)
  useEffect(() => {
    setCopied(false)
    setCopyError(false)
    setExpanded(false)
  }, [text])
  useEffect(() => {
    if (!copied) return
    const timeout = window.setTimeout(() => setCopied(false), 2000)
    return () => window.clearTimeout(timeout)
  }, [copied])
  const links = new Set(answer.data?.citations.map((source) => source.url) ?? [])
  return (
    <section
      className="answer-panel panel"
      aria-labelledby="answer-heading"
      aria-busy={answer.isFetching}
    >
      <div className="answer-heading">
        <span className="answer-mark">
          <ScanSearch size={19} />
        </span>
        <h2 id="answer-heading">Searchy AI</h2>
        <span className="muted small">
          {answer.isFetching ? 'Preparing explanation' : 'Evidence summary'}
        </span>
        {text && (
          <button
            className="icon-button"
            aria-label={copied ? 'Response copied' : 'Copy response'}
            onClick={() => {
              void navigator.clipboard
                .writeText(text)
                .then(() => {
                  setCopied(true)
                  setCopyError(false)
                })
                .catch(() => setCopyError(true))
            }}
          >
            {copied ? <Check size={16} /> : <Copy size={16} />}
          </button>
        )}
      </div>
      {answer.isPending ? (
        <p className="answer-activity" role="status">
          <LoaderCircle size={16} className="spin" /> Preparing an explanation from the retrieved
          evidence…
        </p>
      ) : answer.isError ? (
        <p className="muted">
          The explanation is unavailable. Your scene results are still ready.{' '}
          <button className="text-link" onClick={() => void answer.refetch()}>
            Try again
          </button>
        </p>
      ) : answer.data.status !== 'generated' ? (
        <p className="muted">
          {answer.data.status === 'insufficient_evidence'
            ? 'There is not enough indexed evidence to explain this query reliably.'
            : 'AI explanations are currently unavailable. You can still explore the scene results and their evidence.'}
        </p>
      ) : (
        <>
          <div
            className={`answer-copy ${expanded ? '' : 'answer-copy-collapsed'}`}
            aria-hidden={visible !== text}
          >
            <Markdown
              skipHtml
              allowedElements={[
                'p',
                'strong',
                'em',
                'ul',
                'ol',
                'li',
                'blockquote',
                'code',
                'br',
                'a',
              ]}
              components={{
                a: ({ href, children }) =>
                  href && links.has(href) ? (
                    <Link to={href}>{children}</Link>
                  ) : (
                    <span>{children}</span>
                  ),
              }}
            >
              {visible}
            </Markdown>
          </div>
          <span className="sr-only" role="status">
            {visible === text ? text : ''}
          </span>
          {text.length > 800 && (
            <button
              className="text-link"
              aria-expanded={expanded}
              onClick={() => setExpanded(!expanded)}
            >
              {expanded ? 'Show less' : 'Read full explanation'}
            </button>
          )}
          <div className="answer-sources" aria-label="Supporting scenes">
            {answer.data.citations.map((source, index) => (
              <Link key={source.scene_id} to={`/scenes/${source.scene_id}`} title={source.label}>
                <span>{index + 1}</span>
                {source.label} <span className="muted">{timestamp(source.start)}</span>
              </Link>
            ))}
          </div>
        </>
      )}
      {copyError && (
        <p className="small muted" role="status">
          Copy was unavailable. You can select and copy the explanation text.
        </p>
      )}
      {!!answer.data?.warnings.length && (
        <details className="answer-notes">
          <summary>Evidence and limitations</summary>
          <ul>
            {answer.data.warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      )}
    </section>
  )
}
