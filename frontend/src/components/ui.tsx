import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { AlertCircle, ArrowRight, Inbox, LoaderCircle } from 'lucide-react'
import { Link } from 'react-router'
import { message } from '../lib/format'

export function Button({
  variant = 'primary',
  className = '',
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
}) {
  return (
    <button className={`button button-${variant} ${className}`} {...props}>
      {children}
    </button>
  )
}

export function Badge({
  children,
  tone = 'neutral',
}: {
  children: ReactNode
  tone?: 'neutral' | 'blue' | 'green' | 'amber' | 'red'
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, string> = {
    ready: 'Indexed',
    partial: 'Partially indexed',
    processing: 'Processing',
    queued: 'Queued',
    failed: 'Failed',
    empty: 'No scenes',
    completed: 'Complete',
    running: 'Processing',
  }
  const tone = ['ready', 'completed'].includes(status)
    ? 'green'
    : ['processing', 'running', 'queued'].includes(status)
      ? 'blue'
      : status === 'failed'
        ? 'red'
        : 'neutral'
  return (
    <Badge tone={tone}>
      {['processing', 'running'].includes(status) && <LoaderCircle size={12} className="spin" />}
      {labels[status] ?? status}
    </Badge>
  )
}

export function Loading({ label = 'Loading your workspace…' }: { label?: string }) {
  return (
    <div className="state-panel" role="status">
      <LoaderCircle className="spin" size={24} />
      <p>{label}</p>
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <div className="state-panel state-error" role="alert">
      <AlertCircle size={25} />
      <h3>We couldn’t load this.</h3>
      <p>{message(error)}</p>
      {retry && (
        <Button variant="secondary" onClick={retry}>
          Try again
        </Button>
      )}
    </div>
  )
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="state-panel">
      <Inbox size={29} strokeWidth={1.5} />
      <h3>{title}</h3>
      {children && <p>{children}</p>}
      {action}
    </div>
  )
}

export function PageHeading({
  eyebrow,
  title,
  children,
  action,
}: {
  eyebrow?: string
  title: string
  children?: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="page-heading">
      <div>
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1>{title}</h1>
        {children && <p className="page-description">{children}</p>}
      </div>
      {action}
    </div>
  )
}

export function SectionHeading({
  title,
  count,
  to,
  linkLabel = 'View all',
}: {
  title: string
  count?: number
  to?: string
  linkLabel?: string
}) {
  return (
    <div className="section-heading">
      <h2>
        {title}
        {count !== undefined && <span className="section-count">{count}</span>}
      </h2>
      {to && (
        <Link className="text-link" to={to}>
          {linkLabel}
          <ArrowRight size={14} />
        </Link>
      )}
    </div>
  )
}
