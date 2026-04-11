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
  const tempoDetail = phaseScores?.swing_tempo_detail
  const tempoScore = phaseScores?.swing_tempo ?? null

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

      {/* Swing Tempo comparison */}
      {tempoDetail && (
        <div className="mt-4 pt-4 border-t border-gray-800">
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>Swing Tempo</span>
            <span className="font-medium text-gray-200">
              {tempoScore != null ? Math.round(tempoScore) : '—'}
            </span>
          </div>
          <div className="h-2 w-full rounded-full bg-gray-800 mb-2">
            {tempoScore != null && (
              <div
                className={`h-2 rounded-full transition-all duration-500 ${barColor(tempoScore)}`}
                style={{ width: `${tempoScore}%` }}
              />
            )}
          </div>
          <div className="flex gap-4 text-[11px] text-gray-500">
            <span>You: <span className="text-gray-300 font-medium">{tempoDetail.user_ratio}:1</span></span>
            <span>Pro: <span className="text-gray-300 font-medium">{tempoDetail.pro_ratio}:1</span></span>
          </div>
        </div>
      )}
    </div>
  )
}
