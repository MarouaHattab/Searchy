import { useCallback, useEffect, useReducer, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUp,
  Clock,
  Info,
  Loader2,
  MessageSquare,
  Plus,
  Sparkles,
  Trash2,
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
  'What is Rachel wearing in the coffee shop?',
  'Which episodes have Gunther?',
  'Who argued at the table in the first episode?',
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
              <h2>Ask about your collection</h2>
              <p>
                Answers come only from indexed scenes, and every reply lists the moments it
                used with their exact times.
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
                        Searching scenes…
                      </span>
                    ) : (
                      <>
                        <RichText text={turn.text || 'No answer was produced.'} />
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
            placeholder={busy ? 'Answering…' : 'Ask about a scene, a costume, a line…'}
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
          <header>
            <div>
              <strong>{playing.label}</strong>
              <small>
                <Clock size={10} /> {stamp(playing.start)} – {stamp(playing.end)}
              </small>
            </div>
            <button aria-label="Close player" onClick={() => setPlaying(null)}>
              <X size={14} />
            </button>
          </header>
          <SourcePlayer source={playing} />
          <p className="chat-player-note">
            {playing.snippet.replace(/[#*_`]+/g, ' ').replace(/\s+/g, ' ').trim()}
          </p>
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
  const playable = unique.filter((source) => source.scene_id)
  const shown = open ? unique : unique.slice(0, 4)

  return (
    <div className="chat-sources">
      <button className="chat-sources-toggle" onClick={toggle} aria-expanded={open}>
        <span>
          {playable.length} source{playable.length === 1 ? '' : 's'}
        </span>
        <span className="chat-sources-caret" aria-hidden>
          {open ? '▴' : '▾'}
        </span>
      </button>
      <div className="chat-source-list">
        {shown.map((source) => (
          <button
            key={`${source.scene_id}-${source.number}`}
            className={`chat-source ${playing?.scene_id === source.scene_id ? 'active' : ''} ${!source.scene_id ? 'summary' : ''}`}
            onClick={() => source.scene_id && onPlay(source)}
            disabled={!source.scene_id}
            title={source.label}
          >
            <span className="chat-source-number">{source.number}</span>
            <span className="chat-source-body">
              <strong>{source.label}</strong>
              <small>
                {source.scene_id ? `${stamp(source.start)} – ${stamp(source.end)}` : 'summary'}
              </small>
            </span>
          </button>
        ))}
        {!open && unique.length > 4 && (
          <button className="chat-source more" onClick={toggle}>
            +{unique.length - 4}
          </button>
        )}
      </div>
    </div>
  )
}

function SourcePlayer({ source }: { source: ChatSource }) {
  const [url, setUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    setUrl(null)
    setFailed(false)
    api
      .scene(source.scene_id)
      .then(() => alive && setUrl(`/api/scenes/${source.scene_id}/media`))
      .catch(() => alive && setFailed(true))
    return () => {
      alive = false
    }
  }, [source.scene_id])

  if (failed) return <p className="chat-player-error">Source media is unavailable.</p>
  if (!url)
    return (
      <div className="chat-player-loading">
        <Loader2 size={16} className="spin" />
      </div>
    )
  return (
    <video
      key={source.scene_id}
      controls
      autoPlay
      src={`${url}#t=${source.start ?? 0}`}
      onLoadedMetadata={(event) => {
        if (source.start != null) event.currentTarget.currentTime = source.start
      }}
    />
  )
}
