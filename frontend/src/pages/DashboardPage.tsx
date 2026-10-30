import { useQuery } from '@tanstack/react-query'
import {
  ArrowRight,
  ArrowUpRight,
  Clapperboard,
  Clock3,
  Database,
  Film,
  Search,
  Upload,
} from 'lucide-react'
import { Link } from 'react-router'
import { SceneCard, SceneThumbnail } from '../components/SceneCard'
import {
  Button,
  EmptyState,
  ErrorState,
  Loading,
  PageHeading,
  SectionHeading,
  StatusBadge,
} from '../components/ui'
import { count, dateTime, episodeTitle, humanize } from '../lib/format'
import { api } from '../services/api'
import '../styles/catalog.css'

export default function DashboardPage() {
  const workspace = useQuery({
    queryKey: ['workspace'],
    queryFn: ({ signal }) => api.workspace(signal),
    refetchInterval: 15_000,
  })
  const videos = useQuery({
    queryKey: ['library', { limit: 5 }],
    queryFn: ({ signal }) => api.library({ limit: 5 }, signal),
    refetchInterval: 15_000,
  })
  const jobs = useQuery({
    queryKey: ['jobs'],
    queryFn: ({ signal }) => api.jobs(signal),
    refetchInterval: 10_000,
  })

  if (workspace.isPending) return <Loading />
  if (workspace.isError)
    return <ErrorState error={workspace.error} retry={() => void workspace.refetch()} />

  const { metrics, featured_scenes: featured } = workspace.data
  const activeJobs = jobs.data?.filter((job) => ['running', 'queued'].includes(job.status)) ?? []
  const recentJobs = [
    ...activeJobs,
    ...(jobs.data?.filter((job) => !['running', 'queued'].includes(job.status)) ?? []),
  ].slice(0, 4)
  const metricCards = [
    {
      label: 'Videos in your library',
      value: metrics.total_videos,
      detail: `${count(metrics.uploaded_videos)} uploaded · ${count(metrics.total_videos - metrics.uploaded_videos)} imported`,
      icon: Film,
    },
    {
      label: 'Searchable scenes',
      value: metrics.indexed_scenes,
      detail: `${count(metrics.total_scenes)} scenes discovered`,
      icon: Database,
    },
    {
      label: 'Scenes with video',
      value: metrics.playable_scenes,
      detail: `${count(metrics.metadata_only_scenes)} metadata only`,
      icon: Clapperboard,
    },
    {
      label: 'Processing now',
      value: metrics.running_jobs + metrics.queued_jobs,
      detail: `${count(metrics.running_jobs)} active · ${count(metrics.queued_jobs)} queued`,
      icon: Clock3,
    },
  ]

  return (
    <div className="catalog-page stack">
      <PageHeading
        eyebrow="Your workspace"
        title="A clearer view of your collection."
        action={
          <Button onClick={() => window.dispatchEvent(new CustomEvent('searchy:upload'))}>
            <Upload size={17} />
            Upload video
          </Button>
        }
      >
        Your videos, searchable moments, and processing activity in one place.
      </PageHeading>

      <div className="metric-grid">
        {metricCards.map(({ label, value, detail, icon: Icon }) => (
          <article className="metric-card" key={label}>
            <div className="metric-label">
              <span>{label}</span>
              <Icon size={17} strokeWidth={1.7} />
            </div>
            <p className="metric-value">{count(value)}</p>
            <p className="muted small">{detail}</p>
          </article>
        ))}
      </div>

      <Link className="search-launcher" to="/search">
        <span className="search-launcher-icon">
          <Search size={23} />
        </span>
        <span>
          <strong>Find the moment you have in mind.</strong>
          <span>Search your indexed scenes with a simple description.</span>
        </span>
        <ArrowRight size={20} />
      </Link>

      {featured.length > 0 && (
        <section>
          <SectionHeading
            title="Available to watch"
            count={featured.length}
            to="/library"
            linkLabel="Browse library"
          />
          <p className="section-description">
            A few moments with source video available in your workspace.
          </p>
          <div className="scene-grid dashboard-scenes">
            {featured.slice(0, 3).map((scene) => (
              <SceneCard key={scene.scene_id} scene={scene} compact />
            ))}
          </div>
        </section>
      )}

      <div className="dashboard-columns">
        <section className="panel recent-panel">
          <SectionHeading title="Your video library" to="/library" />
          {videos.isPending ? (
            <Loading label="Loading videos…" />
          ) : videos.isError ? (
            <ErrorState error={videos.error} retry={() => void videos.refetch()} />
          ) : !videos.data.items.length ? (
            <EmptyState
              title="Your library starts here"
              action={
                <Button
                  variant="secondary"
                  onClick={() => window.dispatchEvent(new CustomEvent('searchy:upload'))}
                >
                  Upload a video
                </Button>
              }
            >
              Add a video to start finding scenes.
            </EmptyState>
          ) : (
            <div className="recent-video-list">
              {videos.data.items.map((video) => (
                <Link
                  className="recent-video"
                  key={video.video_id}
                  to={`/library/${video.video_id}`}
                >
                  <div className="recent-video-thumb">
                    <SceneThumbnail
                      id={video.thumbnail_scene_id ?? video.video_id}
                      available={Boolean(video.thumbnail_scene_id)}
                      title={video.title}
                    />
                  </div>
                  <div className="recent-video-info">
                    <strong>{video.title}</strong>
                    <span className="small muted">
                      {video.source_kind === 'import'
                        ? episodeTitle(video.original_id)
                        : 'Uploaded video'}{' '}
                      · {count(video.indexed_scenes)} indexed scenes
                    </span>
                  </div>
                  <StatusBadge status={video.status} />
                  <ArrowUpRight className="recent-video-arrow" size={17} />
                </Link>
              ))}
            </div>
          )}
        </section>
        <section className="panel activity-panel">
          <SectionHeading title="Processing activity" to="/jobs" />
          {jobs.isPending ? (
            <Loading label="Loading activity…" />
          ) : jobs.isError ? (
            <ErrorState error={jobs.error} retry={() => void jobs.refetch()} />
          ) : !recentJobs.length ? (
            <EmptyState title="Nothing processing yet">
              Your ingestion jobs will appear here.
            </EmptyState>
          ) : (
            <div className="activity-list">
              {recentJobs.map((job) => (
                <Link className="activity-item" key={job.job_id} to={`/jobs?job=${job.job_id}`}>
                  <div className={`activity-dot activity-dot-${job.status}`} />
                  <div className="activity-copy">
                    <div className="activity-title">
                      <strong>
                        {job.title ??
                          (job.kind === 'import' ? 'Collection import' : 'Video processing')}
                      </strong>
                      <StatusBadge status={job.status} />
                    </div>
                    <p>
                      {job.status === 'failed' ? 'Processing needs attention' : humanize(job.stage)}
                    </p>
                    <time className="small muted">{dateTime(job.updated_at)}</time>
                  </div>
                </Link>
              ))}
            </div>
          )}
          {metrics.failed_jobs > 0 && (
            <Link className="activity-notice" to="/jobs?status=failed">
              {count(metrics.failed_jobs)} failed{' '}
              {metrics.failed_jobs === 1 ? 'job needs' : 'jobs need'} attention
              <ArrowRight size={15} />
            </Link>
          )}
        </section>
      </div>
    </div>
  )
}
