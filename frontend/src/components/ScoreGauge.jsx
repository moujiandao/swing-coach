// SVG circular progress ring centered at (60,60), r=50
const RADIUS = 50
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

function scoreColor(score) {
  if (score >= 80) return '#2D8653'   // green
  if (score >= 60) return '#EAB308'   // yellow
  if (score >= 40) return '#F97316'   // orange
  return '#EF4444'                    // red
}

function scoreLabel(score) {
  if (score >= 80) return 'Excellent'
  if (score >= 60) return 'Good'
  if (score >= 40) return 'Fair'
  return 'Needs Work'
}

export default function ScoreGauge({ score }) {
  const pct = Math.max(0, Math.min(100, score)) / 100
  const dashOffset = CIRCUMFERENCE * (1 - pct)
  const color = scoreColor(score)

  return (
    <div className="flex flex-col items-center gap-2">
      <svg width="120" height="120" viewBox="0 0 120 120" className="-rotate-90">
        {/* Track */}
        <circle
          cx="60" cy="60" r={RADIUS}
          fill="none"
          stroke="#1f2937"
          strokeWidth="10"
        />
        {/* Progress */}
        <circle
          cx="60" cy="60" r={RADIUS}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={dashOffset}
          style={{ transition: 'stroke-dashoffset 0.6s ease' }}
        />
      </svg>
      {/* Score label overlay */}
      <div className="text-center -mt-2">
        <div className="text-4xl font-bold text-white leading-none">{Math.round(score)}</div>
        <div className="text-xs mt-1 font-medium" style={{ color }}>{scoreLabel(score)}</div>
      </div>
    </div>
  )
}
