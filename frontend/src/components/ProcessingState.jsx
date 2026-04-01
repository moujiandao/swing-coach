export default function ProcessingState({ onCancel }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      {/* Spinning ring */}
      <div className="relative mb-8">
        <div className="h-20 w-20 rounded-full border-4 border-gray-800" />
        <div className="absolute inset-0 h-20 w-20 rounded-full border-4 border-t-[#2D8653] animate-spin" />
      </div>

      <h2 className="text-xl font-semibold text-white mb-2">Analyzing your swing&hellip;</h2>
      <p className="text-gray-400 text-sm mb-1">
        Extracting pose landmarks and comparing against pro reference
      </p>
      <p className="text-gray-600 text-xs">Usually takes 30&ndash;60 seconds</p>

      {/* Animated stage hints */}
      <div className="mt-8 flex flex-col gap-2 text-xs text-gray-500 w-56">
        {['Extracting frames', 'Estimating pose', 'Comparing to pro', 'Generating feedback'].map(
          (stage, i) => (
            <div key={stage} className="flex items-center gap-2">
              <div
                className="h-1.5 w-1.5 rounded-full bg-[#2D8653] animate-pulse"
                style={{ animationDelay: `${i * 0.4}s` }}
              />
              {stage}
            </div>
          ),
        )}
      </div>

      {onCancel && (
        <button
          type="button"
          onClick={onCancel}
          className="mt-8 rounded-xl border border-red-800 bg-red-900/30 px-5 py-2 text-sm font-medium text-red-400 hover:bg-red-900/60 transition-colors"
        >
          Cancel Analysis
        </button>
      )}
    </div>
  )
}
