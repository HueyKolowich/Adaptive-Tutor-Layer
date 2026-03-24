#!/usr/bin/env python3
"""Run a local simulated-student demo against Adaptive Tutor APIs.

This harness drives the real HTTP pipeline:
- POST /api/tutor/respond
- POST /api/turns/<turn_id>/feedback

The simulated student is a separate OpenAI-compatible local model endpoint.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import random
import sys
import time
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest


DEFAULT_API_BASE = "http://127.0.0.1:8000"
DEFAULT_PANEL_BASE = "http://127.0.0.1:3001"
DEFAULT_USER_ID = "demo-learner-01"
DEFAULT_PERSONA = "socratic_novice"
DEFAULT_TURNS = 30
DEFAULT_SEED = 42
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_RETRIES = 3
DEFAULT_TIMEOUT = 20
DEFAULT_SLEEP_MS = 150
DEFAULT_TRANSCRIPT_WINDOW = 4
DEFAULT_STUDENT_MAX_TOKENS = 300


class HarnessError(RuntimeError):
    """Raised when the simulation cannot safely continue."""


@dataclass
class TurnRecord:
    turn_id: str
    turn_index: int
    question_text: str
    tutor_response: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run simulated student demo against local APIs.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--panel-base", default=DEFAULT_PANEL_BASE)
    parser.add_argument("--student-llm-url", required=True)
    parser.add_argument("--student-model", required=True)
    parser.add_argument("--student-api-key", default="")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--conversation-id", default="")
    parser.add_argument("--persona", default=DEFAULT_PERSONA)
    parser.add_argument("--turns", type=int, default=DEFAULT_TURNS)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--max-retries", type=int, default=DEFAULT_MAX_RETRIES)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--sleep-ms", type=int, default=DEFAULT_SLEEP_MS)
    parser.add_argument("--transcript-window", type=int, default=DEFAULT_TRANSCRIPT_WINDOW)
    parser.add_argument("--student-max-tokens", type=int, default=DEFAULT_STUDENT_MAX_TOKENS)
    parser.add_argument(
        "--profiles-path",
        default=str(Path(__file__).resolve().parent / "student_profiles.json"),
    )
    return parser.parse_args()


def load_profiles(path: str) -> dict[str, dict[str, Any]]:
    try:
        raw = Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
    except Exception as exc:
        raise HarnessError(f"Failed to load profiles from {path}: {exc}") from exc

    if not isinstance(data, dict) or not data:
        raise HarnessError(f"Profile file {path} must contain a non-empty JSON object.")

    required_keys = {"system_prompt", "question_style", "feedback_rubric", "noise", "target_topic"}
    for name, profile in data.items():
        if not isinstance(profile, dict):
            raise HarnessError(f"Profile '{name}' must be an object.")
        missing = sorted(required_keys - set(profile.keys()))
        if missing:
            raise HarnessError(f"Profile '{name}' missing keys: {', '.join(missing)}")
    return data


def clamp_rating(value: Any) -> int:
    try:
        rating = int(round(float(value)))
    except Exception:
        rating = 3
    return max(1, min(5, rating))


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : idx + 1]

    return None


def _parse_json_object(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    fragment = _extract_first_json_object(text)
    if not fragment:
        return None

    try:
        parsed = json.loads(fragment)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _sleep_backoff(attempt: int, base_seconds: float = 0.35) -> None:
    time.sleep(base_seconds * (2**attempt))


def _http_json(
    *,
    method: str,
    url: str,
    payload: dict[str, Any] | None,
    timeout: int,
    headers: dict[str, str] | None = None,
    max_retries: int = 0,
    retry_statuses: tuple[int, ...] = (429, 500, 502, 503, 504),
) -> tuple[int, dict[str, Any]]:
    body = None
    req_headers = {
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    for attempt in range(max_retries + 1):
        req = urlrequest.Request(url=url, data=body, method=method.upper(), headers=req_headers)
        try:
            with urlrequest.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, dict):
                    parsed = {"data": parsed}
                return int(resp.status), parsed
        except urlerror.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            try:
                parsed = json.loads(raw) if raw else {}
                if not isinstance(parsed, dict):
                    parsed = {"data": parsed}
            except Exception:
                parsed = {"detail": raw or str(exc)}

            if int(exc.code) in retry_statuses and attempt < max_retries:
                _sleep_backoff(attempt)
                continue
            return int(exc.code), parsed
        except (urlerror.URLError, TimeoutError) as exc:
            if attempt < max_retries:
                _sleep_backoff(attempt)
                continue
            raise HarnessError(f"HTTP request failed ({method} {url}): {exc}") from exc

    raise HarnessError(f"Request exhausted retries: {method} {url}")


def llm_chat(
    *,
    url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: int,
    max_retries: int,
) -> str:
    headers = {
        "User-Agent": "student-sim-demo/1.0",
    }
    if api_key.strip():
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    status, data = _http_json(
        method="POST",
        url=url,
        payload={
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=timeout,
        headers=headers,
        max_retries=max_retries,
    )

    if status < 200 or status >= 300:
        raise HarnessError(f"Student LLM returned HTTP {status}: {data}")

    if isinstance(data.get("choices"), list) and data["choices"]:
        choice0 = data["choices"][0]
        if isinstance(choice0, dict):
            msg = choice0.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"]

    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    raise HarnessError(f"Student LLM response missing text content: {data}")


def build_transcript_snippet(history: list[TurnRecord], window: int) -> str:
    recent = history[-window:]
    if not recent:
        return "(no prior turns)"

    lines: list[str] = []
    for item in recent:
        q = item.question_text.strip().replace("\n", " ")
        a = item.tutor_response.strip().replace("\n", " ")
        lines.append(f"Turn {item.turn_index} student: {q[:240]}")
        lines.append(f"Turn {item.turn_index} tutor: {a[:320]}")
    return "\n".join(lines)


def generate_question(
    *,
    llm_url: str,
    llm_key: str,
    llm_model: str,
    temperature: float,
    timeout: int,
    max_retries: int,
    max_tokens: int,
    persona_name: str,
    profile: dict[str, Any],
    history: list[TurnRecord],
    turn_number: int,
    transcript_window: int,
    rng: random.Random,
) -> str:
    transcript = build_transcript_snippet(history, transcript_window)
    style = profile.get("question_style", "")
    topic = profile.get("target_topic", "foundational math")

    sys_prompt = (
        f"{profile.get('system_prompt', '')}\n"
        "You are generating the student's next message in a tutoring chat.\n"
        "Return ONLY valid JSON with one key: question_text."
    )
    user_prompt = (
        f"Persona: {persona_name}\n"
        f"Topic focus: {topic}\n"
        f"Turn number: {turn_number}\n"
        f"Question style constraints:\n{style}\n\n"
        f"Recent transcript:\n{transcript}\n\n"
        "Output format exactly:\n"
        '{"question_text":"..."}\n'
        "No markdown. No commentary."
    )

    raw = llm_chat(
        url=llm_url,
        api_key=llm_key,
        model=llm_model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )

    parsed = _parse_json_object(raw)
    question = parsed.get("question_text") if parsed else None
    if isinstance(question, str) and question.strip():
        return question.strip()

    repair = llm_chat(
        url=llm_url,
        api_key=llm_key,
        model=llm_model,
        messages=[
            {
                "role": "system",
                "content": "Convert text into strict JSON. Return JSON only.",
            },
            {
                "role": "user",
                "content": (
                    "Rewrite this output as exactly {'question_text':'...'} JSON and nothing else:\n"
                    f"{raw}"
                ),
            },
        ],
        temperature=0.0,
        max_tokens=120,
        timeout=timeout,
        max_retries=max_retries,
    )
    repaired = _parse_json_object(repair)
    question = repaired.get("question_text") if repaired else None
    if isinstance(question, str) and question.strip():
        return question.strip()

    fallback_templates = [
        "I still feel shaky on {topic}. What is the most important idea to master next?",
        "Can we do one concrete example for {topic} and then check my understanding?",
        "What is a common mistake in {topic}, and how can I avoid it?",
        "Could you give me a small practice problem about {topic} and guide me?",
    ]
    template = fallback_templates[(turn_number + rng.randint(0, 1000)) % len(fallback_templates)]
    return template.format(topic=topic)


def generate_feedback(
    *,
    llm_url: str,
    llm_key: str,
    llm_model: str,
    temperature: float,
    timeout: int,
    max_retries: int,
    max_tokens: int,
    persona_name: str,
    profile: dict[str, Any],
    question_text: str,
    tutor_response: str,
    transcript: str,
    rng: random.Random,
) -> dict[str, Any]:
    rubric = profile.get("feedback_rubric", {})

    sys_prompt = (
        f"{profile.get('system_prompt', '')}\n"
        "You are grading a tutor response from the simulated student's perspective.\n"
        "Return ONLY valid JSON."
    )
    user_prompt = (
        f"Persona: {persona_name}\n"
        f"Rubric:\n{json.dumps(rubric, indent=2)}\n\n"
        f"Student question:\n{question_text}\n\n"
        f"Tutor response:\n{tutor_response[:1800]}\n\n"
        f"Recent transcript:\n{transcript}\n\n"
        "Return JSON only with keys:\n"
        '{"rating_perceived_progress":1-5,"rating_clarity_understanding":1-5,'
        '"rating_engagement_fit":1-5,"free_text":"optional brief comment"}'
    )

    raw = llm_chat(
        url=llm_url,
        api_key=llm_key,
        model=llm_model,
        messages=[
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        max_retries=max_retries,
    )

    parsed = _parse_json_object(raw)
    if not parsed:
        repair = llm_chat(
            url=llm_url,
            api_key=llm_key,
            model=llm_model,
            messages=[
                {
                    "role": "system",
                    "content": "Convert text into strict JSON. Return JSON only.",
                },
                {
                    "role": "user",
                    "content": (
                        "Rewrite this output as strict feedback JSON with ratings 1-5 and free_text:\n"
                        f"{raw}"
                    ),
                },
            ],
            temperature=0.0,
            max_tokens=180,
            timeout=timeout,
            max_retries=max_retries,
        )
        parsed = _parse_json_object(repair) or {}

    feedback = {
        "rating_perceived_progress": clamp_rating(parsed.get("rating_perceived_progress", 3)),
        "rating_clarity_understanding": clamp_rating(parsed.get("rating_clarity_understanding", 3)),
        "rating_engagement_fit": clamp_rating(parsed.get("rating_engagement_fit", 3)),
        "free_text": str(parsed.get("free_text", "")).strip()[:240] or None,
    }

    noise = profile.get("noise", {}) if isinstance(profile.get("noise"), dict) else {}
    prob = float(noise.get("jitter_probability", 0.0) or 0.0)
    max_delta = int(noise.get("max_delta", 0) or 0)
    if prob > 0 and max_delta > 0:
        for key in (
            "rating_perceived_progress",
            "rating_clarity_understanding",
            "rating_engagement_fit",
        ):
            if rng.random() < prob:
                delta = rng.randint(-max_delta, max_delta)
                feedback[key] = clamp_rating(feedback[key] + delta)

    return feedback


def get_turn_from_history(
    *,
    api_base: str,
    conversation_id: str,
    user_id: str,
    turn_id: str,
    timeout: int,
    max_retries: int,
) -> dict[str, Any] | None:
    url = (
        f"{api_base.rstrip('/')}/api/conversations/{conversation_id}/history"
        f"?user_id={user_id}"
    )
    status, data = _http_json(
        method="GET",
        url=url,
        payload=None,
        timeout=timeout,
        max_retries=max_retries,
    )
    if status != 200:
        return None
    turns = data.get("turns")
    if not isinstance(turns, list):
        return None
    for row in turns:
        if isinstance(row, dict) and str(row.get("turn_id", "")) == turn_id:
            return row
    return None


def submit_feedback(
    *,
    api_base: str,
    turn_id: str,
    user_id: str,
    feedback: dict[str, Any],
    timeout: int,
    max_retries: int,
) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/api/turns/{turn_id}/feedback"
    payload = {
        "user_id": user_id,
        "rating_perceived_progress": clamp_rating(feedback.get("rating_perceived_progress", 3)),
        "rating_clarity_understanding": clamp_rating(feedback.get("rating_clarity_understanding", 3)),
        "rating_engagement_fit": clamp_rating(feedback.get("rating_engagement_fit", 3)),
        "free_text": feedback.get("free_text"),
    }

    status, data = _http_json(
        method="POST",
        url=url,
        payload=payload,
        timeout=timeout,
        max_retries=max_retries,
    )
    if status != 201:
        raise HarnessError(f"Feedback submit failed for turn {turn_id}: HTTP {status} {data}")
    return data


def run(args: argparse.Namespace) -> int:
    if args.turns < 1:
        raise HarnessError("--turns must be >= 1")
    if args.max_retries < 0:
        raise HarnessError("--max-retries must be >= 0")
    if args.timeout < 1:
        raise HarnessError("--timeout must be >= 1")

    profiles = load_profiles(args.profiles_path)
    if args.persona not in profiles:
        available = ", ".join(sorted(profiles.keys()))
        raise HarnessError(f"Unknown persona '{args.persona}'. Available: {available}")

    profile = profiles[args.persona]
    rng = random.Random(args.seed)

    conversation_id = args.conversation_id.strip() or ""
    history: list[TurnRecord] = []
    panel_url_printed = False

    for turn_no in range(1, args.turns + 1):
        transcript = build_transcript_snippet(history, args.transcript_window)
        question_text = generate_question(
            llm_url=args.student_llm_url,
            llm_key=args.student_api_key,
            llm_model=args.student_model,
            temperature=args.temperature,
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_tokens=args.student_max_tokens,
            persona_name=args.persona,
            profile=profile,
            history=history,
            turn_number=turn_no,
            transcript_window=args.transcript_window,
            rng=rng,
        )

        gate_attempts = 0
        while True:
            status, data = _http_json(
                method="POST",
                url=f"{args.api_base.rstrip('/')}/api/tutor/respond",
                payload={
                    "user_id": args.user_id,
                    "conversation_id": conversation_id or None,
                    "question_text": question_text,
                },
                timeout=args.timeout,
                max_retries=args.max_retries,
            )

            if status == 200:
                break

            if status == 409 and data.get("code") == "feedback_required":
                missing_turn_id = str(data.get("last_turn_id", "")).strip()
                if not missing_turn_id:
                    raise HarnessError(f"Feedback gate returned no turn id: {data}")
                gate_attempts += 1
                if gate_attempts > 3:
                    raise HarnessError(f"Feedback gate repeated too many times for turn {missing_turn_id}")

                if conversation_id:
                    missing = get_turn_from_history(
                        api_base=args.api_base,
                        conversation_id=conversation_id,
                        user_id=args.user_id,
                        turn_id=missing_turn_id,
                        timeout=args.timeout,
                        max_retries=args.max_retries,
                    )
                else:
                    missing = None

                missing_question = str((missing or {}).get("user_text") or "Can you explain this in another way?")
                missing_response = str((missing or {}).get("assistant_text") or "")
                missing_transcript = build_transcript_snippet(history, args.transcript_window)
                missing_feedback = generate_feedback(
                    llm_url=args.student_llm_url,
                    llm_key=args.student_api_key,
                    llm_model=args.student_model,
                    temperature=args.temperature,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                    max_tokens=args.student_max_tokens,
                    persona_name=args.persona,
                    profile=profile,
                    question_text=missing_question,
                    tutor_response=missing_response,
                    transcript=missing_transcript,
                    rng=rng,
                )
                submit_feedback(
                    api_base=args.api_base,
                    turn_id=missing_turn_id,
                    user_id=args.user_id,
                    feedback=missing_feedback,
                    timeout=args.timeout,
                    max_retries=args.max_retries,
                )
                continue

            raise HarnessError(f"Tutor respond failed: HTTP {status} {data}")

        response_text = str(data.get("tutor_response", ""))
        turn_id = str(data.get("turn_id", "")).strip()
        if not turn_id:
            raise HarnessError(f"Tutor respond missing turn_id: {data}")

        if data.get("conversation_id"):
            conversation_id = str(data["conversation_id"])

        if conversation_id and not panel_url_printed:
            panel_url = f"{args.panel_base.rstrip('/')}/?conversation_id={conversation_id}"
            print(f"panel={panel_url}")
            panel_url_printed = True

        feedback = generate_feedback(
            llm_url=args.student_llm_url,
            llm_key=args.student_api_key,
            llm_model=args.student_model,
            temperature=args.temperature,
            timeout=args.timeout,
            max_retries=args.max_retries,
            max_tokens=args.student_max_tokens,
            persona_name=args.persona,
            profile=profile,
            question_text=question_text,
            tutor_response=response_text,
            transcript=transcript,
            rng=rng,
        )

        submit_feedback(
            api_base=args.api_base,
            turn_id=turn_id,
            user_id=args.user_id,
            feedback=feedback,
            timeout=args.timeout,
            max_retries=args.max_retries,
        )

        history.append(
            TurnRecord(
                turn_id=turn_id,
                turn_index=int(data.get("turn_index", turn_no)),
                question_text=question_text,
                tutor_response=response_text,
            )
        )

        q_preview = question_text.strip().replace("\n", " ")[:120]
        print(
            f"turn={turn_no} question=\"{q_preview}\" "
            f"prompt_response_len={len(response_text)} "
            f"ratings=({feedback['rating_perceived_progress']},"
            f"{feedback['rating_clarity_understanding']},"
            f"{feedback['rating_engagement_fit']})"
        )

        if args.sleep_ms > 0:
            time.sleep(args.sleep_ms / 1000.0)

    print(
        f"completed turns={args.turns} user_id={args.user_id} "
        f"conversation_id={conversation_id or '(unknown)'}"
    )
    return 0


def main() -> int:
    args = parse_args()
    try:
        return run(args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
