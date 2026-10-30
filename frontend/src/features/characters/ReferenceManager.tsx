import { useRef, useState } from 'react'
import { ImagePlus, LoaderCircle, Trash2 } from 'lucide-react'
import { Badge, Button, SectionHeading } from '../../components/ui'
import { apiUrl } from '../../services/api'
import type { Job } from '../../types'
import { characterApi, validateReferenceFiles } from './api'
import { ReferencePicker } from './ReferencePicker'
import type { CustomCharacter } from './types'

export function ReferenceManager({
  character,
  busy,
  perform,
  setJob,
  setNotice,
  setError,
}: {
  character: CustomCharacter
  busy: string
  perform: (operation: string, action: () => Promise<void>) => Promise<void>
  setJob: (job: Job | null) => void
  setNotice: (notice: string) => void
  setError: (error: string) => void
}) {
  const id = character.id
  const replacementInput = useRef<HTMLInputElement>(null)
  const replacement = useRef('')
  const [files, setFiles] = useState<File[]>([])
  return (
    <section className="stack character-section">
      <SectionHeading title="Reference images" count={character.references.length} />
      <p className="character-evidence-note">
        Use clear views of the same subject. Images are checked for faces when a face recognition
        model is configured; an image-only reference is labelled separately.
      </p>
      <input
        ref={replacementInput}
        type="file"
        hidden
        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
        onChange={(event) => {
          const file = event.target.files?.[0]
          const referenceId = replacement.current
          event.target.value = ''
          if (!file || !referenceId) return
          const failure = validateReferenceFiles([file], character.references.length - 1)
          if (failure) {
            setError(failure)
            return
          }
          void perform('replace', async () => {
            const result = await characterApi.replaceReference(id, referenceId, file)
            setJob(result.job)
            setNotice('Replacement saved. Reference preparation is queued.')
          })
        }}
      />
      {!!character.references.length && (
        <div className="character-reference-gallery">
          {character.references.map((reference, index) => (
            <article className="character-reference-item panel" key={reference.id}>
              <img src={apiUrl(reference.url)} alt={`${character.name} reference image`} />
              <div>
                <Badge
                  tone={
                    reference.validation === 'face_ready'
                      ? 'green'
                      : ['failed', 'rejected'].includes(reference.validation)
                        ? 'red'
                        : 'neutral'
                  }
                >
                  {reference.validation === 'face_ready'
                    ? 'Face reference ready'
                    : reference.validation === 'image_validated'
                      ? 'Image validated'
                      : reference.validation === 'rejected'
                        ? 'Reference rejected'
                        : 'Processing failed'}
                </Badge>
                <span className="muted small">
                  {reference.width} × {reference.height}
                </span>
                {reference.error && <p className="form-error">{reference.error}</p>}
                <div className="character-reference-actions">
                  <Button
                    variant="ghost"
                    disabled={!!busy}
                    onClick={() => {
                      replacement.current = reference.id
                      replacementInput.current?.click()
                    }}
                    aria-label={`Replace reference image ${index + 1}`}
                  >
                    <ImagePlus size={14} />
                    Replace
                  </Button>
                  <Button
                    variant="ghost"
                    disabled={!!busy}
                    onClick={() =>
                      void perform('remove', async () => {
                        const result = await characterApi.removeReference(id, reference.id)
                        setJob(result.job)
                        setNotice('Reference removed. Existing scene evidence is preserved.')
                      })
                    }
                    aria-label={`Remove reference image ${index + 1}`}
                  >
                    <Trash2 size={14} />
                    Remove
                  </Button>
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
      {character.references.length < 5 && (
        <div className="panel character-reference-upload">
          <ReferencePicker
            files={files}
            onChange={setFiles}
            existing={character.references.length}
            disabled={!!busy}
          />
          {!!files.length && (
            <div className="character-inline-actions">
              <Button variant="secondary" disabled={!!busy} onClick={() => setFiles([])}>
                Clear selection
              </Button>
              <Button
                disabled={!!busy}
                onClick={() =>
                  void perform('upload', async () => {
                    const result = await characterApi.addReferences(id, files)
                    setFiles([])
                    setJob(result.job)
                    setNotice(
                      result.job
                        ? 'Images saved. Reference preparation is queued.'
                        : 'These reference images are already saved.'
                    )
                  })
                }
              >
                {busy === 'upload' ? (
                  <LoaderCircle size={15} className="spin" />
                ) : (
                  <ImagePlus size={15} />
                )}
                Save reference images
              </Button>
            </div>
          )}
        </div>
      )}
    </section>
  )
}
