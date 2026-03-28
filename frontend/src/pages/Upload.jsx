import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import VideoUploader from '../components/VideoUploader'
import ProReferencePicker from '../components/ProReferencePicker'
import { createAnalysis, confirmUpload } from '../lib/api'

const STROKE_TYPES = [
  { value: 'forehand', label: 'Forehand' },
  { value: 'backhand_one', label: '1H Backhand' },
  { value: 'backhand_two', label: '2H Backhand' },
  { value: 'serve_flat', label: 'Flat Serve' },
  { value: 'serve_kick', label: 'Kick Serve' },
  { value: 'serve_slice', label: 'Slice Serve' },
  { value: 'volley', label: 'Volley' },
]

export default function Upload() {
  const navigate = useNavigate()

  const [strokeType, setStrokeType] = useState('')
  const [proReferenceId, setProReferenceId] = useState(null)
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [error, setError] = useState(null)

  const canSubmit = file && strokeType && proReferenceId && uploadProgress == null

  function handleStrokeType(value) {
    setStrokeType(value)
    // Clear selection — it may not match the new stroke type
    setProReferenceId(null)
  }

  function handleFile(selected, err) {
    setFileError(err)
    setFile(selected)
    setError(null)
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!canSubmit) return

    setError(null)
    setUploadProgress(0)

    try {
      // Step 1: create the job and get an upload URL
      const { analysis_id, upload_url } = await createAnalysis(strokeType, proReferenceId)

      // Step 2: upload the video
      if (upload_url.startsWith('file://')) {
        // Local dev fallback: POST multipart to backend
        const formData = new FormData()
        formData.append('file', file)
        await axios.post(
          `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/upload/local/${analysis_id}`,
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (e) => {
              setUploadProgress(Math.round((e.loaded / e.total) * 100))
            },
          },
        )
      } else {
        // Normal path: PUT directly to presigned S3 URL
        await axios.put(upload_url, file, {
          headers: { 'Content-Type': file.type },
          onUploadProgress: (e) => {
            setUploadProgress(Math.round((e.loaded / e.total) * 100))
          },
        })
      }

      // Step 3: confirm upload, trigger pipeline
      await confirmUpload(analysis_id)

      // Step 4: navigate to results
      navigate(`/analysis/${analysis_id}`)
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Upload failed. Please try again.')
      setUploadProgress(null)
    }
  }

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="text-2xl font-bold mb-1">Upload Your Swing</h1>
      <p className="text-gray-400 mb-6 text-sm">
        Select a stroke type, choose a pro reference, and upload your video clip.
      </p>

      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Stroke type */}
        <fieldset>
          <legend className="text-sm font-medium text-gray-300 mb-3">Stroke Type</legend>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
            {STROKE_TYPES.map(({ value, label }) => (
              <button
                key={value}
                type="button"
                onClick={() => handleStrokeType(value)}
                className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors text-left
                  ${strokeType === value
                    ? 'border-[#2D8653] bg-[#2D8653]/20 text-white'
                    : 'border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
                  }`}
              >
                {label}
              </button>
            ))}
          </div>
        </fieldset>

        {/* Pro reference picker — only shown after stroke type is selected */}
        {strokeType && (
          <div>
            <p className="text-sm font-medium text-gray-300 mb-3">Compare Against</p>
            <ProReferencePicker
              strokeType={strokeType}
              selectedId={proReferenceId}
              onSelect={setProReferenceId}
            />
            {!proReferenceId && (
              <p className="mt-2 text-xs text-gray-500">Select a pro reference to continue.</p>
            )}
          </div>
        )}

        {/* Video upload */}
        <div>
          <p className="text-sm font-medium text-gray-300 mb-2">Your Video</p>
          <VideoUploader
            file={file}
            onFile={handleFile}
            uploadProgress={uploadProgress}
          />
          {fileError && (
            <p className="mt-2 text-xs text-red-400">{fileError}</p>
          )}
        </div>

        {/* Error banner */}
        {error && (
          <div className="rounded-lg border border-red-800 bg-red-900/30 px-4 py-3 text-sm text-red-300">
            {error}
          </div>
        )}

        {/* Submit */}
        <button
          type="submit"
          disabled={!canSubmit}
          className={`w-full rounded-xl py-3 text-sm font-semibold transition-colors
            ${canSubmit
              ? 'bg-[#2D8653] text-white hover:bg-[#236b42]'
              : 'cursor-not-allowed bg-gray-800 text-gray-500'
            }`}
        >
          {uploadProgress != null ? `Uploading… ${uploadProgress}%` : 'Analyze Swing'}
        </button>
      </form>
    </div>
  )
}
