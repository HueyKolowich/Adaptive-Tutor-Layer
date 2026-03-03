# GA Service (Per-User Prompt Evolution)

Files:
- `src/apps/ga_service/service.py`
- `src/apps/ga_service/models.py`

## Purpose
GA Service generates prompt variants for a specific learner and publishes them as learner-private candidate arms.

It is an evolutionary boundary service, but current generation logic is still a deterministic placeholder (single-generation mutation, no crossover/population loop).

## Input Contract
### `generate_variants(parent_prompt_id, subject_user_id, drift_signal_id=None, k=3)`
- `subject_user_id` is required.
- `parent_prompt_id` is optional; when absent, GA resolves parent by learner posterior.
- `drift_signal_id` links run lineage to drift trigger when provided.

## Parent Prompt Resolution
Implemented in `resolve_parent_prompt_for_user(subject_user_id)`.

Rule order:
1. Query learner's `BanditUserArmState` rows where prompt is active and visible to learner.
2. Compute posterior mean for each arm:
   - `lambda = lambda0 + nu`
   - `mu = (lambda0*mu0 + eta) / lambda`
3. Select arm with max `mu`.
4. Fallback to latest global active manual prompt.
5. Secondary fallback: latest global active prompt.

Visibility constraint used throughout:
- `prompt.owner_user_id IS NULL OR prompt.owner_user_id = subject_user_id`

## Variant Generation Algorithm (Current)
For `n = max(1, int(k))` drafts:
1. Choose mutation operator by cyclic index from:
   - `tone_supportive`
   - `scaffold_depth`
   - `misconception_probe`
   - `hint_cadence`
2. Build candidate text by appending a deterministic operator-specific suffix:
   - format: `"<parent text>\n\n[GA:<operator>] <suffix>"`
3. Score candidate via deterministic hash score:
   - SHA-256(text), first 32 bits normalized to `[0,1]`.
4. Safety-check candidate with lexical denylist:
   - rejects if text contains blocked substrings.

Candidates passing safety are sorted by score descending, then published.

## Publication Semantics
For each published candidate:
- create `Prompt` with:
  - `origin='ga'`
  - `status='candidate'`
  - `rollout_pct=0.10`
  - `owner_user_id=subject_user_id`
  - `parent_prompt=<resolved parent>`
  - lineage metadata including evolution run and mutation operator
- create `PromptVariantCandidate(status='published')` row linked to prompt.

Promotion does not change ownership; learner-private prompts remain learner-private.

## Persistence Model
### `PromptEvolutionRun`
Tracks one generation invocation.
Key fields:
- `subject_user_id`
- `parent_prompt`
- `drift_signal` (optional)
- `requested_by` (`system` for drift-triggered, `manual` otherwise)
- generation/publish counts and timestamps

### `PromptVariantCandidate`
Tracks generated artifact metadata and published prompt linkage.

## Event Emission
On successful run:
- `ga.variants_generated`
- envelope user scope: `user_id = subject_user_id`
- payload includes:
  - `subject_user_id`
  - `parent_prompt_id`
  - `generated_count`
  - `published_count`
- panel edge emitted as `ga -> policies`.

## Current Limits
- No crossover.
- No multi-generation population state.
- No model-based fitness from online reward yet.
- Safety is lexical, not classifier-backed.

## Why This Is Acceptable Right Now
The service currently prioritizes:
- deterministic behavior,
- reproducible lineage,
- strict learner isolation,
- low operational complexity.

This keeps experimentation safe while establishing stable interfaces for later full GA implementations.
