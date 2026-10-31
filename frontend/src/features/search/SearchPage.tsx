import { lazy, Suspense, useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowRight, Check, Clock3, Search, SlidersHorizontal, X } from 'lucide-react'
import { useNavigate } from 'react-router'
import { SceneCard } from '../../components/SceneCard'
import { Button, EmptyState, ErrorState, SectionHeading } from '../../components/ui'
import { api, ApiError } from '../../services/api'
import { charactersQuery, workspaceQuery } from '../../services/queries'
import { AnswerPanel } from './AnswerPanel'
import { answerQueryKey, useAnswer } from './useAnswer'
import { rankingOf, useResultScroll } from './state'
import {
  canonicalSearch,
  clearSearch,
  rememberOrigin,
  rememberSearch,
  searchDestination,
} from '../player/navigation'
import '../../styles/exploration.css'

function collectionLabel(id: string) {
  return id
    .split(/[-_]/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

const EvidenceGraph = lazy(() => import('../graph/EvidenceGraph'))

const suggestions = [
  'Rachel wearing a wedding dress',
  'Phoebe playing guitar',
  'A conversation between Ross and Rachel',
]

export default function SearchPage({ href, frozen = false }: { href: string; frozen?: boolean }) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const params = useMemo(() => new URLSearchParams(href.split('?')[1] ?? ''), [href])
  const query = params.get('q')?.trim() ?? ''
  const collection = params.get('collection') ?? ''
  const character = params.get('character') ?? ''
  const characterId = params.get('character_id') ?? ''
  const limit = Math.min(100, Math.max(12, Number(params.get('limit')) || 12))
  const [draft, setDraft] = useState(query)
  const playable = params.get('playable') === '1'
  const setPlayable = (value: boolean) => update({ playable: value ? '1' : '' })
  const [waiting, setWaiting] = useState(false)
  const forceFresh = useRef(false)
  const resultView = params.get('view') === 'graph' ? 'graph' : 'scenes'
  const setResultView = (value: 'scenes' | 'graph') =>
    update({ view: value === 'graph' ? 'graph' : '' }, true)
  const focusSceneId = params.get('focus')
  const setFocusSceneId = (value: string | null) =>
    update({ focus: value ?? '', view: 'graph' }, true)
  const [highlighted, setHighlighted] = useState<string[]>([])
  const workspace = useQuery(workspaceQuery)
  const characters = useQuery(charactersQuery)
  const search = useQuery({
    queryKey: ['search', query, collection, character, characterId, limit],
    queryFn: async ({ signal }) => {
      const body = {
        query,
        limit,
        collection_id: collection || undefined,
        characters: characterId || !character ? undefined : [character],
        character_ids: characterId ? [characterId] : undefined,
      }
      const sid = forceFresh.current ? null : params.get('sid')
      forceFresh.current = false
      if (sid) {
        try {
          const saved = await api.session(sid, signal)
          const savedCharacters = saved.request.character_ids ?? []
          const identityMatches =
            saved.request.query === query &&
            (saved.request.collection_id ?? '') === collection &&
            (saved.request.limit ?? limit) === limit &&
            (savedCharacters[0] ?? '') === characterId &&
            (characterId || (saved.request.characters?.[0] ?? '') === character)
          if (identityMatches) {
            if (saved.answer?.status === 'generated')
              client.setQueryData(
                answerQueryKey({
                  query,
                  scene_ids: saved.response.results.slice(0, 12).map((s) => s.scene_id),
                  collection_id: collection || undefined,
                  character_ids: characterId ? [characterId] : undefined,
                  search_id: saved.response.search_id,
                }),
                saved.answer
              )
            return saved.response
          }
        } catch (error) {
          if (!(error instanceof ApiError) || ![404, 409].includes(error.status)) throw error
        }
      }
      return api.search(body, signal)
    },
    enabled: !!query,
    retry: false,
    staleTime: Infinity,
    gcTime: 60 * 60_000,
  })

  useEffect(() => {
    setDraft(query)
  }, [query])
  const identity = `${query}|${collection}|${character}|${characterId}`
  const sessionId = params.get('sid') ?? ''
  const seenIdentity = useRef<string | null>(null)
  useEffect(() => {
    if (seenIdentity.current === null) {
      seenIdentity.current = identity
      return
    }
    if (seenIdentity.current !== identity) {
      seenIdentity.current = identity
      setHighlighted([])
      if (!sessionId) window.scrollTo(0, 0)
    }
  }, [identity, sessionId])
  useEffect(() => {
    if (frozen) return
    const id = search.data?.search_id
    if (!id || params.get('sid') === id) return
    const next = new URLSearchParams(params)
    next.set('sid', id)
    navigate(canonicalSearch(`/search?${next.toString()}`) ?? '/search', { replace: true })
  }, [frozen, search.data?.search_id, href, navigate, params])
  useEffect(() => {
    setWaiting(false)
    if (!search.isFetching) return
    const timer = window.setTimeout(() => setWaiting(true), 12_000)
    return () => window.clearTimeout(timer)
  }, [search.isFetching])

  function update(values: Record<string, string>, replace = false) {
    if (frozen) return
    const next = new URLSearchParams(params)
    Object.entries(values).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key)
    )
    if (
      Object.keys(values).some((key) =>
        ['q', 'collection', 'character', 'character_id', 'limit'].includes(key)
      )
    ) {
      next.delete('sid')
      next.delete('view')
      next.delete('focus')
    }
    navigate(canonicalSearch(`/search?${next.toString()}`) ?? '/search', { replace })
  }

  const results =
    search.data?.results.filter((scene) => !playable || scene.playback.available) ?? []
  const searchHref = href
  useEffect(() => {
    if (frozen || !query) return
    rememberSearch(searchHref)
    try {
      sessionStorage.removeItem('searchy:expect-return')
    } catch {
      /* The scene URL still carries the search link. */
    }
  }, [frozen, query, searchHref])
  useEffect(() => {
    if (frozen || query) return
    let pending = false
    try {
      pending = sessionStorage.getItem('searchy:expect-return') === '1'
    } catch {
      return
    }
    if (!pending) return
    try {
      sessionStorage.removeItem('searchy:expect-return')
    } catch {
      /* Continue with the saved search when storage is readable. */
    }
    const saved = searchDestination('/scenes/return', '')
    if (saved !== '/search') navigate(saved, { replace: true })
  }, [frozen, query, navigate])
  const answer = useAnswer({
    query,
    scene_ids: search.data?.results.slice(0, 12).map((s) => s.scene_id) ?? [],
    collection_id: collection || undefined,
    character_ids: characterId ? [characterId] : undefined,
    search_id: search.data?.search_id,
  })
  useResultScroll(searchHref, !!search.data && !search.isPending)

  function openScene() {
    rememberOrigin({
      href: searchHref,
      query,
      sceneIds: rankingOf(results),
      scroll: window.scrollY,
      tab: resultView,
    })
  }
  const knownCharacters =
    characters.data?.filter(
      (item) =>
        (item.identity_status === 'reference' || item.origin === 'custom') &&
        (!collection || !item.collection_id || item.collection_id === collection)
    ) ?? []

  function submit() {
    if (!draft.trim()) return
    if (draft.trim() === query && limit === 12) {
      if (search.isFetching) return
      forceFresh.current = true
      void search.refetch()
      return
    }
    update({ q: draft.trim(), limit: '' })
  }

  const settling = search.isPending && !search.data
  return (
    <div className={`search-page ${query ? 'has-results' : ''}`}>
      <section className="search-hero">
        <div className="search-kicker">
          <span className="accent-rule" />
          YOUR VIDEO COLLECTION, SEARCHABLE
        </div>
        <h1>
          Find any <span>moment.</span>
        </h1>
        <p>
          Search scenes, characters, conversations, and visual details.
          <br className="desktop-break" /> Describe what you remember. We’ll find the evidence.
        </p>
        <form
          className="search-form"
          onSubmit={(event) => {
            event.preventDefault()
            submit()
          }}
        >
          <Search size={23} strokeWidth={1.7} />
          <label className="sr-only" htmlFor="scene-query">
            Describe a scene
          </label>
          <input
            id="scene-query"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="A character, a line, a moment…"
            maxLength={2000}
            autoComplete="off"
          />
          {draft && (
            <button
              type="button"
              className="icon-button clear-search"
              aria-label="Clear search text"
              onClick={() => setDraft('')}
            >
              <X size={17} />
            </button>
          )}
          <Button disabled={!draft.trim()} type="submit" aria-label="Search scenes">
            <span>Search</span>
            <ArrowRight size={18} />
          </Button>
        </form>
        <div className="search-filter-row">
          <span className="filter-caption">
            <SlidersHorizontal size={14} />
            Refine by
          </span>
          <label className="sr-only" htmlFor="search-collection">
            Collection
          </label>
          <select
            id="search-collection"
            className="select filter-select"
            value={collection}
            onChange={(event) =>
              update({
                collection: event.target.value,
                character: '',
                character_id: '',
                limit: '',
              })
            }
          >
            <option value="">All collections</option>
            {workspace.data?.collections.map((item) => (
              <option key={item.collection_id} value={item.collection_id}>
                {collectionLabel(item.collection_id)}
              </option>
            ))}
            {collection &&
              !workspace.data?.collections.some((item) => item.collection_id === collection) && (
                <option value={collection}>{collectionLabel(collection)}</option>
              )}
          </select>
          <label className="sr-only" htmlFor="search-character">
            Character
          </label>
          <select
            id="search-character"
            className="select filter-select"
            value={characterId || character}
            onChange={(event) => {
              const selected = knownCharacters.find((item) => item.id === event.target.value)
              update({
                character_id: selected?.id ?? '',
                character: selected?.name ?? '',
                limit: '',
              })
            }}
          >
            <option value="">Any character</option>
            {knownCharacters.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
                {item.collection_id && !collection
                  ? ` · ${collectionLabel(item.collection_id)}`
                  : ''}
                {item.origin === 'custom' ? ` · ${item.id.slice(0, 4)}` : ''}
              </option>
            ))}
            {characterId && !knownCharacters.some((item) => item.id === characterId) && (
              <option value={characterId}>{character || 'Selected character'}</option>
            )}
            {!characterId && character && <option value={character}>{character}</option>}
          </select>
          {(collection || character || characterId) && (
            <button
              className="text-link muted"
              onClick={() => update({ collection: '', character: '', character_id: '' })}
            >
              Reset filters
              <X size={12} />
            </button>
          )}
          {query && (
            <button
              className="text-link muted"
              onClick={() => {
                clearSearch()
                navigate('/search')
              }}
            >
              New search
            </button>
          )}
        </div>
        {!query && (
          <div className="suggestions">
            <span>Try a search</span>
            {suggestions.map((suggestion) => (
              <button key={suggestion} onClick={() => update({ q: suggestion })}>
                {suggestion}
                <ArrowRight size={13} />
              </button>
            ))}
          </div>
        )}
      </section>

      {query ? (
        <section className="search-results" aria-live="polite" aria-busy={search.isFetching}>
          <div className="section-heading search-results-heading">
            <div>
              <h2>
                {settling
                  ? 'Looking for your moment…'
                  : search.isError
                    ? 'Search interrupted'
                    : playable
                      ? `${results.length} of ${search.data?.results.length ?? 0} matches with video`
                      : `${search.data?.results.length ?? 0} scene matches`}
              </h2>
              <p className="muted small">
                {settling
                  ? 'Matching dialogue, descriptions, and scene knowledge.'
                  : search.isFetching
                    ? 'Updating these matches…'
                    : 'Ranked by matching evidence in your collection.'}
              </p>
            </div>
            {!settling && !!search.data?.results.length && (
              <button
                className={`filter-toggle ${playable ? 'selected' : ''}`}
                aria-pressed={playable}
                onClick={() => setPlayable(!playable)}
              >
                {playable && <Check size={13} />}Video available
              </button>
            )}
          </div>
          {settling ? (
            <>
              <div className="search-skeleton-grid">
                {[0, 1, 2].map((id) => (
                  <div className="search-skeleton" key={id}>
                    <div />
                    <span />
                    <span />
                    <span />
                  </div>
                ))}
              </div>
              <p className="search-loading-note">
                <Clock3 size={15} />
                {waiting
                  ? 'Still searching. Loading the local model can take longer the first time.'
                  : 'Finding evidence across your indexed scenes…'}
              </p>
            </>
          ) : search.isError ? (
            <ErrorState
              error={search.error}
              retry={() => {
                void search.refetch()
              }}
            />
          ) : (
            <>
              {search.data && (
                <AnswerPanel
                  key={query + characterId + collection}
                  state={answer}
                  retrievalWarnings={search.data.warnings}
                  origin={searchHref}
                  onOpen={openScene}
                />
              )}
              {!search.data?.results.length && !!search.data?.warnings.length && (
                <details className="search-warnings">
                  <summary>Some matching details need verification</summary>
                  <ul>
                    {search.data.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </details>
              )}
              {!!search.data?.results.length && (
                <div
                  className="result-view-tabs"
                  role="tablist"
                  aria-label="Explore search results"
                >
                  <button
                    id="scenes-tab"
                    role="tab"
                    aria-controls="scenes-results"
                    aria-selected={resultView === 'scenes'}
                    onClick={() => setResultView('scenes')}
                  >
                    Scenes
                  </button>
                  <button
                    id="graph-tab"
                    role="tab"
                    aria-controls="graph-results"
                    aria-selected={resultView === 'graph'}
                    onClick={() => setResultView('graph')}
                  >
                    Evidence graph
                  </button>
                </div>
              )}
              {resultView === 'graph' && search.data && (
                <div id="graph-results" role="tabpanel" aria-labelledby="graph-tab">
                  <Suspense fallback={<p className="muted">Loading graph explorer…</p>}>
                    <EvidenceGraph
                      scenes={search.data.results}
                      query={query}
                      characterId={characterId}
                      onFocus={setFocusSceneId}
                      answerGraph={answer.answer?.graph}
                      stateKey={search.data.search_id}
                      origin={searchHref}
                      onOpen={openScene}
                      collection={collection}
                      focusSceneId={focusSceneId}
                      onSelection={setHighlighted}
                    />
                  </Suspense>
                </div>
              )}
              <div
                id="scenes-results"
                role="tabpanel"
                aria-labelledby="scenes-tab"
                hidden={resultView !== 'scenes'}
              >
                {results.length ? (
                  <div className="scene-grid">
                    {results.map((scene, index) => (
                      <SceneCard
                        key={scene.scene_id}
                        scene={scene}
                        rank={index + 1}
                        onOpen={openScene}
                        origin={searchHref}
                        selected={highlighted.includes(scene.scene_id)}
                        onSelect={(id) => {
                          setFocusSceneId(id)
                          setHighlighted([id])
                        }}
                      />
                    ))}
                  </div>
                ) : (
                  <EmptyState
                    title={
                      playable ? 'No playable clips in these matches' : 'No matching scenes found'
                    }
                    action={
                      playable ? (
                        <Button variant="secondary" onClick={() => setPlayable(false)}>
                          Show all matches
                        </Button>
                      ) : (
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setDraft(query)
                            document.getElementById('scene-query')?.focus()
                          }}
                        >
                          Refine your search
                        </Button>
                      )
                    }
                  >
                    {playable
                      ? 'The matching descriptions are still available. Their source video files are not in this workspace.'
                      : 'Try fewer details or a different phrase. Searchy only returns evidence from the indexed collection.'}
                  </EmptyState>
                )}
              </div>
              {!!results.length && search.data?.results.length === limit && limit < 100 && (
                <div className="load-more">
                  <Button
                    variant="secondary"
                    onClick={() => update({ limit: String(Math.min(100, limit + 12)) })}
                  >
                    Find more matches
                    <ArrowRight size={15} />
                  </Button>
                </div>
              )}
            </>
          )}
        </section>
      ) : (
        <section className="search-discover">
          <SectionHeading
            title="A few moments to explore"
            to="/library"
            linkLabel="Browse library"
          />
          <p className="muted discover-description">
            Available clips from your collection. Start watching, or search for something specific.
          </p>
          {workspace.isError ? (
            <ErrorState
              error={workspace.error}
              retry={() => {
                void workspace.refetch()
              }}
            />
          ) : workspace.isPending ? (
            <div className="search-skeleton-grid">
              {[0, 1, 2].map((id) => (
                <div className="search-skeleton" key={id}>
                  <div />
                  <span />
                  <span />
                </div>
              ))}
            </div>
          ) : workspace.data.featured_scenes.length ? (
            <div className="scene-grid">
              {workspace.data.featured_scenes.slice(0, 3).map((scene) => (
                <SceneCard compact key={scene.scene_id} scene={scene} />
              ))}
            </div>
          ) : (
            <EmptyState title="Your next favorite moment starts here">
              Upload a video or import your processed collection to make it searchable.
            </EmptyState>
          )}
          {workspace.data && (
            <div className="search-footnote">
              <span className="status-dot" />
              {workspace.data.metrics.indexed_scenes.toLocaleString()} indexed scenes
              <span className="footnote-divider">/</span>
              {workspace.data.metrics.playable_scenes.toLocaleString()} with video
              <span className="footnote-divider">/</span>Answers grounded in your collection
            </div>
          )}
        </section>
      )}
    </div>
  )
}
