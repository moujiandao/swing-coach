// Maps backend phase keys → display names (order matters for display)
const PHASE_ORDER = [
  ['preparation', 'Preparation'],
  ['backswing', 'Backswing'],
  ['forward_swing', 'Forward Swing'],
  ['contact', 'Contact'],
  ['follow_through', 'Follow-through'],
]

function barColor(score) {
  if (score >= 80) return 'bg-[#2D8653]'
  if (score >= 60) return 'bg-yellow-500'
  if (score >= 40) return 'bg-orange-500'
  return 'bg-red-500'
}

export default function PhaseBreakdown({ phaseScores }) {
  return (
    <div className="space-y-3">
      {PHASE_ORDER.map(([key, label]) => {
        const score = phaseScores?.[key] ?? null
        return (
          <div key={key}>
            <div className="flex justify-between text-xs text-gray-400 mb-1">
              <span>{label}</span>
              <span className="font-medium text-gray-200">
                {score != null ? Math.round(score) : '—'}
              </span>
            </div>
            <div className="h-2 w-full rounded-full bg-gray-800">
              {score != null && (
                <div
                  className={`h-2 rounded-full transition-all duration-500 ${barColor(score)}`}
                  style={{ width: `${score}%` }}
                />
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
