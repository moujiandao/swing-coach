import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Create a new analysis job and get a presigned S3 upload URL.
 * @param {string} strokeType
 * @param {string|null} proReferenceId  UUID of a ready ProReference record
 * @returns {{ analysis_id: string, upload_url: string }}
 */
export async function createAnalysis(strokeType, proReferenceId) {
  const { data } = await api.post('/api/upload', {
    stroke_type: strokeType,
    pro_reference_id: proReferenceId ?? null,
  })
  return data
}

/**
 * Confirm the video upload is complete, triggering pipeline processing.
 * @returns {{ status: string }}
 */
export async function confirmUpload(analysisId) {
  const { data } = await api.post(`/api/upload/${analysisId}/confirm`)
  return data
}

/**
 * Fetch a single analysis by ID.
 * @returns {AnalysisResponse}
 */
export async function getAnalysis(analysisId) {
  const { data } = await api.get(`/api/analysis/${analysisId}`)
  return data
}

/**
 * Fetch the full overlay dataset for canvas rendering.
 * Includes user_landmarks, pro_landmarks, frame_deviations, phase_boundaries,
 * video_url, keyframe_urls, and landmark_connections.
 * @returns {OverlayResponse}
 */
export async function getOverlay(analysisId) {
  const { data } = await api.get(`/api/analysis/${analysisId}/overlay`)
  return data
}

/**
 * Fetch the user's analysis history.
 * @returns {AnalysisResponse[]}
 */
export async function getHistory(limit = 20) {
  const { data } = await api.get('/api/history', { params: { limit } })
  return data
}

// ---------------------------------------------------------------------------
// Pro reference library
// ---------------------------------------------------------------------------

/** @returns {ProReferenceListItem[]} */
export async function getProReferences(filters = {}) {
  const { data } = await api.get('/api/pro-references', { params: filters })
  return data
}

/** @returns {ProReferenceResponse} */
export async function getProReference(id) {
  const { data } = await api.get(`/api/pro-references/${id}`)
  return data
}

/** @returns {{ reference_id: string, upload_url: string, s3_key: string }} */
export async function createProReference(playerName, strokeType, metadata) {
  const { data } = await api.post('/api/pro-references', {
    player_name: playerName,
    stroke_type: strokeType,
    metadata_json: metadata ?? null,
  })
  return data
}

/** @returns {{ reference_id: string, status: string }} */
export async function confirmProReference(referenceId) {
  const { data } = await api.post(`/api/pro-references/${referenceId}/confirm`)
  return data
}

/** @returns {void} */
export async function deleteProReference(referenceId) {
  await api.delete(`/api/pro-references/${referenceId}`)
}

/** @returns {{ reference_id: string, status: string }} */
export async function reprocessProReference(referenceId) {
  const { data } = await api.post(`/api/pro-references/${referenceId}/reprocess`)
  return data
}

export default api
