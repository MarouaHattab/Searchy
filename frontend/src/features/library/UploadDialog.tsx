import { useEffect, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, CloudUpload, FileVideo, Folder, Info, LoaderCircle, X } from 'lucide-react'
import { Link } from 'react-router'
import { Button } from '../../components/ui'
import { message } from '../../lib/format'
import { uploadVideo } from '../../services/api'
import { workspaceQuery } from '../../services/queries'
import type { Job } from '../../types'

const extensions = ['mp4', 'mkv', 'mov', 'webm']
const mimeTypes: Record<string, string> = {
  mp4: 'video/mp4',
  mkv: 'video/x-matroska',
  mov: 'video/quicktime',
  webm: 'video/webm',
}

export function UploadDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const fileInput = useRef<HTMLInputElement>(null)
  const controller = useRef<AbortController | null>(null)
  const active = useRef(false)
  const client = useQueryClient()
  const workspace = useQuery(workspaceQuery)
  const [file, setFile] = useState<File | null>(null)
  const [collection, setCollection] = useState('uploads')
  const [dragging, setDragging] = useState(false)
  const [progress, setProgress] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [job, setJob] = useState<Job | null>(null)
  const maxSize = workspace.data?.capabilities.max_upload_mb

  useEffect(() => {
    if (open) {
      setFile(null)
      setJob(null)
      setError('')
      setProgress(0)
      if (fileInput.current) fileInput.current.value = ''
      dialog.current?.showModal()
    } else dialog.current?.close()
  }, [open])

  useEffect(() => () => controller.current?.abort(), [])

  function selectFile(value: File | undefined) {
    setError('')
    if (!value) return
    setFile(null)
    const extension = value.name.split('.').pop()?.toLowerCase() ?? ''
    if (!extensions.includes(extension)) {
      setError('Choose an MP4, MKV, MOV, or WebM video.')
      if (fileInput.current) fileInput.current.value = ''
      return
    }
    if (!value.size) {
      setError('This file is empty. Choose a video with content.')
      return
    }
    if (maxSize && value.size > maxSize * 1024 * 1024) {
      setError(`This video exceeds the ${maxSize.toLocaleString()} MB upload limit.`)
      return
    }
    setFile(
      value.type.startsWith('video/')
        ? value
        : new File([value], value.name, { type: mimeTypes[extension] })
    )
  }

  async function submit() {
    if (!file || active.current) return
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(collection)) {
      setError('Use 1–80 letters, numbers, hyphens, or underscores for the collection.')
      return
    }
    active.current = true
    setUploading(true)
    setError('')
    setProgress(0)
    controller.current = new AbortController()
    try {
      const result = await uploadVideo(file, collection, setProgress, controller.current.signal)
      setJob(result)
      await Promise.all([
        client.invalidateQueries({ queryKey: ['jobs'] }),
        client.invalidateQueries({ queryKey: ['workspace'] }),
        client.invalidateQueries({ queryKey: ['library'] }),
      ])
    } catch (failure) {
      setError(
        failure instanceof DOMException && failure.name === 'AbortError'
          ? 'Transfer cancelled. Check Processing Jobs if the upload had already finished.'
          : message(failure)
      )
    } finally {
      active.current = false
      setUploading(false)
      controller.current = null
    }
  }

  return (
    <dialog
      ref={dialog}
      className="upload-dialog"
      aria-labelledby="upload-title"
      onCancel={(event) => {
        if (uploading) event.preventDefault()
        else onClose()
      }}
      onClick={(event) => {
        if (event.target === dialog.current && !uploading) onClose()
      }}
    >
      <div className="dialog-content">
        <div className="dialog-heading">
          <div>
            <p className="eyebrow">GROW YOUR COLLECTION</p>
            <h2 id="upload-title">{job ? 'Your video is in the queue.' : 'Add a video'}</h2>
          </div>
          <button
            className="icon-button"
            disabled={uploading}
            onClick={onClose}
            aria-label="Close upload dialog"
          >
            <X size={20} />
          </button>
        </div>
        {job ? (
          <div className="upload-success">
            <span className="success-icon">
              <Check size={28} />
            </span>
            <h3>Transfer complete. Processing comes next.</h3>
            <p>
              Searchy will extract scenes, transcribe dialogue, and index the video. Follow its
              progress in Processing Jobs.
            </p>
            <div className="notice">
              <Info size={17} />
              <span>The ingestion worker must be running for queued jobs to start.</span>
            </div>
            <Link
              className="button button-primary"
              to={`/jobs?job=${job.job_id}`}
              onClick={onClose}
            >
              View processing job
            </Link>
            <Button variant="secondary" onClick={onClose}>
              Back to workspace
            </Button>
          </div>
        ) : (
          <>
            <p className="muted dialog-intro">
              Make a new video searchable by scene, conversation, and visual detail.
            </p>
            <input
              ref={fileInput}
              type="file"
              accept=".mp4,.mkv,.mov,.webm,video/mp4,video/quicktime,video/webm,video/x-matroska"
              hidden
              onChange={(event) => selectFile(event.target.files?.[0])}
              disabled={uploading}
            />
            <button
              type="button"
              className={`upload-dropzone ${dragging ? 'dragging' : ''} ${file ? 'has-file' : ''}`}
              disabled={uploading}
              onClick={() => fileInput.current?.click()}
              onDragOver={(event) => {
                event.preventDefault()
                if (!uploading) setDragging(true)
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault()
                setDragging(false)
                if (!uploading) {
                  if (event.dataTransfer.files.length > 1) setError('Upload one video at a time.')
                  else selectFile(event.dataTransfer.files[0])
                }
              }}
            >
              <span className="upload-icon">
                {file ? (
                  <FileVideo size={26} strokeWidth={1.5} />
                ) : (
                  <CloudUpload size={28} strokeWidth={1.5} />
                )}
              </span>
              <strong>{file ? file.name : 'Drop your video here'}</strong>
              <span>
                {file
                  ? `${(file.size / 1024 / 1024).toFixed(1)} MB · Click to choose another`
                  : 'or click to browse files'}
              </span>
              <small>
                MP4, MKV, MOV, WebM{maxSize ? ` · Up to ${maxSize.toLocaleString()} MB` : ''}
              </small>
            </button>
            <label className="field upload-collection">
              <span>
                <Folder size={14} />
                Collection
              </span>
              <input
                className="input"
                value={collection}
                maxLength={80}
                disabled={uploading}
                onChange={(event) => setCollection(event.target.value)}
                placeholder="uploads"
              />
              <small>Use an existing collection name or start a new one.</small>
            </label>
            {workspace.data && !workspace.data.capabilities.vlm_configured && (
              <div className="notice">
                <Info size={17} />
                <p>
                  Vision analysis needs a provider key in the backend configuration before
                  processing can finish.{' '}
                  <Link
                    className="text-link"
                    to="/settings"
                    onClick={() => {
                      if (!uploading) onClose()
                    }}
                  >
                    View settings
                  </Link>
                </p>
              </div>
            )}
            {uploading && (
              <div className="upload-progress" role="status">
                <div>
                  <span>
                    {progress < 100 ? 'Uploading video' : 'Validating video and creating a job…'}
                  </span>
                  <strong>{progress}% transferred</strong>
                </div>
                <progress value={progress} max={100} aria-label="File transfer progress" />
                <p>
                  This is file transfer progress. Scene processing starts after the job is queued.
                </p>
              </div>
            )}
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            <div className="dialog-actions">
              {uploading ? (
                <Button variant="secondary" onClick={() => controller.current?.abort()}>
                  Cancel transfer
                </Button>
              ) : (
                <Button variant="secondary" onClick={onClose}>
                  Cancel
                </Button>
              )}
              <Button
                disabled={!file || uploading || !collection.trim()}
                onClick={() => {
                  void submit()
                }}
              >
                {uploading ? (
                  <LoaderCircle size={16} className="spin" />
                ) : (
                  <CloudUpload size={16} />
                )}
                {uploading ? 'Uploading…' : 'Upload video'}
              </Button>
            </div>
          </>
        )}
      </div>
    </dialog>
  )
}
