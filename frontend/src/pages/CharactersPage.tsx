import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, ArrowRight, Plus, Search, Users } from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import { SceneCard } from '../components/SceneCard'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Loading,
  PageHeading,
  SectionHeading,
} from '../components/ui'
import { count } from '../lib/format'
import { api, apiUrl } from '../services/api'
import { charactersQuery } from '../services/queries'
import type { Character } from '../types'
import { CharacterDialog } from '../features/characters/CharacterDialog'
import { CharacterManager } from '../features/characters/CharacterManager'
import { isCustomCharacter, pipelineStatus } from '../features/characters/types'
import '../styles/management.css'
import '../styles/characters.css'

function CharacterPortrait({
  character,
  large = false,
}: {
  character: Character
  large?: boolean
}) {
  const [failed, setFailed] = useState(false)
  return (
    <span className={`character-portrait ${large ? 'character-portrait-large' : ''}`}>
      {character.reference_url && !failed ? (
        <img
          src={apiUrl(character.reference_url)}
          alt={`${character.name} reference`}
          onError={() => setFailed(true)}
        />
      ) : (
        <Users size={large ? 32 : 21} strokeWidth={1.4} />
      )}
    </span>
  )
}

function CharacterStatus({ character }: { character: Character }) {
  return (
    <Badge tone={character.identity_status === 'reference' ? 'blue' : 'neutral'}>
      {character.identity_status === 'reference'
        ? 'Reference image'
        : character.identity_status === 'unidentified'
          ? 'Unidentified'
          : 'Extracted name'}
    </Badge>
  )
}

export default function CharactersPage() {
  const characters = useQuery(charactersQuery)
  const [params, setParams] = useSearchParams()
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState(false)
  const [adding, setAdding] = useState(false)
  const selected = characters.data?.find((character) => character.id === params.get('character'))
  const offset = Math.max(0, Number(params.get('offset')) || 0)
  const scenes = useQuery({
    queryKey: ['character-scenes', selected?.id, offset],
    queryFn: ({ signal }) => api.characterScenes(selected!.id, offset, signal),
    enabled: !!selected && !isCustomCharacter(selected),
  })

  function select(character: Character) {
    setParams({ character: character.id })
    window.scrollTo({ top: 0, behavior: 'instant' })
  }

  if (characters.isPending) return <Loading label="Finding characters in your collection…" />
  if (characters.isError)
    return <ErrorState error={characters.error} retry={() => void characters.refetch()} />

  if (selected && isCustomCharacter(selected)) {
    return (
      <div className="stack characters-page">
        <button className="text-link back-link" onClick={() => setParams({})}>
          <ArrowLeft size={15} />
          All characters
        </button>
        <CharacterManager key={selected.id} id={selected.id} onDeleted={() => setParams({})} />
      </div>
    )
  }

  if (selected) {
    const searchParams = new URLSearchParams({
      q: `Show scenes with ${selected.name}`,
      character: selected.name,
    })
    return (
      <div className="stack characters-page">
        <button className="text-link back-link" onClick={() => setParams({})}>
          <ArrowLeft size={15} />
          All characters
        </button>
        <div className="character-profile panel">
          <CharacterPortrait key={selected.id} character={selected} large />
          <div className="character-profile-copy">
            <CharacterStatus character={selected} />
            <h1>{selected.name}</h1>
            <p className="muted">
              {count(selected.scene_count)} associated scenes across {count(selected.video_count)}{' '}
              videos
            </p>
          </div>
          <Link className="button button-primary" to={`/search?${searchParams}`}>
            <Search size={16} />
            Search these scenes
          </Link>
        </div>
        <p className="character-evidence-note">
          Names come from indexed scene descriptions.{' '}
          {selected.verified_scene_count > 0
            ? `${count(selected.verified_scene_count)} scene associations have verified evidence; other associations remain unverified.`
            : 'These scene associations have not been independently verified.'}{' '}
          A reference image helps identify a character; it does not confirm an appearance.
        </p>
        <SectionHeading title="Associated scenes" count={selected.scene_count} />
        {scenes.isPending ? (
          <Loading label="Loading associated scenes…" />
        ) : scenes.isError ? (
          <ErrorState error={scenes.error} retry={() => void scenes.refetch()} />
        ) : scenes.data.length ? (
          <>
            <div className="scene-grid">
              {scenes.data.map((scene) => (
                <SceneCard key={scene.scene_id} scene={scene} />
              ))}
            </div>
            <div className="management-pagination">
              <span className="muted small">
                Showing {count(offset + 1)}–{count(offset + scenes.data.length)} of{' '}
                {count(selected.scene_count)}
              </span>
              <div>
                <Button
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() =>
                    setParams({ character: selected.id, offset: String(Math.max(0, offset - 24)) })
                  }
                >
                  <ArrowLeft size={15} />
                  Previous
                </Button>
                <Button
                  variant="secondary"
                  disabled={offset + scenes.data.length >= selected.scene_count}
                  onClick={() => setParams({ character: selected.id, offset: String(offset + 24) })}
                >
                  Next
                  <ArrowRight size={15} />
                </Button>
              </div>
            </div>
          </>
        ) : (
          <EmptyState title="No associated scenes">
            There are no indexed scenes for this character yet.
          </EmptyState>
        )}
      </div>
    )
  }

  const filtered = characters.data.filter((character) =>
    character.name.toLocaleLowerCase().includes(filter.toLocaleLowerCase().trim())
  )
  const registered = filtered.filter(isCustomCharacter)
  const references = filtered.filter(
    (character) => !isCustomCharacter(character) && character.identity_status === 'reference'
  )
  const others = filtered.filter(
    (character) => !isCustomCharacter(character) && character.identity_status !== 'reference'
  )
  const visibleOthers = expanded || filter ? others : others.slice(0, 12)
  return (
    <div className="stack characters-page">
      <PageHeading
        eyebrow="Your collection"
        title="People, in context."
        action={
          <Button onClick={() => setAdding(true)}>
            <Plus size={16} />
            Add character
          </Button>
        }
      >
        Manage character references and explore their appearances across your collection.
      </PageHeading>
      <div className="toolbar character-toolbar">
        <label className="management-search">
          <Search size={17} />
          <input
            aria-label="Find a character"
            placeholder="Find a character…"
            value={filter}
            onChange={(event) => {
              setFilter(event.target.value)
              setExpanded(false)
            }}
          />
        </label>
        <span className="muted small">
          {count(characters.data.length)} characters and extracted names
        </span>
      </div>
      {filtered.length === 0 ? (
        <EmptyState title="No characters found">Try another name or clear your search.</EmptyState>
      ) : (
        <>
          {!!registered.length && (
            <section className="stack character-section">
              <SectionHeading title="Your characters" count={registered.length} />
              <div className="character-reference-grid">
                {registered.map((character) => (
                  <button
                    className="character-reference-card registered-character"
                    key={character.id}
                    onClick={() => select(character)}
                  >
                    <CharacterPortrait character={character} large />
                    <span className="character-reference-copy">
                      <strong>{character.name}</strong>
                      <span className="muted small">
                        {character.collection_id} · {count(character.scene_count)} scenes
                      </span>
                      <span className="registered-character-status">
                        {pipelineStatus(character)}
                        {character.scene_count
                          ? ` · ${count(character.scene_count)} detected`
                          : ''}
                      </span>
                    </span>
                    <ArrowRight size={16} className="character-card-arrow" />
                  </button>
                ))}
              </div>
            </section>
          )}
          {!!references.length && (
            <section className="stack character-section">
              <SectionHeading title="Character references" count={references.length} />
              <div className="character-reference-grid">
                {references.map((character) => (
                  <button
                    className="character-reference-card"
                    key={character.id}
                    onClick={() => select(character)}
                  >
                    <CharacterPortrait character={character} large />
                    <span className="character-reference-copy">
                      <strong>{character.name}</strong>
                      <span className="muted small">
                        {count(character.scene_count)} scenes · {count(character.video_count)}{' '}
                        videos
                      </span>
                    </span>
                    <ArrowRight size={16} className="character-card-arrow" />
                  </button>
                ))}
              </div>
              <p className="character-evidence-note">
                Reference images are available for these names. Scene appearances are extracted from
                metadata and may be uncertain.
              </p>
            </section>
          )}
          {!!others.length && (
            <section className="stack character-section">
              <SectionHeading title="Other extracted names" count={others.length} />
              <div className="character-name-list panel">
                {visibleOthers.map((character) => (
                  <button
                    className="character-name-row"
                    key={character.id}
                    onClick={() => select(character)}
                  >
                    <CharacterPortrait character={character} />
                    <span className="character-name-copy">
                      <strong>{character.name}</strong>
                      <span className="muted small">
                        {count(character.scene_count)} associated scenes
                      </span>
                    </span>
                    <CharacterStatus character={character} />
                    <ArrowRight size={15} />
                  </button>
                ))}
              </div>
              {!expanded && !filter && others.length > visibleOthers.length && (
                <Button
                  variant="secondary"
                  className="character-show-more"
                  onClick={() => setExpanded(true)}
                >
                  Show {count(others.length - visibleOthers.length)} more names
                </Button>
              )}
            </section>
          )}
        </>
      )}
      <CharacterDialog
        open={adding}
        onClose={() => setAdding(false)}
        onCreated={(id) => setParams({ character: id })}
      />
    </div>
  )
}
