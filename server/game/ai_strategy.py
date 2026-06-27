"""
AI 전략 모듈

전략 추가 방법:
  새 함수를 작성하고 decide_action()의 strategy 선택 부분에서 호출하세요.
  각 전략 함수는 (va: dict) -> tuple[str, int] 시그니처를 따릅니다.
"""
from __future__ import annotations
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .game_state import GameState


def decide_action(game_state: 'GameState', player_id: str) -> tuple[str, int]:
    if game_state.betting_round is None:
        return "fold", 0
    va = game_state.betting_round.valid_actions(player_id)
    return random_strategy(va)


def random_strategy(va: dict) -> tuple[str, int]:
    """랜덤 전략 — 합법적인 액션 중 확률 기반 선택."""
    roll = random.random()

    if va.get("check"):
        if not va.get("raise") or roll < 0.65:
            return "check", 0
        return _random_raise(va)

    if va.get("call"):
        call_amt  = va.get("call_amount", 0)
        allin_amt = va.get("allin_amount", 0)
        is_allin_call = allin_amt > 0 and call_amt >= allin_amt
        if is_allin_call:
            return ("call", 0) if roll < 0.45 else ("fold", 0)
        if roll < 0.55:
            return "call", 0
        if roll < 0.75 and va.get("raise"):
            return _random_raise(va)
        return "fold", 0

    return "fold", 0


def _random_raise(va: dict) -> tuple[str, int]:
    min_r  = va.get("min_raise", 100)
    allin  = va.get("allin_amount", min_r)
    max_r  = min(allin, min_r * 4)
    steps  = max(0, (max_r - min_r) // 100)
    amount = min_r + random.randint(0, steps) * 100
    return "raise", amount
