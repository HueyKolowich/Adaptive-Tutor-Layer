# Prompt Service (Current Implementation)

Files:
- `src/apps/prompt_service/service.py`
- `src/apps/prompt_service/models.py`

## Purpose
Prompt Service is the online policy layer that performs per-learner prompt-arm selection and posterior updates. It now enforces prompt visibility isolation:
- global prompts (`owner_user_id IS NULL`) are shared,
- learner-owned prompts (`owner_user_id = learner`) are private.

## Prompt Ownership Model
`Prompt.owner_user_id` controls visibility:
- `NULL`: global policy arm.
- `<user_id>`: learner-private arm (typically GA-generated).

Selection for learner `L` is constrained to:
- `is_active=True`,
- `status != retired`,
- `(owner_user_id IS NULL OR owner_user_id = L)`.

## Bandit Core
Per `(learner_id, prompt_id)` posterior state is stored in `BanditUserArmState`.

Posterior parameters:
- `lambda = lambda0 + nu`
- `mu = (lambda0*mu0 + eta) / lambda`

Thompson sampling draw per arm:
- `theta ~ Normal(mu, alpha^2 / lambda)`

Selected arm is argmax of sampled `theta`, with streak guardrail fallback.

## Candidate Rollout Gate
For `status='candidate'`, eligibility is deterministic per learner/conversation/prompt:
- key: `"{user_id}:{conversation_id}:{prompt_id}"`
- hash: SHA-256
- include if `normalized_hash < rollout_pct`

This keeps rollout deterministic while preserving stochastic-looking distribution across users/conversations.

## Selection Trace
`select_system_prompt_with_trace(...)` returns:
- selected prompt id,
- sampled theta,
- guardrail flag,
- candidate-level posterior/sample diagnostics.

Event payload compatibility is preserved (no event renames).

## Reward Update Path
Rewards are derived from `TurnEvaluation.q_total` and applied to unresolved `PromptDecision` rows.

Update equations (discounted):
- `eta <- gamma*eta + tau_r*r`
- `nu <- gamma*nu + tau_r`
- `effective_n <- gamma*effective_n + 1`
- where `tau_r = 1/sigma_r^2`, and `r` is clipped to `[0,1]`.

## Baseline Compatibility
Baseline control prompt is resolved outside Prompt Service and constrained to global prompts (`owner_user_id IS NULL`) to avoid accidental learner-private control policies.

## Constraints / Current Limits
- Context is learner-id partition only (no feature-vector contextual model yet).
- Candidate rollout is hash-gated, not adaptive traffic optimization.
- Reward aggregation is turn-level mean of evaluation rows.
