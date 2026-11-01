import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, LoaderCircle, Pencil, Search, Trash2, Users, X } from 'lucide-react'
import { Link } from 'react-router'
import { Badge, Button, ErrorState, Loading } from '../../components/ui'
import { count, message } from '../../lib/format'
import { apiUrl } from '../../services/api'
import { workspaceQuery } from '../../services/queries'
import type { Job } from '../../types'
import { characterApi } from './api'
import { AppearanceReview } from './AppearanceReview'
import { ReferenceManager } from './ReferenceManager'
import { pipelineStatus, recognitionStatus, referenceStatus } from './types'

export function CharacterManager({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const client = useQueryClient()
  const confirmation = useRef<HTMLDialogElement>(null)
  const active = useRef(false)
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [collection, setCollection] = useState('')
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const detail = useQuery({
    queryKey: ['character-detail', id],
    queryFn: ({ signal }) => characterApi.detail(id, signal),
    refetchInterval: (query) => {
      const data = query.state.data
      return data &&
        [data.status, data.recognition_status].some((status) =>
          ['queued', 'processing'].includes(status)
        )
        ? 3000
        : false
    },
  })
  const workspace = useQuery(workspaceQuery)

  async function perform(operation: string, action: () => Promise<void>) {
    if (active.current) return
    active.current = true
    setBusy(operation)
    setError('')
    setNotice('')
    try {
      await action()
    } catch (failure) {
      setError(message(failure))
    } finally {
      await Promise.all(
        [
          'character-detail',
          'characters',
          'character-matches',
          'character-scenes',
          'workspace',
          'search',
          'search-answer',
          'evidence-graph',
          'jobs',
        ].map((key) => client.invalidateQueries({ queryKey: [key] }))
      )
      active.current = false
      setBusy('')
    }
  }

  if (detail.isPending) return <Loading label="Loading character references…" />
  if (detail.isError) return <ErrorState error={detail.error} retry={() => void detail.refetch()} />
  const character = detail.data
  const searchParams = new URLSearchParams({
    q: `Show scenes with ${character.name}`,
    character_id: character.id,
    collection: character.collection_id,
  })
  const preparing = ['queued', 'processing'].includes(character.status)
  const recognizing = ['queued', 'processing'].includes(character.recognition_status)

  return (
    <div className="stack character-manager">
      <div className="character-profile panel">
        <span className="character-portrait character-portrait-large">
          {character.reference_url ? (
            <img src={apiUrl(character.reference_url)} alt={`${character.name} reference`} />
          ) : (
            <Users size={32} />
          )}
        </span>
        <div className="character-profile-copy">
          <Badge tone="blue">Your character · {character.collection_id}</Badge>
          <h1>{character.name}</h1>
          <p className="muted">
            {count(character.scene_count)} associated scenes · {count(character.video_count)} videos
          </p>
        </div>
        <div className="character-profile-actions">
          <Link className="button button-primary" to={`/search?${searchParams}`}>
            <Search size={15} />
            Search scenes
          </Link>
          <Button
            variant="secondary"
            onClick={() => {
              setName(character.name)
              setDescription(character.description)
              setCollection(character.collection_id)
              setEditing(!editing)
            }}
          >
            <Pencil size={14} />
            Edit details
          </Button>
        </div>
      </div>
      {editing ? (
        <form
          className="panel character-editor"
          onSubmit={(event) => {
            event.preventDefault()
            void perform('save', async () => {
              const moved = collection !== character.collection_id
              const updated = await characterApi.update(id, {
                name: name.trim(),
                description,
                ...(moved ? { collection_id: collection } : {}),
              })
              setEditing(false)
              setNotice(
                moved
                  ? updated.recognition_status === 'queued'
                    ? `Collection changed to ${collection}. Appearance recognition is queued.`
                    : `Collection changed to ${collection}. Run Find appearances after reference preparation.`
                  : 'Character details saved.'
              )
            })
          }}
        >
          <label className="field">
            <span>Character name</span>
            <input
              className="input"
              value={name}
              maxLength={100}
              required
              onChange={(event) => setName(event.target.value)}
              disabled={!!busy}
            />
          </label>
          <label className="field">
            <span>Description</span>
            <textarea
              className="input"
              rows={2}
              maxLength={2000}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              disabled={!!busy}
            />
          </label>
          <label className="field">
            <span>Recognition collection</span>
            <select
              className="input"
              value={collection}
              onChange={(event) => setCollection(event.target.value)}
              disabled={!!busy}
            >
              {workspace.data?.collections
                .filter((item) => item.indexed_scenes > 0)
                .map((item) => (
                  <option key={item.collection_id} value={item.collection_id}>
                    {item.collection_id} · {item.indexed_scenes} indexed scenes
                  </option>
                ))}
              {!workspace.data?.collections.some(
                (item) => item.collection_id === collection && item.indexed_scenes > 0
              ) && <option value={collection}>{collection} · current</option>}
            </select>
            <small>
              Changing collections clears old identity links and scans the new collection.
            </small>
          </label>
          <div className="character-inline-actions">
            <Button
              type="button"
              variant="secondary"
              disabled={!!busy}
              onClick={() => setEditing(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!!busy || !name.trim()}>
              {busy === 'save' ? 'Saving…' : 'Save changes'}
            </Button>
          </div>
        </form>
      ) : (
        character.description && <p className="character-description">{character.description}</p>
      )}
      <div className="character-processing panel">
        <div>
          <span className="eyebrow">Reference preparation</span>
          <strong>
            {preparing && <LoaderCircle size={14} className="spin" />}
            {referenceStatus(character.status)}
          </strong>
          <p>Image validation prepares references. It does not confirm an appearance.</p>
        </div>
        <div>
          <span className="eyebrow">Scene recognition</span>
          <strong>
            {recognizing && <LoaderCircle size={14} className="spin" />}
            {pipelineStatus(character)}
          </strong>
          <p>
            {recognitionStatus(character.recognition_status)}. {character.scene_count} associated
            scene{character.scene_count === 1 ? '' : 's'}
            {character.review_count ? `, ${character.review_count} awaiting review` : ''}.{' '}
            {character.video_id ? 'Limited to the selected video.' : 'Scoped to this collection.'}
          </p>
        </div>
        <Button
          disabled={!!busy || preparing || recognizing || !character.references.length}
          onClick={() =>
            void perform('recognize', async () => {
              const queued = await characterApi.recognize(id)
              setJob(queued)
              setNotice(
                'Appearance search queued. Review the proposed matches when processing finishes.'
              )
            })
          }
        >
          {busy === 'recognize' ? (
            <LoaderCircle size={15} className="spin" />
          ) : (
            <Search size={15} />
          )}
          Find appearances
        </Button>
      </div>
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
      {(notice || job) && (
        <div className="character-notice" role="status">
          <Check size={16} />
          <p>
            {notice}
            {job && (
              <>
                {' '}
                <Link className="text-link" to={`/jobs?job=${job.job_id}`}>
                  View processing job
                </Link>
              </>
            )}
          </p>
        </div>
      )}
      <ReferenceManager
        character={character}
        busy={busy}
        perform={perform}
        setJob={setJob}
        setNotice={setNotice}
        setError={setError}
      />
      <AppearanceReview character={character} />
      <div className="character-delete-row">
        <div>
          <strong>Remove this character</strong>
          <p>Delete the identity and its references. Scenes and their original evidence remain.</p>
        </div>
        <Button variant="ghost" disabled={!!busy} onClick={() => confirmation.current?.showModal()}>
          <Trash2 size={15} />
          Delete character
        </Button>
      </div>
      <dialog
        ref={confirmation}
        className="upload-dialog character-delete-dialog"
        aria-labelledby="delete-character-title"
        onCancel={(event) => {
          if (busy) event.preventDefault()
        }}
      >
        <div className="dialog-content">
          <div className="dialog-heading">
            <h2 id="delete-character-title">Delete {character.name}?</h2>
            <button
              className="icon-button"
              disabled={!!busy}
              onClick={() => confirmation.current?.close()}
              aria-label="Close delete confirmation"
            >
              <X size={19} />
            </button>
          </div>
          <p className="dialog-intro muted">
            The character record, reference images and registered identity links will be removed.
            Original scene descriptions, dialogue and videos will remain.
          </p>
          <div className="dialog-actions">
            <Button
              variant="secondary"
              disabled={!!busy}
              onClick={() => confirmation.current?.close()}
            >
              Keep character
            </Button>
            <Button
              variant="danger"
              disabled={!!busy}
              onClick={() =>
                void perform('delete', async () => {
                  await characterApi.delete(id)
                  confirmation.current?.close()
                  onDeleted()
                })
              }
            >
              {busy === 'delete' ? 'Deleting…' : 'Delete character'}
            </Button>
          </div>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
      </dialog>
    </div>
  )
}
