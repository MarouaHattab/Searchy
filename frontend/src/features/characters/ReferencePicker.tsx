import { useEffect, useRef, useState } from 'react'
import { ImagePlus, X } from 'lucide-react'
import { validateReferenceFiles } from './api'

export function ReferencePicker({
  files,
  onChange,
  existing = 0,
  disabled = false,
}: {
  files: File[]
  onChange: (files: File[]) => void
  existing?: number
  disabled?: boolean
}) {
  const input = useRef<HTMLInputElement>(null)
  const [error, setError] = useState('')
  const [dragging, setDragging] = useState(false)
  const [previews, setPreviews] = useState<{ url: string; name: string }[]>([])
  useEffect(() => {
    const next = files.map((file) => ({ url: URL.createObjectURL(file), name: file.name }))
    setPreviews(next)
    return () => next.forEach((image) => URL.revokeObjectURL(image.url))
  }, [files])

  function select(values: File[]) {
    const next = [...files, ...values]
    const failure = validateReferenceFiles(next, existing)
    setError(failure)
    if (!failure) onChange(next)
    if (input.current) input.current.value = ''
  }

  return (
    <div className="character-picker">
      <input
        ref={input}
        type="file"
        hidden
        multiple
        accept=".jpg,.jpeg,.png,.webp,image/jpeg,image/png,image/webp"
        disabled={disabled}
        onChange={(event) => select(Array.from(event.target.files ?? []))}
      />
      {existing + files.length < 5 && (
        <button
          type="button"
          className={`character-dropzone ${dragging ? 'dragging' : ''}`}
          disabled={disabled}
          onClick={() => input.current?.click()}
          onDragOver={(event) => {
            event.preventDefault()
            if (!disabled) setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault()
            setDragging(false)
            if (!disabled) select(Array.from(event.dataTransfer.files))
          }}
        >
          <ImagePlus size={24} strokeWidth={1.5} />
          <strong>{existing ? 'Add reference images' : 'Drop reference images here'}</strong>
          <span>or click to browse · JPEG, PNG, WebP</span>
          <small>Up to 5 images · 10 MB each · One clear subject per image</small>
        </button>
      )}
      {!!files.length && (
        <div className="character-upload-previews">
          {previews.map((image, index) => (
            <div key={image.url}>
              <img src={image.url} alt={`Selected reference: ${image.name}`} />
              <button
                type="button"
                className="icon-button"
                disabled={disabled}
                aria-label={`Remove ${image.name}`}
                onClick={() => {
                  onChange(files.filter((_, position) => position !== index))
                  setError('')
                }}
              >
                <X size={15} />
              </button>
              <span title={image.name}>{image.name}</span>
            </div>
          ))}
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
