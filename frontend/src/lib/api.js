import axios from 'axios'

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  headers: { 'Content-Type': 'application/json' },
})

/**
 * Create a new analysis job and get a presigned S3 upload URL.
 * @returns {{ analysis_id: string, upload_url: string }}
 */
export async function createAnalysis(strokeType, proReference) {
  const { data } = await api.post('/api/upload/create', { stroke_type: strokeType, pro_reference: proReference })
  return data
}

/**
 * Confirm the video upload is complete, triggering pipeline processing.
 * @returns {{ status: string }}
 */
export async function confirmUpload(analysisId) {
  const { data } = await api.post(`/api/upload/confirm/${analysisId}`)
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
 * Fetch the user's analysis history.
 * @returns {AnalysisResponse[]}
 */
export async function getHistory(limit = 20) {
  const { data } = await api.get('/api/history', { params: { limit } })
  return data
}

export default api
