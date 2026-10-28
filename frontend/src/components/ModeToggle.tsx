import { CALIBRATION_MODES, MODE_LABELS, type CalibrationMode } from "../api/client";

/** Segmented control for the calibration mode. Decision-time is the default. */
export function ModeToggle({
  mode,
  onChange,
}: {
  mode: CalibrationMode;
  onChange: (next: CalibrationMode) => void;
}) {
  const options: CalibrationMode[] = [
    CALIBRATION_MODES.decisionTime,
    CALIBRATION_MODES.retrospective,
  ];
  return (
    <div className="inline-flex rounded-md border border-slate-300 bg-white p-0.5 shadow-sm">
      {options.map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={mode === value}
          onClick={() => onChange(value)}
          className={`rounded px-3 py-1.5 text-sm font-medium transition ${
            mode === value ? "bg-sky-600 text-white" : "text-slate-600 hover:bg-slate-100"
          }`}
        >
          {MODE_LABELS[value]}
        </button>
      ))}
    </div>
  );
}
