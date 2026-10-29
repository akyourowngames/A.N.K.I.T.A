# Problem: secret scrubber misses split secrets and drifts with vendors

## Problem

Three gaps in the secret scrubber (`secret-scrubber.mjs`), in increasing order
of how unhappy Krish himself said he was about them:

1. **Split secrets are not caught.** Base64 and URL-encoded candidates are
   decoded and re-scanned recursively (up to `MAX_ENCODING_DEPTH = 2`), and
   multi-line PEM keys are fine because the PEM pattern spans lines. But a
   secret deliberately split across string literals and concatenated at
   runtime — `'AK' + 'IA...'` — is not caught. The entropy gate (4.2
   bits/char on unlabeled generic tokens) catches some fragments, but the
   code says it plainly: split messages are outside v1.
2. **Patterns drift and there is no update path.** The 7 patterns are
   hardcoded in `PATTERNS`. Vendors change key formats (AWS changed prefix
   twice in three years) and today there is no auto-update — community PRs
   only. Krish called this the gap he is least happy about in the design.
3. **Shape-only matching causes false positives.** The 7 vendor patterns
   match on shape alone with no entropy check, so a GitHub-looking token in
   a code sample still fires. The entropy gate applies only to generic
   labeled tokens and short bearer candidates.

The strength to preserve: zero model calls — near-zero latency, no rate
limits, no privacy exposure. Any fix that phones home by default breaks the
point of a desktop scrubber.

Source: cubl9snp71hm, Oct 12, 2026, on "How I built a secret scrubber for my
desktop AI assistant". Status: agreed in thread.

## Design

Keep zero-network the default. Any pattern-update channel must be opt-in and
signature-checked. Reduce false positives without weakening true positives:
the entropy gate is a filter, not a verdict.

## Solution

1. Split/concat detection: add a pass that catches secrets assembled at
   runtime from string-literal fragments (concatenation analysis, or scanning
   assembled values where they are built), so `'AK' + 'IA...'` is flagged the
   way a base64-wrapped secret already is.
2. Versioned pattern pack with an opt-in, signature-checked update channel —
   or, if that is too big for one change, a documented pattern-drift
   checklist run before every release (vendor changelog review + community
   PR triage) so drift is caught on a cadence instead of by accident.
3. Apply the entropy gate to vendor-pattern matches in sample/code contexts
   so realistic-looking tokens in examples stop firing, while real secrets
   in credentials-shaped contexts still match on shape.

## Acceptance

- Fixture: runtime-concatenated secret → flagged.
- Fixture: GitHub-looking token inside a code sample → no fire.
- The update path (or the release checklist) is documented, and the default
  install still makes zero network calls.
