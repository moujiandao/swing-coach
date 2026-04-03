import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import axios from 'axios'
import { ArrowLeft, ArrowRight } from 'lucide-react'
import VideoUploader from '../components/VideoUploader'
import ProReferencePicker from '../components/ProReferencePicker'
import WizardStepIndicator from '../components/WizardStepIndicator'
import GripSelector, { GRIPS } from '../components/GripSelector'
import { createAnalysis, confirmUpload } from '../lib/api'

const STROKE_TYPES = [
  { value: 'forehand', label: 'Forehand' },
  { value: 'backhand_one', label: '1H Backhand' },
  { value: 'backhand_two', label: '2H Backhand' },
  { value: 'serve_flat', label: 'Flat Serve' },
  { value: 'serve_kick', label: 'Kick Serve' },
  { value: 'serve_slice', label: 'Slice Serve' },
  { value: 'volley', label: 'Volley' },
  { value: 'buggy_whip_forehand', label: 'Buggy-Whip Forehand' },
  { value: 'slice', label: 'Slice' },
]

export default function Upload() {
  const navigate = useNavigate()

  const [wizardStep, setWizardStep] = useState(1)
  const [strokeType, setStrokeType] = useState('')
  const [gripType, setGripType] = useState(null)
  const [proReferenceId, setProReferenceId] = useState(null)
  const [file, setFile] = useState(null)
  const [fileError, setFileError] = useState(null)
  const [uploadProgress, setUploadProgress] = useState(null)
  const [error, setError] = useState(null)

  const showGripSelector = strokeType === 'forehand'
  // Step 1 is complete when stroke is selected (and grip is selected if forehand)
  const step1Complete = strokeType && (!showGripSelector || gripType)
  const step2Complete = !!file
  const canSubmit = step1Complete && step2Complete && proReferenceId && uploadProgress == null

  function handleStrokeType(value) {
    setStrokeType(value)
    setProReferenceId(null)
    // Reset grip when changing stroke type
    if (value !== 'forehand') {
      setGripType(null)
    }
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
      const { analysis_id, upload_url } = await createAnalysis(strokeType, proReferenceId)

      if (upload_url.startsWith('file://')) {
        const formData = new FormData()
        formData.append('file', file)
        await axios.post(
          `${import.meta.env.VITE_API_URL || 'http://localhost:8000'}/api/upload/local/${analysis_id}`,
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

      await confirmUpload(analysis_id)
      navigate(`/analysis/${analysis_id}`)
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Upload failed. Please try again.')
      setUploadProgress(null)
    }
  }

  // Build the list of player names associated with the selected grip,
  // used to filter pro references in Step 3
  const gripPlayerNames = gripType
    ? (GRIPS.find((g) => g.value === gripType)?.players?.map((p) => p.name.toLowerCase()) ?? [])
    : []

  // Filter function for ProReferencePicker: match by grip metadata or player name
  function filterByGrip(ref) {
    if (!gripType) return true
    // Check metadata_json.grip match
    const refGrip = ref.metadata_json?.grip
    if (refGrip === gripType) return true
    // Fallback: check if the player name matches any grip-associated player
    const refName = (ref.player_name || '').toLowerCase()
    return gripPlayerNames.some((name) => refName.includes(name))
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-bold mb-1 text-center">Analyze Your Swing</h1>
      <p className="text-gray-400 mb-6 text-sm text-center">
        Three steps to personalized coaching feedback.
      </p>

      <WizardStepIndicator currentStep={wizardStep} />

      <form onSubmit={handleSubmit}>
        {/* ---- Step 1: Choose Stroke Type ---- */}
        {wizardStep === 1 && (
          <div className="space-y-6">
            <fieldset>
              <legend className="text-sm font-medium text-gray-300 mb-3">What stroke are you working on?</legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {STROKE_TYPES.map(({ value, label }) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => handleStrokeType(value)}
                    className={`rounded-xl border px-4 py-3 text-sm font-medium transition-all duration-200
                      ${strokeType === value
                        ? 'border-[#2D8653] bg-[#2D8653]/20 text-white shadow-lg shadow-[#2D8653]/10'
                        : 'border-gray-700 text-gray-400 hover:border-gray-500 hover:text-gray-200'
                      }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </fieldset>

            {/* Grip sub-selector (forehand only) */}
            {showGripSelector && (
              <div className="space-y-3">
                <p className="text-sm font-medium text-gray-300">What grip do you use?</p>
                <GripSelector selectedGrip={gripType} onSelect={setGripType} />
              </div>
            )}

            {/* Next button */}
            <div className="flex justify-end pt-2">
              <button
                type="button"
                disabled={!step1Complete}
                onClick={() => setWizardStep(2)}
                className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-semibold transition-colors
                  ${step1Complete
                    ? 'bg-[#2D8653] text-white hover:bg-[#236b42]'
                    : 'cursor-not-allowed bg-gray-800 text-gray-500'
                  }`}
              >
                Next <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ---- Step 2: Upload Video ---- */}
        {wizardStep === 2 && (
          <div className="space-y-6">
            <div>
              <p className="text-sm font-medium text-gray-300 mb-2">Upload a court-level video of your swing</p>
              <p className="text-xs text-gray-500 mb-4">
                For best results, film from behind or the side at court level. Slow-motion (120fps+) works great.
              </p>
              <VideoUploader
                file={file}
                onFile={handleFile}
                uploadProgress={uploadProgress}
              />
              {fileError && (
                <p className="mt-2 text-xs text-red-400">{fileError}</p>
              )}
            </div>

            {/* Navigation */}
            <div className="flex justify-between pt-2">
              <button
                type="button"
                onClick={() => setWizardStep(1)}
                className="flex items-center gap-2 rounded-xl border border-gray-700 px-5 py-2.5 text-sm font-medium text-gray-300 hover:border-gray-500 hover:text-white transition-colors"
              >
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
              <button
                type="button"
                disabled={!step2Complete}
                onClick={() => setWizardStep(3)}
                className={`flex items-center gap-2 rounded-xl px-6 py-2.5 text-sm font-semibold transition-colors
                  ${step2Complete
                    ? 'bg-[#2D8653] text-white hover:bg-[#236b42]'
                    : 'cursor-not-allowed bg-gray-800 text-gray-500'
                  }`}
              >
                Next <ArrowRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}

        {/* ---- Step 3: Compare & Analyze ---- */}
        {wizardStep === 3 && (
          <div className="space-y-6">
            <div>
              <p className="text-sm font-medium text-gray-300 mb-3">Choose a pro to compare against</p>
              <ProReferencePicker
                strokeType={strokeType}
                selectedId={proReferenceId}
                onSelect={setProReferenceId}
                filterFn={showGripSelector ? filterByGrip : undefined}
              />
              {!proReferenceId && (
                <p className="mt-2 text-xs text-gray-500">Select a pro reference to continue.</p>
              )}
            </div>

            {/* Summary of selections */}
            <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-4 space-y-2">
              <p className="text-xs font-medium text-gray-400 uppercase tracking-wider">Summary</p>
              <div className="flex flex-wrap gap-3 text-sm">
                <span className="rounded-full bg-[#2D8653]/20 border border-[#2D8653]/30 px-3 py-1 text-[#2D8653] font-medium">
                  {STROKE_TYPES.find((s) => s.value === strokeType)?.label}
                </span>
                {gripType && (
                  <span className="rounded-full bg-blue-900/30 border border-blue-800/30 px-3 py-1 text-blue-400 font-medium">
                    {GRIPS.find((g) => g.value === gripType)?.label} grip
                  </span>
                )}
                {file && (
                  <span className="rounded-full bg-gray-800 border border-gray-700 px-3 py-1 text-gray-300">
                    {file.name}
                  </span>
                )}
              </div>
            </div>

            {/* Error banner */}
            {error && (
              <div className="rounded-lg border border-red-800 bg-red-900/30 px-4 py-3 text-sm text-red-300">
                {error}
              </div>
            )}

            {/* Navigation */}
            <div className="flex justify-between pt-2">
              <button
                type="button"
                onClick={() => setWizardStep(2)}
                className="flex items-center gap-2 rounded-xl border border-gray-700 px-5 py-2.5 text-sm font-medium text-gray-300 hover:border-gray-500 hover:text-white transition-colors"
              >
                <ArrowLeft className="h-4 w-4" /> Back
              </button>
              <button
                type="submit"
                disabled={!canSubmit}
                className={`rounded-xl px-8 py-2.5 text-sm font-semibold transition-colors
                  ${canSubmit
                    ? 'bg-[#2D8653] text-white hover:bg-[#236b42]'
                    : 'cursor-not-allowed bg-gray-800 text-gray-500'
                  }`}
              >
                {uploadProgress != null ? `Uploading... ${uploadProgress}%` : 'Analyze My Swing'}
              </button>
            </div>
          </div>
        )}
      </form>
    </div>
  )
}
