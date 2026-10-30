import type { Character, Job } from '../../types'

export type ProcessingStatus = 'unprocessed' | 'queued' | 'processing' | 'ready' | 'failed'

export interface CharacterReference {
  id: string
  width: number
  height: number
  validation: 'image_validated' | 'face_ready' | 'rejected' | 'failed'
  error: string | null
  url: string
}

export interface CustomCharacter extends Character {
  origin: 'custom'
  description: string
  collection_id: string
  video_id: string | null
  revision: number
  status: ProcessingStatus
  recognition_status: ProcessingStatus
  references: CharacterReference[]
}

export interface CharacterCreate {
  name: string
  description: string
  collection_id: string
  video_id?: string
}

export interface ReferenceChange {
  character: CustomCharacter
  job: Job | null
}

export interface CharacterMatch {
  id: string
  scene_id: string
  character_id: string
  confidence: number | null
  method: string
  status: 'pending' | 'accepted' | 'rejected'
  timestamp: number | null
  evidence: string
  revision: number
  verified: boolean
  frame_url: string | null
}

export function isCustomCharacter(character: Character): character is CustomCharacter {
  return 'origin' in character && character.origin === 'custom'
}

export function referenceStatus(status: ProcessingStatus) {
  return {
    unprocessed: 'References not processed',
    queued: 'References queued',
    processing: 'Preparing references',
    ready: 'References ready',
    failed: 'Reference processing failed',
  }[status]
}

export function recognitionStatus(status: ProcessingStatus) {
  return {
    unprocessed: 'Appearances not checked',
    queued: 'Appearance search queued',
    processing: 'Finding appearances',
    ready: 'Appearance search complete',
    failed: 'Appearance search failed',
  }[status]
}
