import { useState } from 'react'
import axios from 'axios'
import { X } from 'lucide-react'
import VideoUploader from './VideoUploader'
import { createProReference, confirmProReference } from '../lib/api'

const STROKE_TYPES = [
  { value: 'forehand', label: 'Forehand' },
  { value: 'backhand_one', label: '1H Backhand' },
  { value: 'backhand_two', label: '2H Backhand' },
  { value: 'serve_flat', label: 'Flat Serve' },
  { value: 'serve_kick', label: 'Kick Serve' },
  { value: 'serve_slice', label: 'Slice Serve' },
  { value: 'volley', label: 'Volley' },
]

export default function AddProReferenceModal({ onClose, onSuccess }) {
  const [playerName, setPlayerName] = useState('')
  const [strokeType, setStrokeType] = useState('')
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [error, setError] = useState(null)

  const canSubmit = playerName.trim() && strokeType && file && uploadProgress == null

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
      // Step 1: create record + get presigned URL
      const { reference_id, upload_url } = await createProReference(playerName.trim(), strokeType)

      // Step 2: upload video
      if (upload_url.startsWith('file://')) {
        // Local dev: POST multipart to backend
        const formData = new FormData()
        formData.append('file', file)
        await axios.post(
          `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/pro-references/local/${reference_id}`,
          formData,
          {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (ev) => {
              setUploadProgress(Math.round((ev.loaded / ev.total) * 100))
            },
          },
        )
      } else {
        await axios.put(upload_url, file, {
          headers: { 'Content-Type': file.type },
          onUploadProgress: (ev) => {
            setUploadProgress(Math.round((ev.loaded / ev.total) * 100))
          },
        })
      }

      // Step 3: confirm upload, triggers processing
      await confirmProReference(reference_id)

      onSuccess?.()
      onClose()
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Upload failed. Please try again.')
      setUploadProgress(null)
    }
  }

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="relative w-full max-w-lg rounded-2xl border border-gray-800 bg-gray-950 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <h2 className="text-lg font-semibold text-white">Add Pro Reference</h2>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-white transition-colors"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="px-6 py-5 space-y-5">
          {/* Player name */}
          <div>
            <label className="block text-sm font-medium text-gray-300 mb-1.5">
              Player Name <span className="text-red-400">*</span>
            </label>
            <input
              type="text"
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              placeholder="e.g. Roger Federer"
              className="w-full rounded-lg border border-gray-700 bg-gray-900 px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:border-[#2D8653] focus:outline-none"
              disabled={uploadProgress != null}
            />
          </div>

          {/* Stroke type */}
          <fieldset>
            <legend className="text-sm font-medium text-gray-300 mb-2">
              Stroke Type <span className="text-red-400">*</span>
            </legend>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              {STROKE_TYPES.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setStrokeType(value)}
                  disabled={uploadProgress != null}
                  className={`rounded-lg border px-3 py-2 text-sm font-medium transition-colors text-left
                    ${strokeType === value
                      ? 'border-[#2D8653] bg-[#2D8653]/20 text-white'
                      : 'border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
                    }
                    disabled:pointer-events-none disabled:opacity-50`}
                >
                  {label}
                </button>
              ))}
            </div>
          </fieldset>

          {/* Video upload */}
          <div>
            <p className="text-sm font-medium text-gray-300 mb-2">
              Pro Video <span className="text-red-400">*</span>
            </p>
            <VideoUploader
              file={file}
              onFile={handleFile}
              uploadProgress={uploadProgress}
            />
            {fileError && (
              <p className="mt-1 text-xs text-red-400">{fileError}</p>
            )}
          </div>

          {/* Error banner */}
          {error && (
            <div className="rounded-lg border border-red-800 bg-red-900/30 px-4 py-3 text-sm text-red-300">
              {error}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              disabled={uploadProgress != null}
              className="flex-1 rounded-xl border border-gray-700 py-2.5 text-sm font-medium text-gray-300 hover:border-gray-500 hover:text-white transition-colors disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSubmit}
              className={`flex-1 rounded-xl py-2.5 text-sm font-semibold transition-colors
                ${canSubmit
                  ? 'bg-[#2D8653] text-white hover:bg-[#236b42]'
                  : 'cursor-not-allowed bg-gray-800 text-gray-500'
                }`}
            >
              {uploadProgress != null
                ? `Uploading… ${uploadProgress}%`
                : 'Upload & Process'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
