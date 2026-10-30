import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  ArrowUpRight,
  Check,
  Clock3,
  Layers,
  LoaderCircle,
  RefreshCw,
} from 'lucide-react'
import { Link, useSearchParams } from 'react-router'
import {
  Badge,
  Button,
  EmptyState,
  ErrorState,
  Loading,
  PageHeading,
  StatusBadge,
} from '../components/ui'
import { count, dateTime, humanize, message } from '../lib/format'
import { api } from '../services/api'
import { jobsQuery } from '../services/queries'
import type { Job } from '../types'
import '../styles/management.css'

function stageLabel(job: Job): string {
  if (job.status === 'queued') return 'Waiting for the processing worker'
  if (job.status === 'completed') return 'Ready for search'
  if (job.status === 'failed') return 'Processing stopped'
  const stages: Record<string, string> = {
    'checking services': 'Connecting to search services',
    'reading processed chunks': 'Reading scene descriptions and subtitles',
    'validating video': 'Checking the video file',
    'detecting shot boundaries': 'Finding scene boundaries',
    'transcribing speech': 'Transcribing dialogue',
    'video has no audio stream': 'Analyzing a video without audio',
    'scene extraction complete': 'Preparing scenes for search',
    'removing obsolete scene boundaries': 'Updating the scene index',
  }
  if (job.stage.startsWith('indexing scenes'))
    return `Adding ${job.stage.replace('indexing ', '')} to search`
  if (job.stage.startsWith('analyzing scene')) return humanize(job.stage)
  return stages[job.stage] ?? humanize(job.stage)
}

function JobResult({ result }: { result: Job['result'] }) {
  if (!result) return null
  const scenes = typeof result.scenes === 'number' ? result.scenes : null
  const indexed = typeof result.indexed === 'number' ? result.indexed : null
  const unchanged = typeof result.unchanged === 'number' ? result.unchanged : null
  return (
    <div className="job-result">
      {scenes !== null && <span>{count(scenes)} scenes found</span>}
      {indexed !== null && <span>{count(indexed)} indexed</span>}
      {unchanged !== null && unchanged > 0 && <span>{count(unchanged)} already indexed</span>}
    </div>
  )
}

export default function JobsPage() {
  const jobs = useQuery(jobsQuery)
  const client = useQueryClient()
  const [params, setParams] = useSearchParams()
  const [retriedJobs, setRetriedJobs] = useState<Set<string>>(new Set())
  const jobElements = useRef(new Map<string, HTMLElement>())
  const selectedJob = params.get('job')
  const requestedStatus = params.get('status')
  const filter =
    requestedStatus && ['active', 'completed', 'failed'].includes(requestedStatus)
      ? requestedStatus
      : 'all'
  const retry = useMutation({
    mutationFn: api.retryJob,
    onSuccess: async (_, originalId) => {
      setRetriedJobs((previous) => new Set(previous).add(originalId))
      await Promise.all(
        ['jobs', 'workspace', 'library'].map((key) => client.invalidateQueries({ queryKey: [key] }))
      )
    },
  })
  useEffect(() => {
    const element = selectedJob ? jobElements.current.get(selectedJob) : null
    if (element) {
      element.scrollIntoView({ block: 'center', behavior: 'instant' })
      element.focus({ preventScroll: true })
    }
  }, [selectedJob, jobs.isSuccess, filter])
  function setFilter(value: string) {
    const next = new URLSearchParams(params)
    if (value === 'all') next.delete('status')
    else next.set('status', value)
    next.delete('job')
    setParams(next)
  }
  if (jobs.isPending) return <Loading label="Loading processing activity…" />
  if (jobs.isError) return <ErrorState error={jobs.error} retry={() => void jobs.refetch()} />
  const active = jobs.data.filter((job) => ['queued', 'running'].includes(job.status)).length
  const failed = jobs.data.filter((job) => job.status === 'failed').length
  const completed = jobs.data.filter((job) => job.status === 'completed').length
  const filtered = jobs.data.filter(
    (job) =>
      filter === 'all' ||
      (filter === 'active' ? ['queued', 'running'].includes(job.status) : job.status === filter)
  )
  const tabs = [
    { value: 'all', label: 'All activity', amount: jobs.data.length },
    { value: 'active', label: 'In progress', amount: active },
    { value: 'completed', label: 'Complete', amount: completed },
    { value: 'failed', label: 'Failed', amount: failed },
  ]

  return (
    <div className="stack jobs-page">
      <PageHeading eyebrow="Workspace activity" title="From video to searchable.">
        Follow uploads and imports as they move through processing.
      </PageHeading>
      <div className="jobs-status-strip panel">
        <div>
          <span className="job-summary-icon">
            <Layers size={19} />
          </span>
          <strong>{count(active)}</strong>
          <span className="muted">in progress</span>
        </div>
        <div>
          <Check size={18} className="job-icon-success" />
          <strong>{count(completed)}</strong>
          <span className="muted">complete</span>
        </div>
        <div>
          <AlertCircle size={18} className={failed ? 'job-icon-error' : 'muted'} />
          <strong>{count(failed)}</strong>
          <span className="muted">failed</span>
        </div>
      </div>
      <div className="jobs-toolbar">
        <div className="management-tabs" aria-label="Filter processing jobs">
          {tabs.map((tab) => (
            <button
              key={tab.value}
              aria-pressed={filter === tab.value}
              className={filter === tab.value ? 'is-active' : ''}
              onClick={() => setFilter(tab.value)}
            >
              {tab.label}
              <span>{count(tab.amount)}</span>
            </button>
          ))}
        </div>
        <span className="small muted job-refresh">
          <RefreshCw size={12} />
          Updates every 5 seconds
        </span>
      </div>
      {retry.isError && (
        <div className="management-alert" role="alert">
          <AlertCircle size={17} />
          <span>{message(retry.error)}</span>
          <Button variant="ghost" onClick={() => retry.reset()}>
            Dismiss
          </Button>
        </div>
      )}
      {retry.isSuccess && (
        <div className="management-notice" role="status">
          <Check size={17} />
          <span>
            Job queued again. Processing starts when a worker is available.{' '}
            <Link className="text-link" to={`/jobs?job=${encodeURIComponent(retry.data.job_id)}`}>
              View queued job
              <ArrowUpRight size={13} />
            </Link>
          </span>
        </div>
      )}
      {filtered.length ? (
        <div className="job-list">
          {filtered.map((job) => (
            <article
              className={`job-card panel ${selectedJob === job.job_id ? 'is-selected' : ''}`}
              key={job.job_id}
              tabIndex={selectedJob === job.job_id ? -1 : undefined}
              aria-current={selectedJob === job.job_id ? 'true' : undefined}
              ref={(element) => {
                if (element) jobElements.current.set(job.job_id, element)
                else jobElements.current.delete(job.job_id)
              }}
            >
              <div className="job-card-main">
                <span className={`job-type-icon ${job.status === 'running' ? 'is-running' : ''}`}>
                  {job.status === 'running' ? (
                    <LoaderCircle size={20} className="spin" />
                  ) : job.status === 'completed' ? (
                    <Check size={20} />
                  ) : job.status === 'failed' ? (
                    <AlertCircle size={20} />
                  ) : (
                    <Clock3 size={20} />
                  )}
                </span>
                <div className="job-card-copy">
                  <div className="job-card-title">
                    <h2>
                      {job.title ||
                        (job.kind === 'import' ? 'Processed scene import' : 'Video upload')}
                    </h2>
                    <StatusBadge status={job.status} />
                  </div>
                  <p className="job-stage">{stageLabel(job)}</p>
                  <div className="job-meta">
                    <Badge>{job.kind === 'import' ? 'Scene import' : 'Video upload'}</Badge>
                    {job.collection_id && <span>{job.collection_id}</span>}
                    <time dateTime={new Date(job.created_at * 1000).toISOString()}>
                      {dateTime(job.created_at)}
                    </time>
                    {job.attempts > 1 && <span>Attempt {job.attempts}</span>}
                  </div>
                </div>
                <div className="job-actions">
                  {job.status === 'failed' && (
                    <Button
                      variant="secondary"
                      disabled={retry.isPending || retriedJobs.has(job.job_id)}
                      onClick={() => {
                        if (!retry.isPending && !retriedJobs.has(job.job_id))
                          retry.mutate(job.job_id)
                      }}
                    >
                      <RefreshCw
                        size={14}
                        className={retry.isPending && retry.variables === job.job_id ? 'spin' : ''}
                      />
                      {retriedJobs.has(job.job_id)
                        ? 'Retry queued'
                        : retry.isPending && retry.variables === job.job_id
                          ? 'Queuing…'
                          : 'Retry'}
                    </Button>
                  )}
                  {job.video_id && job.status === 'completed' && (
                    <Link className="button button-ghost" to={`/library/${job.video_id}`}>
                      View video
                      <ArrowUpRight size={15} />
                    </Link>
                  )}
                </div>
              </div>
              {job.status === 'failed' && job.error && (
                <div className="job-error">
                  <AlertCircle size={15} />
                  <span>{job.error}</span>
                </div>
              )}
              {job.status === 'completed' && <JobResult result={job.result} />}
              {job.status === 'queued' && (
                <p className="job-queued-note">
                  Keep the Searchy worker running to process queued videos.
                </p>
              )}
            </article>
          ))}
        </div>
      ) : (
        <EmptyState title={filter === 'all' ? 'Nothing in the queue.' : 'No jobs in this view.'}>
          {filter === 'all'
            ? 'Upload a video from your library to start processing.'
            : 'Processing activity will appear here when it matches this filter.'}
        </EmptyState>
      )}
      <p className="small muted">
        Showing the latest {count(jobs.data.length)} jobs. Upload completion means the file was
        received; it becomes searchable after indexing finishes.
      </p>
    </div>
  )
}
