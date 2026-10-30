import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Info, LoaderCircle, UserPlus, X } from 'lucide-react'
import { Button } from '../../components/ui'
import { message } from '../../lib/format'
import { api } from '../../services/api'
import { workspaceQuery } from '../../services/queries'
import { characterApi } from './api'
import { ReferencePicker } from './ReferencePicker'
import type { CustomCharacter } from './types'

export function CharacterDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean
  onClose: () => void
  onCreated: (id: string) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null)
  const active = useRef(false)
  const client = useQueryClient()
  const workspace = useQuery(workspaceQuery)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [collection, setCollection] = useState('uploads')
  const [video, setVideo] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState<CustomCharacter | null>(null)
  const videos = useQuery({
    queryKey: ['character-scope-videos', collection],
    queryFn: ({ signal }) => api.library({ collection_id: collection, limit: 200 }, signal),
    enabled: open && !!collection.trim(),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (open) {
      setName('')
      setDescription('')
      setCollection('uploads')
      setVideo('')
      setFiles([])
      setError('')
      setSaved(null)
      dialog.current?.showModal()
    } else {
      dialog.current?.close()
      setFiles([])
    }
  }, [open])

  async function submit() {
    if (active.current || !name.trim()) return
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(collection)) {
      setError('Use 1–80 letters, numbers, hyphens or underscores for the collection.')
      return
    }
    active.current = true
    setBusy(true)
    setError('')
    let character = saved
    try {
      if (!character) {
        character = await characterApi.create({
          name: name.trim(),
          description: description.trim(),
          collection_id: collection,
          video_id: video || undefined,
        })
        setSaved(character)
      }
      if (files.length) await characterApi.addReferences(character.id, files)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['characters'] }),
        client.invalidateQueries({ queryKey: ['jobs'] }),
      ])
      onCreated(character.id)
      onClose()
    } catch (failure) {
      setError(
        character
          ? `Character saved. The reference upload did not finish: ${message(failure)} You can retry or manage the saved character.`
          : `${message(failure)} Check the character library before retrying if the connection was interrupted.`
      )
      if (character) void client.invalidateQueries({ queryKey: ['characters'] })
    } finally {
      active.current = false
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={dialog}
      className="upload-dialog character-dialog"
      aria-labelledby="character-dialog-title"
      onCancel={(event) => {
        if (busy) event.preventDefault()
        else onClose()
      }}
      onClick={(event) => {
        if (event.target === dialog.current && !busy) onClose()
      }}
    >
      <form
        className="dialog-content"
        onSubmit={(event) => {
          event.preventDefault()
          void submit()
        }}
      >
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">Character library</p>
            <h2 id="character-dialog-title">Add a character</h2>
          </div>
          <button
            type="button"
            className="icon-button"
            disabled={busy}
            onClick={onClose}
            aria-label="Close character dialog"
          >
            <X size={20} />
          </button>
        </div>
        <p className="muted dialog-intro">
          Give a subject a name and reference images. Keep their identity connected to the right
          collection.
        </p>
        <div className="character-form-grid">
          <label className="field">
            <span>Character name</span>
            <input
              autoFocus
              className="input"
              required
              maxLength={100}
              value={name}
              disabled={busy || !!saved}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Alex Rivera"
            />
          </label>
          <label className="field">
            <span>Collection</span>
            <input
              className="input"
              list="character-collections"
              required
              maxLength={80}
              value={collection}
              disabled={busy || !!saved}
              onChange={(event) => {
                setCollection(event.target.value)
                setVideo('')
              }}
            />
            <datalist id="character-collections">
              {workspace.data?.collections.map((item) => (
                <option key={item.collection_id} value={item.collection_id} />
              ))}
            </datalist>
            <small>Choose an existing collection or enter a new one.</small>
          </label>
        </div>
        <label className="field">
          <span>
            Limit to a video <span className="muted">(optional)</span>
          </span>
          <select
            className="input"
            value={video}
            disabled={busy || !!saved || videos.isPending}
            onChange={(event) => setVideo(event.target.value)}
          >
            <option value="">All videos in this collection</option>
            {videos.data?.items.map((item) => (
              <option value={item.video_id} key={item.video_id}>
                {item.title}
              </option>
            ))}
          </select>
          {videos.isError && (
            <small className="form-error">
              Video choices are unavailable. You can still use the whole collection.
            </small>
          )}
        </label>
        <label className="field">
          <span>
            Description <span className="muted">(optional)</span>
          </span>
          <textarea
            className="input"
            rows={2}
            maxLength={2000}
            value={description}
            disabled={busy || !!saved}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Details that help you distinguish this character"
          />
        </label>
        <div className="field">
          <span>
            Reference images <span className="muted">(optional)</span>
          </span>
          <ReferencePicker files={files} onChange={setFiles} disabled={busy} />
        </div>
        <div className="notice">
          <Info size={16} />
          <p>
            Saving creates a character record. References are prepared in the background;
            appearances must be checked before the character has search matches.
          </p>
        </div>
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog-actions">
          <Button
            type="button"
            variant="secondary"
            disabled={busy}
            onClick={() => {
              if (saved) onCreated(saved.id)
              onClose()
            }}
          >
            {saved ? 'Manage saved character' : 'Cancel'}
          </Button>
          <Button type="submit" disabled={busy || !name.trim() || !collection.trim()}>
            {busy ? <LoaderCircle size={16} className="spin" /> : <UserPlus size={16} />}{' '}
            {busy
              ? saved
                ? 'Uploading references…'
                : 'Saving character…'
              : saved
                ? 'Retry image upload'
                : 'Add character'}
          </Button>
        </div>
      </form>
    </dialog>
  )
}
