#!/usr/bin/env python3
"""Clean runtime development data while preserving baseline config records.

Default behavior:
- Keep default prompts (manual + active + parent_prompt is null; fallback to active prompts).
- Keep all Django users.
- Keep default evaluator `qscore_v0`.
- Delete runtime data: conversations, turns, feedback/evals, bandit state/decisions,
  embeddings/sync jobs, drift runs/signals, GA runs/candidates, and non-kept prompts.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import os
from pathlib import Path
import sys
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = REPO_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

try:
    import django  # noqa: E402
except ModuleNotFoundError as exc:
    venv_python = REPO_ROOT / ".venv" / "bin" / "python"
    if venv_python.exists() and Path(sys.executable).resolve() != venv_python.resolve():
        os.execv(str(venv_python), [str(venv_python), __file__, *sys.argv[1:]])
    print(
        "Django is not available in the current interpreter. "
        "Activate the virtualenv or run .venv/bin/python scripts/clean_dev_db.py",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


django.setup()

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.db.models import Q  # noqa: E402

from apps.drift_detection_service.models import DriftRun, DriftSignal  # noqa: E402
from apps.embedding_service.models import EmbeddingSyncJob, TurnEmbeddingIndex  # noqa: E402
from apps.ga_service.models import PromptEvolutionRun, PromptVariantCandidate  # noqa: E402
from apps.history_service.models import Conversation, Turn  # noqa: E402
from apps.prompt_service.models import BanditUserArmState, Prompt, PromptDecision  # noqa: E402
from apps.ratings_service.models import Evaluator, TurnEvaluation, TurnFeedback  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean dev DB while preserving prompts/users by default.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted/kept without writing changes.",
    )
    parser.add_argument(
        "--drop-users",
        action="store_true",
        help="Delete all Django users.",
    )
    parser.add_argument(
        "--drop-evaluators",
        action="store_true",
        help="Delete all Evaluator rows (default keeps qscore_v0).",
    )
    parser.add_argument(
        "--keep-prompt-id",
        type=int,
        action="append",
        default=[],
        help="Prompt id to preserve (can be repeated).",
    )
    parser.add_argument(
        "--keep-all-prompts",
        action="store_true",
        help="Preserve all prompts and only clean runtime state.",
    )
    parser.add_argument(
        "--no-auto-default-prompts",
        action="store_true",
        help="Disable automatic default prompt preservation logic.",
    )
    parser.add_argument(
        "--no-chroma-clean",
        action="store_true",
        help="Skip ChromaDB cleanup.",
    )
    parser.add_argument(
        "--chroma-url",
        default=None,
        help=(
            "Chroma base URL for cleanup (example: http://localhost:8001). "
            "If omitted, script tries common defaults."
        ),
    )
    return parser.parse_args()


def choose_default_prompt_ids() -> set[int]:
    default_qs = Prompt.objects.filter(
        is_active=True,
        origin='manual',
    ).filter(Q(parent_prompt__isnull=True), Q(status='active'))

    if not default_qs.exists():
        default_qs = Prompt.objects.filter(is_active=True, status='active')

    if not default_qs.exists():
        default_qs = Prompt.objects.order_by('id')[:1]

    return set(default_qs.values_list('id', flat=True))


def build_keep_prompt_ids(args: argparse.Namespace) -> set[int]:
    keep_ids: set[int] = set(args.keep_prompt_id)

    if args.keep_all_prompts:
        keep_ids.update(Prompt.objects.values_list('id', flat=True))
        return keep_ids

    if not args.no_auto_default_prompts:
        keep_ids.update(choose_default_prompt_ids())

    return keep_ids


def print_summary(args: argparse.Namespace, keep_prompt_ids: set[int]) -> None:
    User = get_user_model()

    summary = OrderedDict(
        [
            ("keep_prompts", sorted(keep_prompt_ids)),
            ("keep_users", not args.drop_users),
            ("keep_default_evaluator", not args.drop_evaluators),
            ("clean_chroma", not args.no_chroma_clean),
            ("chroma_url_override", args.chroma_url or ""),
            ("counts_prompt_total", Prompt.objects.count()),
            ("counts_prompt_to_delete", Prompt.objects.exclude(id__in=keep_prompt_ids).count()),
            ("counts_users_to_delete", User.objects.count() if args.drop_users else 0),
            ("counts_conversations", Conversation.objects.count()),
            ("counts_turns", Turn.objects.count()),
            ("counts_feedback", TurnFeedback.objects.count()),
            ("counts_evaluations", TurnEvaluation.objects.count()),
            ("counts_bandit_states", BanditUserArmState.objects.count()),
            ("counts_prompt_decisions", PromptDecision.objects.count()),
            ("counts_embedding_rows", TurnEmbeddingIndex.objects.count()),
            ("counts_embedding_jobs", EmbeddingSyncJob.objects.count()),
            ("counts_drift_runs", DriftRun.objects.count()),
            ("counts_drift_signals", DriftSignal.objects.count()),
            ("counts_ga_runs", PromptEvolutionRun.objects.count()),
            ("counts_ga_candidates", PromptVariantCandidate.objects.count()),
            ("counts_evaluators", Evaluator.objects.count()),
        ]
    )

    print("\nPlanned cleanup summary:")
    for key, value in summary.items():
        print(f"- {key}: {value}")


def run_cleanup(args: argparse.Namespace, keep_prompt_ids: set[int]) -> None:
    User = get_user_model()

    with transaction.atomic():
        # Runtime data
        PromptVariantCandidate.objects.all().delete()
        PromptEvolutionRun.objects.all().delete()
        DriftSignal.objects.all().delete()
        DriftRun.objects.all().delete()
        EmbeddingSyncJob.objects.all().delete()
        TurnEmbeddingIndex.objects.all().delete()
        PromptDecision.objects.all().delete()
        BanditUserArmState.objects.all().delete()
        TurnFeedback.objects.all().delete()
        TurnEvaluation.objects.all().delete()
        Turn.objects.all().delete()
        Conversation.objects.all().delete()

        # Keep only selected prompts
        Prompt.objects.exclude(id__in=keep_prompt_ids).delete()

        # Evaluators
        if args.drop_evaluators:
            Evaluator.objects.all().delete()
        else:
            Evaluator.objects.exclude(name='qscore_v0').delete()

        # Users
        if args.drop_users:
            User.objects.all().delete()


def _candidate_chroma_urls(args: argparse.Namespace) -> list[str]:
    out: list[str] = []
    if args.chroma_url:
        out.append(args.chroma_url)

    env_override = os.getenv("CHROMA_CLEAN_URL", "").strip()
    if env_override:
        out.append(env_override)

    # Host-friendly compose mapping first.
    out.extend(
        [
            "http://localhost:8001",
            "http://127.0.0.1:8001",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ]
    )

    # Settings-derived fallback if provided (often container-to-container hostname).
    settings_host = os.getenv("CHROMA_HOST", "").strip()
    settings_port = os.getenv("CHROMA_PORT", "").strip() or "8000"
    if settings_host:
        out.append(f"http://{settings_host}:{settings_port}")

    deduped = []
    seen = set()
    for item in out:
        normalized = item.rstrip("/")
        if normalized and normalized not in seen:
            deduped.append(normalized)
            seen.add(normalized)
    return deduped


def _chroma_request(base_url: str, method: str, path: str) -> object:
    req = urlrequest.Request(
        f"{base_url}{path}",
        method=method,
        headers={"Accept": "application/json"},
    )
    with urlrequest.urlopen(req, timeout=3) as resp:
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _extract_collection_names(payload: object) -> list[str]:
    if isinstance(payload, list):
        out = []
        for item in payload:
            if isinstance(item, dict):
                name = item.get("name")
                if isinstance(name, str) and name:
                    out.append(name)
        return out

    if isinstance(payload, dict):
        collections = payload.get("collections")
        if isinstance(collections, list):
            return _extract_collection_names(collections)

    return []


def clean_chroma_collections(args: argparse.Namespace, dry_run: bool) -> tuple[bool, str]:
    urls = _candidate_chroma_urls(args)
    last_error = "no candidate URL worked"

    for base_url in urls:
        try:
            heartbeat_ok = _chroma_request(base_url, "GET", "/api/v1/heartbeat")
            _ = heartbeat_ok  # validate request path succeeds
            payload = _chroma_request(base_url, "GET", "/api/v1/collections")
            names = _extract_collection_names(payload)

            if dry_run:
                return True, f"dry-run: would delete {len(names)} collections at {base_url}: {names}"

            deleted = 0
            for name in names:
                encoded = urlparse.quote(name, safe="")
                try:
                    _chroma_request(base_url, "DELETE", f"/api/v1/collections/{encoded}")
                    deleted += 1
                except Exception:
                    # Continue best-effort per collection.
                    pass
            return True, f"deleted {deleted}/{len(names)} collections at {base_url}"
        except Exception as exc:
            if isinstance(exc, urlerror.HTTPError):
                detail = exc.read().decode("utf-8") if exc.fp else ""
                last_error = f"{base_url} HTTP {exc.code}: {detail}"
            else:
                last_error = f"{base_url}: {exc}"

    return False, last_error


def main() -> int:
    args = parse_args()
    keep_prompt_ids = build_keep_prompt_ids(args)

    if not keep_prompt_ids and not args.keep_all_prompts:
        print("No prompt ids selected to keep. Aborting to avoid accidental full prompt wipe.")
        return 2

    print_summary(args, keep_prompt_ids)

    if args.dry_run:
        if not args.no_chroma_clean:
            ok, message = clean_chroma_collections(args, dry_run=True)
            if ok:
                print(f"- chroma_cleanup: {message}")
            else:
                print(f"- chroma_cleanup: skipped ({message})")
        print("\nDry-run only. No changes applied.")
        return 0

    run_cleanup(args, keep_prompt_ids)
    if not args.no_chroma_clean:
        ok, message = clean_chroma_collections(args, dry_run=False)
        if ok:
            print(f"- chroma_cleanup: {message}")
        else:
            print(f"- chroma_cleanup: skipped ({message})")
    print("\nCleanup complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
