import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  Check,
  CheckCircle2,
  CircleHelp,
  Copy,
  RefreshCw,
  Server,
  Terminal,
  XCircle,
} from 'lucide-react'
import { Badge, Button, ErrorState, Loading, PageHeading, SectionHeading } from '../components/ui'
import { count } from '../lib/format'
import { apiUrl } from '../services/api'
import { readinessQuery, workspaceQuery } from '../services/queries'
import '../styles/management.css'

const workerCommand = 'uv run --all-extras python -m searchy.worker'

export default function SettingsPage() {
  const workspace = useQuery(workspaceQuery)
  const readiness = useQuery(readinessQuery)
  const [copied, setCopied] = useState(false)
  const [copyFailed, setCopyFailed] = useState(false)
  const docsUrl = apiUrl('/docs') === '/docs' ? 'http://127.0.0.1:8000/docs' : apiUrl('/docs')
  async function copyWorkerCommand() {
    try {
      await navigator.clipboard.writeText(workerCommand)
      setCopied(true)
      setCopyFailed(false)
    } catch {
      setCopyFailed(true)
    }
  }
  if (workspace.isPending) return <Loading label="Loading workspace settings…" />
  if (workspace.isError)
    return <ErrorState error={workspace.error} retry={() => void workspace.refetch()} />
  const { capabilities, metrics } = workspace.data
  return (
    <div className="stack settings-page">
      <PageHeading
        eyebrow="Workspace settings"
        title="A clear view of your setup."
        action={
          <a className="button button-secondary" href={docsUrl} target="_blank" rel="noreferrer">
            API documentation
            <ArrowUpRight size={15} />
          </a>
        }
      >
        Connection health and the capabilities configured for this workspace.
      </PageHeading>
      <section className="stack settings-section">
        <SectionHeading title="Search services" />
        <div className="settings-service-panel panel">
          <div className="settings-service-header">
            <div>
              <Server size={19} />
              <h3>Connection status</h3>
            </div>
            <Button
              variant="ghost"
              onClick={() => void readiness.refetch()}
              disabled={readiness.isFetching}
            >
              <RefreshCw size={14} className={readiness.isFetching ? 'spin' : ''} />
              Refresh
            </Button>
          </div>
          {readiness.isPending ? (
            <p className="muted settings-service-pending" role="status">
              Checking search services…
            </p>
          ) : readiness.isError ? (
            <ErrorState error={readiness.error} retry={() => void readiness.refetch()} />
          ) : (
            <div className="settings-service-list">
              {Object.entries(readiness.data.services).map(([name, service]) => (
                <div className="settings-service-row" key={name}>
                  <span
                    className={`settings-connection-icon ${service.ready ? 'connected' : 'disconnected'}`}
                  >
                    {service.ready ? <CheckCircle2 size={19} /> : <XCircle size={19} />}
                  </span>
                  <div>
                    <strong>
                      {name.toLowerCase() === 'neo4j'
                        ? 'Knowledge graph'
                        : name.toLowerCase() === 'qdrant'
                          ? 'Semantic index'
                          : name}
                    </strong>
                    <span className="small muted">
                      {name.toLowerCase() === 'neo4j'
                        ? 'Neo4j'
                        : name.toLowerCase() === 'qdrant'
                          ? 'Qdrant'
                          : 'Search service'}
                    </span>
                  </div>
                  <Badge tone={service.ready ? 'green' : 'red'}>
                    {service.ready ? 'Connected' : 'Unavailable'}
                  </Badge>
                </div>
              ))}
            </div>
          )}
          <p className="settings-panel-note">
            Live connection checks refresh every 30 seconds. Model configuration below does not
            verify provider access.
          </p>
        </div>
      </section>
      <section className="stack settings-section">
        <SectionHeading title="Models & processing" />
        <div className="settings-values panel">
          <div>
            <span>Text embeddings</span>
            <strong className="settings-model-id">{capabilities.embedding_model}</strong>
          </div>
          <div>
            <span>Visual understanding</span>
            <strong>
              {capabilities.llm_provider === 'GOOGLE_GENAI'
                ? 'Google Gemini'
                : capabilities.llm_provider === 'GROQ'
                  ? 'Groq'
                  : capabilities.llm_provider}
              <Badge tone={capabilities.vlm_configured ? 'blue' : 'amber'}>
                {capabilities.vlm_configured ? 'Key configured' : 'Key required'}
              </Badge>
            </strong>
          </div>
          <div>
            <span>Vision model</span>
            <strong className="settings-model-id">{capabilities.llm_model}</strong>
          </div>
          <div>
            <span>Visual similarity search</span>
            <strong>
              <Badge tone={capabilities.visual_enabled ? 'blue' : 'neutral'}>
                {capabilities.visual_enabled ? 'Enabled' : 'Disabled'}
              </Badge>
            </strong>
          </div>
          <div>
            <span>Maximum video upload</span>
            <strong>{count(capabilities.max_upload_mb)} MB</strong>
          </div>
        </div>
        <p className="settings-help">
          <CircleHelp size={15} />
          Provider keys and model settings are managed in the backend’s local .env file. Restart the
          API and worker after changing them.
        </p>
      </section>
      <section className="stack settings-section">
        <SectionHeading title="Media availability" />
        <div className="settings-media-summary panel">
          <div>
            <strong>{count(metrics.playable_scenes)}</strong>
            <span>scenes with video</span>
          </div>
          <div>
            <strong>{count(metrics.metadata_only_scenes)}</strong>
            <span>metadata-only scenes</span>
          </div>
          <p>
            Scenes without a source file remain searchable. Playback and previews appear only when
            the actual media is available.
          </p>
        </div>
      </section>
      <section className="stack settings-section">
        <SectionHeading title="Background processing" />
        <div className="settings-worker panel">
          <div className="settings-worker-heading">
            <Terminal size={20} />
            <h3>Run the processing worker</h3>
          </div>
          <p className="muted">
            The worker turns received videos and imported metadata into searchable scenes. Run this
            command from the Searchy project directory in a separate terminal.
          </p>
          <div className="settings-command">
            <code>{workerCommand}</code>
            <Button
              variant="ghost"
              onClick={() => void copyWorkerCommand()}
              aria-label="Copy processing worker command"
            >
              {copied ? <Check size={17} /> : <Copy size={17} />}
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          {copyFailed && (
            <p className="small" role="status">
              Copy is unavailable in this browser. Select the command above to copy it.
            </p>
          )}
          <p className="small muted">
            Jobs show their last recorded processing stage. This page cannot determine whether a
            worker process is currently running.
          </p>
        </div>
      </section>
    </div>
  )
}
