# BUGS.md

Open issues as of 2026-04-10. See `docs/archive/BUGS.md` for the original full list filed after Gate 0.2-0.4 (2026-04-02).

## Phase Score Accuracy

- **Backswing**: scoring too tough - penalizing differences that aren't meaningful
- **Follow-through**: scoring too lenient - not catching real deviations
- Per-phase DTW scale factors were tuned (backswing 65.0 more forgiving, follow_through 35.0 stricter) but may need further calibration with real swing data

## Drill Plan Quality

- Drill recommendations could be more grounded in real tennis training methodology
- Drills should connect directly to the 4 golden rules in the coaching prompt
- Needs validation with real swing analyses

## Skeleton Overlay Smoothness

- Frame extraction at 120fps helps but playback smoothness still has room for improvement
- Active work on `feature/skeleton-overlay-clarity` branch addressing this
