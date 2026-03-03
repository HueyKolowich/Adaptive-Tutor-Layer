# Evaluation Service

File: `src/apps/evaluation_service/service.py`

## Purpose
Separates Q-score evaluation logic from feedback ingestion.

## Responsibilities
- Resolve evaluator config (`Evaluator`).
- Normalize ratings and compute Q-components.
- Persist/update `TurnEvaluation`.

## Scoring
Default weighted score:
- correctness: 0.4
- helpfulness: 0.4
- pedagogy: 0.2

Pedagogy currently uses prompt guardrail tag presence as a heuristic.

## Main Methods
- `evaluate_turn(turn)`
- `evaluate_turn_with_reward_payload(turn)`
