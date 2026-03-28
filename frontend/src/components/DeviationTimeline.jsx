import { useState } from 'react'

const SEVERITY_COLOR = {
  critical: '#EF4444',
  moderate: '#F59E0B',
  minor:    '#3B82F6',
}

/**
 * DeviationTimeline
 *
 * Thin horizontal bar showing WHERE deviations occur across the swing.
 * - Colored dot per frame_deviation entry
 * - Hover tooltip with joint and angle info
 * - Click to jump to that frame
 * - Current frame marker moves with playback
 */
export default function DeviationTimeline({ totalFrames, frameDeviations, currentFrame, onSeekToFrame }) {
  const [tooltip, setTooltip] = useState(null) // { pct, text }

  if (!frameDeviations?.length || !totalFrames || totalFrames <= 1) return null

  return (
    <div className="space-y-2">
      <p className="text-xs font-semibold uppercase tracking-widest text-gray-500">
        Deviation Map
      </p>

      {/* Bar */}
      <div className="relative h-7 rounded-lg bg-gray-800 overflow-visible">
        {/* Current-frame cursor */}
        <div
          className="absolute top-0 bottom-0 w-0.5 bg-white/30 pointer-events-none z-0"
          style={{ left: `${(currentFrame / (totalFrames - 1)) * 100}%` }}
        />

        {/* Deviation dots */}
        {frameDeviations.map((dev, i) => {
          const pct = (dev.frame_index / (totalFrames - 1)) * 100
          const color = SEVERITY_COLOR[dev.severity] || SEVERITY_COLOR.moderate
          const firstJoint = dev.deviating_joints?.[0]
          const jointLabel = firstJoint?.joint_name?.replace(/_/g, ' ') ?? ''
          const diff = firstJoint?.diff_degrees
          const phaseLabel = dev.phase?.replace(/_/g, ' ') ?? ''
          const tipText = [
            phaseLabel && `${phaseLabel}`,
            jointLabel && jointLabel,
            diff != null && `${Math.round(diff)}° off`,
          ].filter(Boolean).join(' — ')

          return (
            <button
              key={i}
              className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3 h-3 rounded-full z-10
                         transition-transform hover:scale-150 focus:outline-none focus-visible:ring-2"
              style={{
                left: `${pct}%`,
                background: color,
                boxShadow: `0 0 5px ${color}`,
              }}
              title={tipText}
              onClick={() => onSeekToFrame?.(dev.frame_index)}
              onMouseEnter={() => setTooltip({ pct, text: tipText })}
              onMouseLeave={() => setTooltip(null)}
              aria-label={`Jump to deviation at frame ${dev.frame_index}: ${tipText}`}
            />
          )
        })}

        {/* Tooltip */}
        {tooltip && (
          <div
            className="absolute -top-9 -translate-x-1/2 bg-gray-900 border border-gray-700
                       text-xs text-gray-200 px-2 py-1 rounded whitespace-nowrap pointer-events-none z-20"
            style={{ left: `${Math.min(Math.max(tooltip.pct, 5), 95)}%` }}
          >
            {tooltip.text}
          </div>
        )}
      </div>

      {/* Legend */}
      <div className="flex gap-4 text-[10px] text-gray-500">
        {[['critical', 'Critical'], ['moderate', 'Moderate'], ['minor', 'Minor']].map(([key, label]) => (
          <span key={key} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full inline-block" style={{ background: SEVERITY_COLOR[key] }} />
            {label}
          </span>
        ))}
      </div>
    </div>
  )
}
