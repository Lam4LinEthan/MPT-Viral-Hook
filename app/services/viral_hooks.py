"""
Viral Hook Agent — generates, evaluates, and selects viral hooks
before the main video script is generated.

This module intercepts the standard script generation pipeline to:
1. Generate 5 candidate viral hooks via the configured LLM.
2. Evaluate each hook on a 1-10 scale (curiosity, emotion, specificity, brevity).
3. Select the highest-scoring hook.
4. Optionally log all results to Supabase.
"""

import json
import re
from typing import List, Optional

from loguru import logger

from app.config import config
from app.services.llm import _generate_response

_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# 1. Generate hooks
# ---------------------------------------------------------------------------

def generate_hooks(video_subject: str, language: str = "") -> List[str]:
    """Ask the LLM to produce 5 viral opening hooks for *video_subject*.

    Returns a list of five hook strings, or an empty list on failure.
    """
    prompt = f"""
# Role: Viral Hook Generator

## Goal:
Generate exactly 5 short, attention-grabbing opening hooks for a short-form video about the subject below.
Each hook should be 1-2 sentences maximum and designed to stop a viewer from scrolling.

## Techniques to use (vary across the 5 hooks):
- Curiosity gap ("You won't believe…", "Most people don't know…")
- Bold / controversial claim
- Shocking statistic or fact
- Direct question to the viewer
- Storytelling opener ("I was shocked when…")

## Constraints:
1. Return ONLY a JSON array of 5 strings — no markdown, no explanation.
2. Each hook must be self-contained (one or two sentences).
3. Do NOT include hashtags, emojis, or formatting.
4. Respond in the same language as the video subject.

## Output format:
["hook 1", "hook 2", "hook 3", "hook 4", "hook 5"]

## Video Subject:
{video_subject}
""".strip()

    if language:
        prompt += f"\n## Language: {language}"

    for attempt in range(_MAX_RETRIES):
        try:
            response = _generate_response(prompt)
            if not response or "Error: " in response:
                logger.warning(f"hook generation attempt {attempt + 1} returned error: {response}")
                continue

            hooks = json.loads(response)
            if isinstance(hooks, list) and len(hooks) == 5 and all(isinstance(h, str) for h in hooks):
                logger.info(f"generated {len(hooks)} hooks on attempt {attempt + 1}")
                return hooks

            # Try to extract JSON array from response
            match = re.search(r"\[.*]", response, re.DOTALL)
            if match:
                hooks = json.loads(match.group())
                if isinstance(hooks, list) and all(isinstance(h, str) for h in hooks):
                    logger.info(f"extracted {len(hooks)} hooks on attempt {attempt + 1}")
                    return hooks[:5]

            logger.warning(f"hook generation attempt {attempt + 1}: unexpected format")
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"hook generation attempt {attempt + 1} failed: {exc}")

    logger.error("failed to generate hooks after all retries")
    return []


# ---------------------------------------------------------------------------
# 2. Evaluate hooks
# ---------------------------------------------------------------------------

def evaluate_hooks(hooks: List[str], video_subject: str) -> List[dict]:
    """Score each hook on a 1-10 scale and return a sorted list (best first).

    Each item in the returned list is:
        {"hook": str, "score": int, "reasoning": str}
    """
    hooks_formatted = "\n".join(f"{i + 1}. {h}" for i, h in enumerate(hooks))

    prompt = f"""
# Role: Viral Hook Evaluator

## Goal:
Evaluate each of the following hooks for a video about "{video_subject}".
Score each hook from 1 to 10 based on these criteria:
- **Curiosity gap** — Does it make the viewer NEED to keep watching?
- **Emotional impact** — Does it trigger a strong emotion (surprise, fear, excitement)?
- **Specificity** — Does it feel concrete rather than vague?
- **Brevity** — Is it punchy and concise?

## Hooks to evaluate:
{hooks_formatted}

## Constraints:
1. Return ONLY a JSON array — no markdown fences, no explanation outside the array.
2. Each element must be an object with keys: "hook", "score", "reasoning".
3. "score" must be an integer from 1 to 10.
4. Sort the array from highest score to lowest.

## Output format:
[{{"hook": "...", "score": 9, "reasoning": "..."}}, ...]
""".strip()

    for attempt in range(_MAX_RETRIES):
        try:
            response = _generate_response(prompt)
            if not response or "Error: " in response:
                logger.warning(f"hook evaluation attempt {attempt + 1} returned error: {response}")
                continue

            evaluated = json.loads(response)
            if not isinstance(evaluated, list):
                # Try extracting the JSON array
                match = re.search(r"\[.*]", response, re.DOTALL)
                if match:
                    evaluated = json.loads(match.group())

            if isinstance(evaluated, list) and len(evaluated) > 0:
                # Ensure proper structure & sort by score descending
                valid = []
                for item in evaluated:
                    if isinstance(item, dict) and "hook" in item and "score" in item:
                        item["score"] = int(item["score"])
                        item.setdefault("reasoning", "")
                        valid.append(item)
                valid.sort(key=lambda x: x["score"], reverse=True)
                if valid:
                    logger.info(f"evaluated {len(valid)} hooks on attempt {attempt + 1}")
                    return valid

            logger.warning(f"hook evaluation attempt {attempt + 1}: unexpected format")
        except (json.JSONDecodeError, Exception) as exc:
            logger.warning(f"hook evaluation attempt {attempt + 1} failed: {exc}")

    logger.error("failed to evaluate hooks after all retries")
    return []


# ---------------------------------------------------------------------------
# 3. Select best hook
# ---------------------------------------------------------------------------

def select_best_hook(evaluated_hooks: List[dict]) -> Optional[dict]:
    """Return the highest-scoring hook dict, or None."""
    if not evaluated_hooks:
        return None
    return evaluated_hooks[0]


# ---------------------------------------------------------------------------
# 4. Orchestrator
# ---------------------------------------------------------------------------

def run_viral_hook_pipeline(
    video_subject: str,
    language: str = "",
    task_id: str = "",
) -> str:
    """Full pipeline: generate → evaluate → select → log.

    Returns the winning hook string, or empty string on failure.
    """
    logger.info("\n\n## Viral Hook Agent — starting pipeline")

    # Check feature toggle
    if not config.app.get("enable_viral_hooks", True):
        logger.info("viral hooks disabled via config, skipping")
        return ""

    # Step 1: Generate
    hooks = generate_hooks(video_subject, language)
    if not hooks:
        logger.warning("viral hook agent: no hooks generated")
        return ""

    logger.info(f"viral hook candidates:\n" + "\n".join(f"  {i+1}. {h}" for i, h in enumerate(hooks)))

    # Step 2: Evaluate
    evaluated = evaluate_hooks(hooks, video_subject)
    if not evaluated:
        # Fallback: just pick the first hook without scoring
        logger.warning("viral hook agent: evaluation failed, falling back to first hook")
        winner_hook = hooks[0]
        winner_score = 0
        evaluated = [{"hook": h, "score": 0, "reasoning": "evaluation unavailable"} for h in hooks]
    else:
        winner = select_best_hook(evaluated)
        winner_hook = winner["hook"]
        winner_score = winner["score"]

    logger.success(
        f"viral hook selected (score={winner_score}): {winner_hook}"
    )

    # Step 3: Log to Supabase (fire-and-forget)
    try:
        from app.services.supabase_logger import log_hook_results

        log_hook_results(
            task_id=task_id,
            video_subject=video_subject,
            hooks=hooks,
            evaluated_hooks=evaluated,
            selected_hook=winner_hook,
            selected_score=winner_score,
        )
    except Exception as exc:
        logger.debug(f"supabase logging skipped or failed: {exc}")

    return winner_hook


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    subject = "Why most people fail at saving money"
    result = run_viral_hook_pipeline(video_subject=subject, task_id="test-001")
    print(f"\n{'='*60}")
    print(f"Winning hook: {result}")
