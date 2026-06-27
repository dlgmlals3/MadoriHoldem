from __future__ import annotations
from itertools import combinations
from enum import IntEnum
from .card import Card


class HandRank(IntEnum):
    HIGH_CARD = 1
    ONE_PAIR = 2
    TWO_PAIR = 3
    TRIPS = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    QUADS = 8
    STRAIGHT_FLUSH = 9
    ROYAL_FLUSH = 10


HAND_RANK_NAMES = {
    HandRank.HIGH_CARD: "하이카드",
    HandRank.ONE_PAIR: "원페어",
    HandRank.TWO_PAIR: "투페어",
    HandRank.TRIPS: "트리플",
    HandRank.STRAIGHT: "스트레이트",
    HandRank.FLUSH: "플러시",
    HandRank.FULL_HOUSE: "풀하우스",
    HandRank.QUADS: "포 오브 어 카인드",
    HandRank.STRAIGHT_FLUSH: "스트레이트 플러시",
    HandRank.ROYAL_FLUSH: "로열 플러시",
}


def _ranks_sorted_desc(cards: tuple[Card, ...]) -> list[int]:
    return sorted((c.rank for c in cards), reverse=True)


def _is_flush(cards: tuple[Card, ...]) -> bool:
    return len({c.suit for c in cards}) == 1


def _is_straight(ranks: list[int]) -> bool:
    if ranks[0] - ranks[4] == 4 and len(set(ranks)) == 5:
        return True
    # A-2-3-4-5 wheel
    if ranks == [14, 5, 4, 3, 2]:
        return True
    return False


def _straight_high(ranks: list[int]) -> int:
    if ranks == [14, 5, 4, 3, 2]:
        return 5
    return ranks[0]


def _evaluate_five(cards: tuple[Card, ...]) -> tuple[int, ...]:
    """Return a comparable tuple: (HandRank, tiebreak values...)."""
    ranks = _ranks_sorted_desc(cards)
    flush = _is_flush(cards)
    straight = _is_straight(ranks)

    if flush and straight:
        high = _straight_high(ranks)
        if high == 14:
            return (HandRank.ROYAL_FLUSH,)
        return (HandRank.STRAIGHT_FLUSH, high)

    from collections import Counter
    count = Counter(ranks)
    freq = sorted(count.items(), key=lambda x: (x[1], x[0]), reverse=True)
    groups = [r for r, _ in freq]
    counts = [c for _, c in freq]

    if counts[0] == 4:
        return (HandRank.QUADS, groups[0], groups[1])
    if counts[0] == 3 and counts[1] == 2:
        return (HandRank.FULL_HOUSE, groups[0], groups[1])
    if flush:
        return (HandRank.FLUSH, *ranks)
    if straight:
        return (HandRank.STRAIGHT, _straight_high(ranks))
    if counts[0] == 3:
        return (HandRank.TRIPS, groups[0], groups[1], groups[2])
    if counts[0] == 2 and counts[1] == 2:
        pair_high, pair_low = sorted([groups[0], groups[1]], reverse=True)
        kicker = groups[2]
        return (HandRank.TWO_PAIR, pair_high, pair_low, kicker)
    if counts[0] == 2:
        return (HandRank.ONE_PAIR, groups[0], groups[1], groups[2], groups[3])
    return (HandRank.HIGH_CARD, *ranks)


def best_hand(hole: list[Card], community: list[Card]) -> tuple[tuple[int, ...], list[Card]]:
    """Return (score_tuple, best_5_cards) from 5-7 available cards."""
    all_cards = hole + community
    best_score: tuple[int, ...] = (-1,)
    best_five: list[Card] = []

    for combo in combinations(all_cards, 5):
        score = _evaluate_five(combo)
        if score > best_score:
            best_score = score
            best_five = list(combo)

    return best_score, best_five


def hand_rank_name(score: tuple[int, ...]) -> str:
    return HAND_RANK_NAMES.get(HandRank(score[0]), "알 수 없음")
