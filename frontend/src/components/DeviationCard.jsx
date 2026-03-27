const SEVERITY = {
  critical: { label: 'Critical', className: 'bg-red-900/40 text-red-400 border-red-800' },
  moderate: { label: 'Moderate', className: 'bg-yellow-900/40 text-yellow-400 border-yellow-800' },
  minor:    { label: 'Minor',    className: 'bg-blue-900/40 text-blue-400 border-blue-800' },
}

function severityFromDiff(angleDiff) {
  if (angleDiff == null) return 'minor'
  const abs = Math.abs(angleDiff)
  if (abs >= 20) return 'critical'
  if (abs >= 10) return 'moderate'
  return 'minor'
}

function formatJoint(joint) {
  return joint?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? '—'
}

function formatPhase(phase) {
  return phase?.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()) ?? '—'
}

export default function DeviationCard({ deviation }) {
  const { joint, phase, angle_diff, timing_diff, description } = deviation
  const severity = severityFromDiff(angle_diff)
  const sev = SEVERITY[severity] ?? SEVERITY.minor

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 space-y-2">
      <div className="flex items-start justify-between gap-3">
        <div>
          <span className="text-sm font-medium text-white">{formatJoint(joint)}</span>
          <span className="mx-2 text-gray-600">·</span>
          <span className="text-xs text-gray-400">{formatPhase(phase)}</span>
        </div>
        <span className={`shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium ${sev.className}`}>
          {sev.label}
        </span>
      </div>

      <p className="text-sm text-gray-300">{description}</p>

      <div className="flex gap-4 text-xs text-gray-500">
        {angle_diff != null && (
          <span>Angle diff: <span className="text-gray-300">{angle_diff > 0 ? '+' : ''}{angle_diff.toFixed(1)}°</span></span>
        )}
        {timing_diff != null && (
          <span>Timing: <span className="text-gray-300">{timing_diff > 0 ? '+' : ''}{timing_diff.toFixed(0)} ms</span></span>
        )}
      </div>
    </div>
  )
}
