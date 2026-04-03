import { Check } from 'lucide-react'

const STEPS = [
  { number: 1, label: 'Choose Stroke' },
  { number: 2, label: 'Upload Video' },
  { number: 3, label: 'Analyze' },
]

/**
 * Horizontal 3-step progress indicator for the upload wizard.
 * Completed steps show a green checkmark, the current step is highlighted,
 * and future steps are dimmed.
 */
export default function WizardStepIndicator({ currentStep }) {
  return (
    <div className="flex items-center justify-center gap-0 mb-8">
      {STEPS.map((step, i) => {
        const isCompleted = currentStep > step.number
        const isCurrent = currentStep === step.number
        const isFuture = currentStep < step.number

        return (
          <div key={step.number} className="flex items-center">
            {/* Step circle + label */}
            <div className="flex flex-col items-center">
              <div
                className={`flex h-9 w-9 items-center justify-center rounded-full text-sm font-bold transition-all duration-300
                  ${isCompleted ? 'bg-[#2D8653] text-white' : ''}
                  ${isCurrent ? 'bg-[#2D8653] text-white ring-4 ring-[#2D8653]/30' : ''}
                  ${isFuture ? 'bg-gray-800 text-gray-500 border border-gray-700' : ''}
                `}
              >
                {isCompleted ? <Check className="h-4 w-4" /> : step.number}
              </div>
              <span
                className={`mt-1.5 text-xs font-medium transition-colors duration-300
                  ${isCurrent ? 'text-white' : isCompleted ? 'text-[#2D8653]' : 'text-gray-500'}
                `}
              >
                {step.label}
              </span>
            </div>

            {/* Connector line (not after last step) */}
            {i < STEPS.length - 1 && (
              <div
                className={`h-0.5 w-16 sm:w-24 mx-2 transition-colors duration-300
                  ${isCompleted ? 'bg-[#2D8653]' : 'bg-gray-700'}
                `}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}
