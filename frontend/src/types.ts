export interface Provenance {
  source: string
  method: string
  model: string | null
  confidence: number | null
  verified: boolean
}

export interface Dialogue {
  start: number
  end: number
  text: string
  speaker: string | null
  provenance: Provenance | null
}

export interface Observation {
  kind: 'character' | 'clothing' | 'action' | 'object' | 'location' | 'interaction'
  value: string
  subject: string | null
  evidence: string
  start: number | null
  end: number | null
  provenance: Provenance
}

export interface Playback {
  available: boolean
  url: string | null
  start_offset: number | null
  reason: string | null
}

export interface Scene {
  scene_id: string
  video_id: string
  collection_id: string
  episode_id: string | null
  start: number | null
  end: number | null
  timestamp_basis: string
  description: string
  dialogue: Dialogue[]
  provenance: Provenance[]
  playback: Playback
}

export interface SceneDetail extends Scene {
  source_chunk: string | null
  characters: string[]
  observations: Observation[]
}

export interface SceneMatch extends Scene {
  matching_characters: string[]
  score: number
  channel_scores: Record<string, number>
  evidence: string[]
  match_status: string
  missing_terms: string[]
}

export interface SearchResponse {
  query: string
  results: SceneMatch[]
  warnings: string[]
  channels: string[]
  partial: boolean
}

export interface SearchRequest {
  query: string
  limit?: number
  collection_id?: string
  characters?: string[]
  mode?: 'hybrid' | 'text' | 'graph' | 'visual'
}

export interface Collection {
  collection_id: string
  video_count: number
  scene_count: number
  indexed_scenes: number
}

export interface LibraryVideo {
  video_id: string
  collection_id: string
  title: string
  original_id: string
  source_kind: 'import' | 'upload'
  duration: number | null
  scene_count: number
  indexed_scenes: number
  playable_scenes: number
  thumbnail_scene_id: string | null
  status: 'ready' | 'partial' | 'processing' | 'queued' | 'failed' | 'empty'
  characters: string[]
}

export interface Workspace {
  metrics: {
    total_videos: number
    uploaded_videos: number
    indexed_videos: number
    total_scenes: number
    indexed_scenes: number
    playable_scenes: number
    metadata_only_scenes: number
    running_jobs: number
    queued_jobs: number
    failed_jobs: number
    completed_jobs: number
  }
  collections: Collection[]
  featured_scenes: SceneDetail[]
  capabilities: {
    max_upload_mb: number
    visual_enabled: boolean
    vlm_configured: boolean
    llm_provider: string
    llm_model: string
    embedding_model: string
  }
}

export interface Character {
  id: string
  name: string
  reference_url: string | null
  scene_count: number
  video_count: number
  verified_scene_count: number
  identity_status: 'reference' | 'unverified' | 'unidentified'
}

export interface Job {
  job_id: string
  kind: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  stage: string
  error: string | null
  result: Record<string, unknown> | null
  created_at: number
  updated_at: number
  attempts: number
  title?: string | null
  collection_id?: string | null
  video_id?: string | null
}

export interface Readiness {
  ready: boolean
  services: Record<string, { ready: boolean; detail?: string }>
  features: { visual_enabled: boolean; vlm_configured: boolean; embedding_model: string }
}
