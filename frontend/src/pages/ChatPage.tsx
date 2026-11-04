import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  BookOpen,
  Clock,
  FileText,
  Info,
  Loader2,
  MessageSquare,
  Play,
  Plus,
  Sparkles,
  Trash2,
  Users,
  X,
} from 'lucide-react'
import {
  api,
  deleteConversation,
  listConversations,
  loadConversation,
  streamChat,
  type ChatSource,
} from '../services/api'
import type { SceneDetail } from '../types'
import { RichText } from '../components/RichText'
import '../styles/chat.css'

interface Turn {
  role: 'user' | 'assistant'
  text: string
  sources?: ChatSource[]
  pending?: boolean
  model?: string | null
}

const EXAMPLES = [
  "How does Ross's relationship with Rachel evolve?",
  'What is Rachel wearing in the coffee shop?',
  'What happens when Rachel loses Marcel?',
]

function stamp(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return '--:--'
  const total = Math.max(0, Math.round(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function ChatPage() {
  const client = useQueryClient()
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState('')
  const [conversation, setConversation] = useState<string | undefined>(undefined)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [playing, setPlaying] = useState<ChatSource | null>(null)
  const abort = useRef<AbortController | null>(null)
  const scroller = useRef<HTMLDivElement | null>(null)
  const input = useRef<HTMLTextAreaElement | null>(null)

  const conversations = useQuery({
    queryKey: ['chat-conversations'],
    queryFn: () => listConversations(),
    staleTime: 10_000,
  })

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight, behavior: 'smooth' })
  }, [turns])

  const openConversation = useCallback(async (id: string) => {
    abort.current?.abort()
    setError('')
    setBusy(false)
    setPlaying(null)
    try {
      const data = await loadConversation(id)
      setConversation(id)
      setTurns(
        data.messages.map((message) => ({
          role: message.role,
          text: message.content,
          sources: message.data?.sources,
          model: message.data?.model,
        }))
      )
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'That conversation could not be opened.')
    }
  }, [])

  const startNew = () => {
    abort.current?.abort()
    setTurns([])
    setConversation(undefined)
    setPlaying(null)
    setError('')
    setBusy(false)
    input.current?.focus()
  }

  const remove = async (id: string) => {
    await deleteConversation(id)
    void client.invalidateQueries({ queryKey: ['chat-conversations'] })
    if (id === conversation) startNew()
  }

  const handleCitationClick = useCallback((sources: ChatSource[] | undefined, citationNum: number) => {
    if (!sources || !sources.length) return
    const match = sources.find((s) => s.number === citationNum)
    if (match) {
      setPlaying(match)
    }
  }, [])

  const send = useCallback(
    async (question: string) => {
      const text = question.trim()
      if (!text || busy) return
      setError('')
      setBusy(true)
      setDraft('')
      setPlaying(null)
      setTurns((current) => [
        ...current,
        { role: 'user', text },
        { role: 'assistant', text: '', pending: true },
      ])
      const controller = new AbortController()
      abort.current = controller
      try {
        const reply = await streamChat(
          { question: text, conversation_id: conversation },
          {
            onSources: (sources) =>
              setTurns((current) => {
                const next = [...current]
                for (let i = next.length - 1; i >= 0; i -= 1) {
                  if (next[i].role === 'assistant') {
                    next[i] = { ...next[i], sources }
                    break
                  }
                }
                return next
              }),
            onDelta: (chunk) =>
              setTurns((current) => {
                const next = [...current]
                const last = next.length - 1
                if (last >= 0 && next[last].role === 'assistant')
                  next[last] = { ...next[last], text: next[last].text + chunk }
                return next
              }),
          },
          controller.signal
        )
        setConversation(reply.conversation_id)
        setTurns((current) => {
          const next = [...current]
          const last = next.length - 1
          if (last >= 0 && next[last].role === 'assistant')
            next[last] = {
              role: 'assistant',
              text: reply.answer,
              sources: reply.sources,
              model: reply.model,
            }
          return next
        })
        void client.invalidateQueries({ queryKey: ['chat-conversations'] })
      } catch (cause) {
        if ((cause as Error).name === 'AbortError') return
        setError(cause instanceof Error ? cause.message : 'The chat could not answer.')
        setTurns((current) => current.filter((turn) => !turn.pending))
      } finally {
        setBusy(false)
        abort.current = null
      }
    },
    [busy, conversation, client]
  )

  return (
    <div className={`chat-layout ${playing ? 'with-player' : ''}`}>
      <aside className="chat-history">
        <button className="chat-new" onClick={startNew}>
          <Plus size={15} />
          <span>New chat</span>
        </button>
        <p className="chat-history-heading">Recent</p>
        <div className="chat-history-list">
          {conversations.data?.map((item) => (
            <div
              key={item.id}
              className={`chat-history-item ${item.id === conversation ? 'active' : ''}`}
            >
              <button onClick={() => void openConversation(item.id)}>
                <MessageSquare size={13} />
                <span className="chat-history-title">{item.title || 'Untitled'}</span>
                <small>{Math.max(1, Math.round(item.turns / 2))} messages</small>
              </button>
              <button
                className="chat-history-delete"
                aria-label="Delete conversation"
                onClick={() => void remove(item.id)}
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))}
          {!conversations.data?.length && (
            <p className="chat-history-empty">Your conversations appear here.</p>
          )}
        </div>
      </aside>

      <section className="chat-main">
        <div className="chat-thread" ref={scroller}>
          {!turns.length && (
            <div className="chat-welcome">
              <div className="chat-welcome-mark">
                <Sparkles size={20} />
              </div>
              <h2>Ask about Friends Season 1</h2>
              <p>
                Answers are rigorously grounded in indexed scenes and episode milestones.
                Click on any citation like <code>[1]</code> or source card below to inspect the video,
                full dialogue transcript, or narrative milestone.
              </p>
              <div className="chat-examples">
                {EXAMPLES.map((example) => (
                  <button key={example} onClick={() => void send(example)}>
                    {example}
                  </button>
                ))}
              </div>
            </div>
          )}

          {turns.map((turn, index) =>
            turn.role === 'user' ? (
              <div className="chat-turn chat-user" key={index}>
                <div className="chat-bubble">
                  <p>{turn.text}</p>
                </div>
              </div>
            ) : (
              <div className="chat-turn chat-assistant" key={index}>
                <div className="chat-avatar" aria-hidden>
                  <Sparkles size={13} />
                </div>
                <div className="chat-body">
                  <div
                    className={`chat-answer ${turn.pending && !turn.text ? 'chat-typing' : ''}`}
                  >
                    {turn.pending && !turn.text ? (
                      <span className="chat-thinking">
                        <Loader2 size={13} className="spin" />
                        Searching scenes and episode milestones…
                      </span>
                    ) : (
                      <>
                        <RichText
                          text={turn.text || 'No answer was produced.'}
                          onCitationClick={(num) => handleCitationClick(turn.sources, num)}
                        />
                        {turn.pending && <span className="chat-caret" aria-hidden />}
                      </>
                    )}
                  </div>
                  {!!turn.sources?.length && (
                    <SourceList
                      sources={turn.sources}
                      playing={playing}
                      onPlay={setPlaying}
                      key={index}
                    />
                  )}
                </div>
              </div>
            )
          )}

          {!!error && (
            <div className="chat-error">
              <Info size={14} />
              <span>{error}</span>
            </div>
          )}
        </div>

        <form
          className="chat-compose"
          onSubmit={(event) => {
            event.preventDefault()
            void send(draft)
          }}
        >
          <textarea
            ref={input}
            value={draft}
            rows={1}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                void send(draft)
              }
            }}
            placeholder={busy ? 'Answering…' : 'Ask about a scene, a relationship, a line…'}
            aria-label="Ask a question"
            disabled={busy}
          />
          <button type="submit" disabled={!draft.trim() || busy} aria-label="Send question">
            {busy ? <Loader2 size={15} className="spin" /> : <ArrowUp size={16} />}
          </button>
        </form>
      </section>

      {playing && (
        <aside className="chat-player">
          {playing.scene_id ? (
            <SceneDetailPanel source={playing} onClose={() => setPlaying(null)} />
          ) : (
            <MilestoneSummaryPanel source={playing} onClose={() => setPlaying(null)} />
          )}
        </aside>
      )}
    </div>
  )
}

function SourceList({
  sources,
  playing,
  onPlay,
}: {
  sources: ChatSource[]
  playing: ChatSource | null
  onPlay: (source: ChatSource) => void
}) {
  const [open, toggle] = useReducer((value: boolean) => !value, false)
  const unique = sources.filter(
    (source, index) =>
      !source.scene_id ||
      sources.findIndex((other) => other.scene_id === source.scene_id) === index
  )
  const shown = open ? unique : unique.slice(0, 4)

  return (
    <div className="chat-sources">
      <button className="chat-sources-toggle" onClick={toggle} aria-expanded={open}>
        <span>
          {unique.length} evidence source{unique.length === 1 ? '' : 's'}
        </span>
        <span className="chat-sources-caret" aria-hidden>
          {open ? '▴' : '▾'}
        </span>
      </button>
      <div className="chat-source-list">
        {shown.map((source) => {
          const isMilestone = !source.scene_id || source.timestamp_basis === 'summary'
          const isSelected =
            playing &&
            (playing.number === source.number ||
              (source.scene_id && playing.scene_id === source.scene_id))

          return (
            <button
              key={`${source.scene_id || 'summary'}-${source.number}`}
              className={`chat-source ${isSelected ? 'active' : ''} ${isMilestone ? 'summary' : ''}`}
              onClick={() => onPlay(source)}
              title={isMilestone ? `View Episode Milestone: ${source.label}` : `Watch Scene: ${source.label}`}
            >
              <span className="chat-source-number">{source.number}</span>
              <span className="chat-source-body">
                <strong>{source.label.replace(/^Episode Milestone:\s*/i, '')}</strong>
                <small>
                  {isMilestone ? (
                    <span className="chat-source-type-pill">
                      <BookOpen size={9} /> Milestone Summary
                    </span>
                  ) : (
                    <span className="chat-source-time-pill">
                      <Play size={8} /> {stamp(source.start)} – {stamp(source.end)}
                    </span>
                  )}
                </small>
              </span>
            </button>
          )
        })}
        {!open && unique.length > 4 && (
          <button className="chat-source more" onClick={toggle}>
            +{unique.length - 4} more
          </button>
        )}
      </div>
    </div>
  )
}

function MilestoneSummaryPanel({
  source,
  onClose,
}: {
  source: ChatSource
  onClose: () => void
}) {
  const title = source.label.replace(/^Episode Milestone:\s*/i, '')
  const summaryText = source.description || source.snippet

  return (
    <div className="chat-milestone-panel">
      <header className="chat-sidebar-header">
        <div>
          <div className="chat-milestone-tag">
            <BookOpen size={12} />
            <span>Episode Milestone</span>
          </div>
          <strong className="chat-sidebar-title">{title}</strong>
        </div>
        <button className="chat-sidebar-close" aria-label="Close panel" onClick={onClose}>
          <X size={15} />
        </button>
      </header>

      <div className="chat-milestone-content">
        <div className="chat-milestone-section">
          <h4>Narrative Milestone & Arc</h4>
          <p className="chat-milestone-body">{summaryText}</p>
        </div>

        <div className="chat-milestone-tip">
          <Sparkles size={14} />
          <span>
            This macro milestone anchors the canonical Season 1 timeline and character arcs across episodes.
          </span>
        </div>
      </div>
    </div>
  )
}

function SceneDetailPanel({
  source,
  onClose,
}: {
  source: ChatSource
  onClose: () => void
}) {
  const [detail, setDetail] = useState<SceneDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState<'dialogue' | 'visuals'>('dialogue')
  const videoRef = useRef<HTMLVideoElement | null>(null)

  useEffect(() => {
    let alive = true
    setLoading(true)
    api
      .scene(source.scene_id)
      .then((data) => {
        if (alive) {
          setDetail(data)
          setLoading(false)
        }
      })
      .catch(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [source.scene_id])

  const seekTo = (seconds: number | null) => {
    if (videoRef.current && seconds != null) {
      videoRef.current.currentTime = seconds
      void videoRef.current.play()
    }
  }

  const mediaUrl = `/api/scenes/${encodeURIComponent(source.scene_id)}/media`

  return (
    <div className="chat-scene-panel">
      <header className="chat-sidebar-header">
        <div>
          <strong className="chat-sidebar-title">{source.label}</strong>
          <small className="chat-sidebar-time">
            <Clock size={11} /> {stamp(source.start)} – {stamp(source.end)}
          </small>
        </div>
        <button className="chat-sidebar-close" aria-label="Close player" onClick={onClose}>
          <X size={15} />
        </button>
      </header>

      <div className="chat-video-container">
        <video
          ref={videoRef}
          key={source.scene_id}
          controls
          autoPlay
          src={`${mediaUrl}#t=${source.start ?? 0}`}
          onLoadedMetadata={(event) => {
            if (source.start != null) event.currentTarget.currentTime = source.start
          }}
        />
      </div>

      {detail?.characters && detail.characters.length > 0 && (
        <div className="chat-scene-meta-row">
          <span className="chat-scene-meta-title">
            <Users size={12} /> Present:
          </span>
          <div className="chat-char-pill-list">
            {detail.characters.map((char) => (
              <span key={char} className="chat-char-pill">
                {char}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="chat-sidebar-tabs">
        <button
          className={`chat-tab-btn ${activeTab === 'dialogue' ? 'active' : ''}`}
          onClick={() => setActiveTab('dialogue')}
        >
          <MessageSquare size={13} />
          <span>Dialogue ({detail?.dialogue?.length ?? 0})</span>
        </button>
        <button
          className={`chat-tab-btn ${activeTab === 'visuals' ? 'active' : ''}`}
          onClick={() => setActiveTab('visuals')}
        >
          <FileText size={13} />
          <span>Scene Details</span>
        </button>
      </div>

      <div className="chat-sidebar-tab-content">
        {loading ? (
          <div className="chat-sidebar-loading">
            <Loader2 size={16} className="spin" />
            <span>Loading scene details…</span>
          </div>
        ) : activeTab === 'dialogue' ? (
          <div className="chat-dialogue-list">
            {detail?.dialogue && detail.dialogue.length > 0 ? (
              detail.dialogue.map((line, idx) => (
                <div className="chat-dialogue-row" key={`${line.start}-${idx}`}>
                  <button
                    className="chat-dialogue-seek-btn"
                    onClick={() => seekTo(line.start)}
                    title={`Jump to ${stamp(line.start)}`}
                  >
                    <Play size={9} />
                    <span>{stamp(line.start)}</span>
                  </button>
                  <div className="chat-dialogue-text-block">
                    <strong className="chat-dialogue-speaker">
                      {line.speaker || 'UNKNOWN'}:
                    </strong>
                    <span className="chat-dialogue-line">{line.text}</span>
                  </div>
                </div>
              ))
            ) : (
              <p className="chat-sidebar-empty">No dialogue transcribed for this moment.</p>
            )}
          </div>
        ) : (
          <div className="chat-visuals-panel">
            {detail?.scene_summary && (
              <div className="chat-visuals-section">
                <h5>Scene Summary</h5>
                <p>{detail.scene_summary}</p>
              </div>
            )}
            {detail?.description && (
              <div className="chat-visuals-section">
                <h5>Visual Setting & Action</h5>
                <p>{detail.description.replace(/[#*_`]+/g, ' ').trim()}</p>
              </div>
            )}
            {detail?.observations && detail.observations.length > 0 && (
              <div className="chat-visuals-section">
                <h5>Visual Observations ({detail.observations.length})</h5>
                <div className="chat-observations-list">
                  {detail.observations.map((obs, idx) => (
                    <div key={idx} className="chat-obs-row">
                      <span className="chat-obs-kind">{obs.kind}</span>
                      <span className="chat-obs-val">{obs.evidence || obs.value}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {!detail?.description && !detail?.scene_summary && (!detail?.observations || detail.observations.length === 0) && (
              <p className="chat-sidebar-empty">
                {source.snippet.replace(/[#*_`]+/g, ' ').trim()}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
