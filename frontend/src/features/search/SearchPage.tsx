import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Check, Clock3, Search, SlidersHorizontal, Sparkles, X } from 'lucide-react'
import { useSearchParams } from 'react-router'
import { SceneCard } from '../../components/SceneCard'
import { Button, EmptyState, ErrorState, SectionHeading } from '../../components/ui'
import { api } from '../../services/api'
import { charactersQuery, workspaceQuery } from '../../services/queries'

const suggestions = [
  'Rachel wearing a wedding dress',
  'Phoebe playing guitar',
  'A conversation between Ross and Rachel',
]

export default function SearchPage() {
  const [params, setParams] = useSearchParams()
  const query = params.get('q')?.trim() ?? ''
  const collection = params.get('collection') ?? ''
  const character = params.get('character') ?? ''
  const limit = Math.min(100, Math.max(12, Number(params.get('limit')) || 12))
  const [draft, setDraft] = useState(query)
  const [playable, setPlayable] = useState(false)
  const [waiting, setWaiting] = useState(false)
  const workspace = useQuery(workspaceQuery)
  const characters = useQuery(charactersQuery)
  const search = useQuery({
    queryKey: ['search', query, collection, character, limit],
    queryFn: ({ signal }) =>
      api.search(
        {
          query,
          limit,
          collection_id: collection || undefined,
          characters: character ? [character] : undefined,
        },
        signal
      ),
    enabled: !!query,
    retry: false,
    staleTime: 5 * 60_000,
  })

  useEffect(() => {
    setDraft(query)
    setPlayable(false)
  }, [query])
  useEffect(() => {
    setWaiting(false)
    if (!search.isFetching) return
    const timer = window.setTimeout(() => setWaiting(true), 12_000)
    return () => window.clearTimeout(timer)
  }, [search.isFetching])

  function update(values: Record<string, string>) {
    const next = new URLSearchParams(params)
    Object.entries(values).forEach(([key, value]) =>
      value ? next.set(key, value) : next.delete(key)
    )
    setParams(next)
  }

  const results =
    search.data?.results.filter((scene) => !playable || scene.playback.available) ?? []
  const knownCharacters =
    characters.data?.filter((item) => item.identity_status === 'reference') ?? []

  function submit() {
    if (!draft.trim()) return
    if (draft.trim() === query && limit === 12) void search.refetch()
    else update({ q: draft.trim(), limit: '' })
  }

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
            onChange={(event) => update({ collection: event.target.value, limit: '' })}
          >
            <option value="">All collections</option>
            {workspace.data?.collections.map((item) => (
              <option key={item.collection_id} value={item.collection_id}>
                {item.collection_id}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="search-character">
            Character
          </label>
          <select
            id="search-character"
            className="select filter-select"
            value={character}
            onChange={(event) => update({ character: event.target.value, limit: '' })}
          >
            <option value="">Any character</option>
            {knownCharacters.map((item) => (
              <option key={item.id} value={item.name}>
                {item.name}
              </option>
            ))}
            {character && !knownCharacters.some((item) => item.name === character) && (
              <option value={character}>{character}</option>
            )}
          </select>
          {(collection || character) && (
            <button
              className="text-link muted"
              onClick={() => update({ collection: '', character: '' })}
            >
              Reset filters
              <X size={12} />
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
                {search.isFetching
                  ? 'Looking for your moment…'
                  : search.isError
                    ? 'Search interrupted'
                    : playable
                      ? `${results.length} of ${search.data?.results.length ?? 0} matches with video`
                      : `${search.data?.results.length ?? 0} scene matches`}
              </h2>
              <p className="muted small">
                {search.isFetching
                  ? 'Matching dialogue, descriptions, and scene knowledge.'
                  : 'Ranked by matching evidence in your collection.'}
              </p>
            </div>
            {!search.isFetching && !!search.data?.results.length && (
              <button
                className={`filter-toggle ${playable ? 'selected' : ''}`}
                aria-pressed={playable}
                onClick={() => setPlayable(!playable)}
              >
                {playable && <Check size={13} />}Video available
              </button>
            )}
          </div>
          {search.isFetching ? (
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
              {search.data?.partial && (
                <div className="notice">
                  <Sparkles size={17} />
                  <div>
                    <strong>Some details could not be verified.</strong>
                    <p>
                      These are the closest evidenced matches. Open a scene to review the source.
                    </p>
                  </div>
                </div>
              )}
              {!!search.data?.warnings.length && (
                <details className="search-warnings">
                  <summary>Search notes ({search.data.warnings.length})</summary>
                  <ul>
                    {search.data.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                </details>
              )}
              {results.length ? (
                <div className="scene-grid">
                  {results.map((scene, index) => (
                    <SceneCard key={scene.scene_id} scene={scene} rank={index + 1} />
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
