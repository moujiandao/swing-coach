/**
 * KeyboardShortcutsHelp
 *
 * Semi-transparent overlay showing all keyboard shortcuts for the comparison view.
 * Triggered by pressing ? or clicking the ? icon in the toolbar.
 */

const SHORTCUTS = [
  { keys: 'Space', desc: 'Play / Pause' },
  { keys: '← →', desc: 'Step back / forward 1 frame' },
  { keys: '1 – 5', desc: 'Jump to phase (Preparation → Follow-through)' },
  { keys: 'S', desc: 'Toggle your skeleton' },
  { keys: 'P', desc: 'Toggle pro skeleton' },
  { keys: 'D', desc: 'Toggle deviations' },
  { keys: 'M', desc: 'Switch Overlay / Side-by-Side mode' },
  { keys: '[', desc: 'Decrease playback speed' },
  { keys: ']', desc: 'Increase playback speed' },
  { keys: '?', desc: 'Toggle this help overlay' },
]

export default function KeyboardShortcutsHelp({ onClose }) {
  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      {/* Card */}
      <div
        className="relative bg-gray-900 border border-gray-700 rounded-2xl p-6 w-full max-w-sm mx-4 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-white">Keyboard Shortcuts</h3>
          <button
            onClick={onClose}
            className="text-gray-500 hover:text-white transition-colors text-lg leading-none"
            aria-label="Close help"
          >
            ×
          </button>
        </div>

        <div className="space-y-2">
          {SHORTCUTS.map(({ keys, desc }) => (
            <div key={keys} className="flex items-center justify-between gap-4">
              <kbd className="text-xs font-mono bg-gray-800 border border-gray-700 text-gray-200 px-2 py-0.5 rounded whitespace-nowrap">
                {keys}
              </kbd>
              <span className="text-xs text-gray-400 text-right">{desc}</span>
            </div>
          ))}
        </div>

        <p className="mt-4 text-[10px] text-gray-600 text-center">
          Shortcuts active when not focused on a form field
        </p>
      </div>
    </div>
  )
}
