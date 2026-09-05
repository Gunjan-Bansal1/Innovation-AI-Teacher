"""
Adaptation Agent — recommends next teaching strategy.

Gemma recommends an action.
FastAPI validates the action is in the allowed set.
Never repeats the same strategy twice in a row.
"""
from typing import Optional

from app.services.ollama_service import ollama_service
from app.schemas.evaluation import AdaptationDecision, AdaptationAction
from app.prompts.misconception import build_adaptation_prompt
from app.prompts.system_teacher import SYSTEM_EVALUATOR
from app.core.logging import get_logger

logger = get_logger(__name__)

ALLOWED_ACTIONS = {a.value for a in AdaptationAction}


class AdaptationAgent:
    """Decides the next teaching strategy based on student performance."""

    async def decide(
        self,
        concept_key: str,
        evaluation_status: str,
        understanding: str,
        misconception: Optional[str],
        session_history: list[str],
        level: str,
        teaching_style: str,
        last_action: Optional[str],
    ) -> AdaptationDecision:
        """
        Recommend the next teaching action.

        Gemma proposes → FastAPI validates → Orchestrator executes.
        The same action as last_action is explicitly forbidden.
        """
        prompt = build_adaptation_prompt(
            concept_key=concept_key,
            evaluation_status=evaluation_status,
            understanding=understanding,
            misconception=misconception,
            session_history=session_history,
            level=level,
            teaching_style=teaching_style,
            last_action=last_action,
        )

        try:
            result = await ollama_service.generate_structured(
                prompt=prompt,
                schema=AdaptationDecision,
                system=SYSTEM_EVALUATOR,
                temperature=0.3,
            )

            # FastAPI validation: ensure action is in allowed set
            if result.action.value not in ALLOWED_ACTIONS:
                logger.warning(
                    f"Gemma proposed invalid action: {result.action}. Defaulting to RETEACH."
                )
                result.action = AdaptationAction.RETEACH

            # Enforce: don't repeat the same action
            if last_action and result.action.value == last_action:
                result.action = self._select_fallback_action(
                    evaluation_status, last_action
                )
                result.reason = f"Switching strategy (previous was {last_action})"

            logger.info(
                "Adaptation decision",
                extra={
                    "action": result.action,
                    "concept": concept_key,
                    "last_action": last_action,
                },
            )
            return result

        except Exception as e:
            logger.error(f"Adaptation decision failed: {e}")
            return AdaptationDecision(
                action=AdaptationAction.RETEACH,
                reason="Defaulting to reteach due to error",
            )

    def _select_fallback_action(
        self,
        evaluation_status: str,
        last_action: str,
    ) -> AdaptationAction:
        """Select a fallback when the recommended action equals the last action."""
        if evaluation_status in ("incorrect", "unclear"):
            fallback_sequence = [
                AdaptationAction.USE_ANALOGY,
                AdaptationAction.SIMPLIFY,
                AdaptationAction.SHOW_VISUAL,
                AdaptationAction.GIVE_EXAMPLE,
                AdaptationAction.ASK_EASIER_QUESTION,
                AdaptationAction.RETEACH,
            ]
        else:
            fallback_sequence = [
                AdaptationAction.CONTINUE,
                AdaptationAction.INCREASE_DIFFICULTY,
            ]

        for action in fallback_sequence:
            if action.value != last_action:
                return action

        return AdaptationAction.RETEACH


adaptation_agent = AdaptationAgent()
