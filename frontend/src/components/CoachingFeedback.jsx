import { useState } from 'react'
import { ChevronDown, ChevronRight, CheckCircle } from 'lucide-react'

const DIFFICULTY_COLOR = {
  beginner:     'text-green-400',
  intermediate: 'text-yellow-400',
  advanced:     'text-red-400',
}

function FixAccordion({ fix }) {
  const [open, setOpen] = useState(false)
  const { title, explanation, drill, difficulty, target_metric, current_value, target_value } = fix

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-800/50 transition-colors"
      >
        <div className="flex items-center gap-3">
          {open ? (
            <ChevronDown className="h-4 w-4 shrink-0 text-gray-400" />
          ) : (
            <ChevronRight className="h-4 w-4 shrink-0 text-gray-400" />
          )}
          <span className="text-sm font-medium text-white">{title}</span>
        </div>
        {difficulty && (
          <span className={`text-xs font-medium capitalize shrink-0 ${DIFFICULTY_COLOR[difficulty] ?? 'text-gray-400'}`}>
            {difficulty}
          </span>
        )}
      </button>

      {open && (
        <div className="px-4 pb-4 space-y-3 border-t border-gray-800 pt-3">
          {explanation && <p className="text-sm text-gray-300">{explanation}</p>}

          {(current_value != null || target_value != null) && (
            <div className="flex gap-4 text-xs">
              {current_value != null && (
                <span className="text-gray-500">Current: <span className="text-gray-200">{current_value}</span></span>
              )}
              {target_value != null && (
                <span className="text-gray-500">Target: <span className="text-[#2D8653]">{target_value}</span></span>
              )}
              {target_metric && (
                <span className="text-gray-600">({target_metric})</span>
              )}
            </div>
          )}

          {drill && (
            <div className="rounded-lg border border-gray-700 bg-gray-800/50 px-3 py-2 text-xs text-gray-400">
              <span className="font-medium text-gray-300">Drill: </span>{drill}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function DrillCard({ drill }) {
  const { name, description, duration, frequency, focus_area } = drill
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900 p-4 space-y-1">
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-white">{name}</span>
        {focus_area && (
          <span className="text-xs text-gray-500 shrink-0">{focus_area}</span>
        )}
      </div>
      {description && <p className="text-xs text-gray-400">{description}</p>}
      <div className="flex gap-3 text-xs text-gray-500 pt-1">
        {duration && <span>{duration}</span>}
        {frequency && <span>· {frequency}</span>}
      </div>
    </div>
  )
}

export default function CoachingFeedback({ feedback }) {
  if (!feedback) return null

  const { summary, overall_assessment, priority_fixes, drill_plan, positive_notes } = feedback

  return (
    <div className="space-y-6">
      {/* Summary */}
      {(summary || overall_assessment) && (
        <div className="rounded-xl border border-gray-800 bg-gray-900 p-4">
          <p className="text-sm text-gray-300 leading-relaxed">{summary || overall_assessment}</p>
        </div>
      )}

      {/* Priority fixes */}
      {priority_fixes?.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wide">Priority Fixes</h3>
          {priority_fixes.map((fix, i) => (
            <FixAccordion key={i} fix={fix} />
          ))}
        </div>
      )}

      {/* Drills */}
      {drill_plan?.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wide">Drill Plan</h3>
          <div className="grid gap-3 sm:grid-cols-2">
            {drill_plan.map((drill, i) => (
              <DrillCard key={i} drill={drill} />
            ))}
          </div>
        </div>
      )}

      {/* Positive notes */}
      {positive_notes?.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-semibold text-gray-200 uppercase tracking-wide">What You&apos;re Doing Well</h3>
          <div className="space-y-2">
            {positive_notes.map((note, i) => (
              <div key={i} className="flex items-start gap-2 rounded-xl border border-green-900 bg-green-900/20 px-4 py-3">
                <CheckCircle className="h-4 w-4 shrink-0 text-[#2D8653] mt-0.5" />
                <p className="text-sm text-gray-300">{note}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
