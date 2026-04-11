# BUGS.md

Filed after Gate 0.2-0.4 real video pipeline run (2026-04-02).

## Phase Score Accuracy

- **Backswing**: scoring too tough — penalizing differences that aren't meaningful
- **Follow-through**: scoring too lenient — not catching real deviations
- **Preparation**: seems okay
- **Forward swing / Contact**: seems okay
- Scoring should reflect how similar the swing is to the pro reference, not an abstract quality score

## Missing Analysis: Base / Lower Body

- No dedicated scoring for the player's base (stance/lower body)
- Need to measure and score:
  - Stance width (how far apart are the feet)
  - Knee bend before and during the shot
  - Overall lower body similarity to the pro reference
- This should be ONE overall "base" score (not per-phase), displayed alongside the phase breakdown

## Missing Analysis: Forward Swing Acceleration

- Not currently measuring acceleration during the forward swing phase
- This is a key indicator of racket head speed and power generation

## Coaching Feedback Quality

- Feedback sounds made up and not accurate to what's actually happening in the video
- Needs golden rules / coaching principles injected into the prompt so Claude has real tennis knowledge to draw from
- Brian's coaching philosophy (inject these as golden rules into the system prompt):
  1. Always sufficiently move to the ball before initiating the backswing
  2. During the backswing the elbow should not be too low - a higher elbow on the backswing ensures optimal torque when doing the forward swing
  3. Stay balanced on your feet while hitting through the contact point
  4. On the follow-through the tip of the racquet should ideally point diagonally downward toward the left side pocket of the player's pants

## Drill Plan Quality

- Drill recommendations are inaccurate for the same reason as coaching feedback
- Drills should be grounded in real tennis training methodology, not invented
- Drills should connect directly to the golden rules above

## Skeleton Overlay

- Tracking is reasonably accurate, no major alignment issues
- Frames could be smoother - consider extracting more frames from the video for higher fidelity playback

## Frontend Polish

- [ ] Video should default to 0.25x playback speed (currently defaults to 1x)
- [ ] Video should auto-play in a loop on load

## Upload Page (Marketing-Ready Redesign)

### Guided step flow
- Redesign as a clear 3-step wizard:
  - **Step 1**: Choose your stroke type
  - **Step 2**: Upload a court-level video of yourself
  - **Step 3**: Run the comparison analysis

### Grip selection (dependent on stroke type)
- When user selects "Forehand", show a dependent "Forehand Grip" selector with images of each grip:
  - Semi-Western (Jannik Sinner, Carlos Alcaraz)
  - Modified Eastern (Roger Federer)
  - Eastern (Bautista Agut, JJ Wolf)
  - Western (Kei Nishikori, Taylor Fritz)
- Grip selection determines the available pro players to compare against
- Each grip option should show an image of the grip
- Each player option should show a headshot/face image

### New stroke types
- [ ] Add "Buggy-Whip Forehand" stroke type
- [ ] Add "Slice" stroke type
- These need to be added to the backend enum as well as frontend selectors

## Library Page

- [ ] Add a short description field for pro reference videos (editable, shown on card)

## History Page

- [ ] Allow deleting a single analysis
- [ ] Bulk delete via checkboxes (select multiple, then delete)
- [ ] Backend: `DELETE /api/analysis/{id}` endpoint
- [ ] Backend: `DELETE /api/analysis/bulk` endpoint (accepts list of IDs)
