import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from game.card import Card, Suit
from game.hand_evaluator import best_hand, HandRank, hand_rank_name


def c(rank: int, suit: str) -> Card:
    s = {"s": Suit.SPADE, "h": Suit.HEART, "d": Suit.DIAMOND, "c": Suit.CLUB}[suit]
    return Card(rank, s)


def test_royal_flush():
    hole = [c(14, "s"), c(13, "s")]
    comm = [c(12, "s"), c(11, "s"), c(10, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.ROYAL_FLUSH


def test_straight_flush():
    hole = [c(9, "h"), c(8, "h")]
    comm = [c(7, "h"), c(6, "h"), c(5, "h"), c(2, "s"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.STRAIGHT_FLUSH
    assert score[1] == 9


def test_quads():
    hole = [c(7, "s"), c(7, "h")]
    comm = [c(7, "d"), c(7, "c"), c(14, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.QUADS


def test_full_house():
    hole = [c(3, "s"), c(3, "h")]
    comm = [c(3, "d"), c(6, "c"), c(6, "s"), c(2, "h"), c(9, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.FULL_HOUSE


def test_flush():
    hole = [c(14, "h"), c(9, "h")]
    comm = [c(5, "h"), c(3, "h"), c(2, "h"), c(7, "s"), c(8, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.FLUSH


def test_straight():
    hole = [c(9, "s"), c(8, "h")]
    comm = [c(7, "d"), c(6, "c"), c(5, "s"), c(2, "h"), c(14, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.STRAIGHT


def test_wheel_straight():
    hole = [c(14, "s"), c(2, "h")]
    comm = [c(3, "d"), c(4, "c"), c(5, "s"), c(9, "h"), c(10, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.STRAIGHT
    assert score[1] == 5


def test_trips():
    hole = [c(5, "s"), c(5, "h")]
    comm = [c(5, "d"), c(9, "c"), c(14, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.TRIPS


def test_two_pair():
    hole = [c(9, "s"), c(9, "h")]
    comm = [c(6, "d"), c(6, "c"), c(14, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.TWO_PAIR


def test_one_pair():
    hole = [c(14, "s"), c(14, "h")]
    comm = [c(7, "d"), c(6, "c"), c(5, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.ONE_PAIR


def test_high_card():
    hole = [c(14, "s"), c(9, "h")]
    comm = [c(7, "d"), c(6, "c"), c(5, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert score[0] == HandRank.HIGH_CARD


def test_hand_rank_ordering():
    """Higher hand rank beats lower hand rank."""
    hole_flush = [c(14, "h"), c(9, "h")]
    comm_flush = [c(5, "h"), c(3, "h"), c(2, "h"), c(7, "s"), c(8, "d")]
    hole_str = [c(9, "s"), c(8, "h")]
    comm_str = [c(7, "d"), c(6, "c"), c(5, "s"), c(2, "h"), c(14, "d")]
    flush_score, _ = best_hand(hole_flush, comm_flush)
    str_score, _ = best_hand(hole_str, comm_str)
    assert flush_score > str_score


def test_hand_rank_name():
    hole = [c(14, "s"), c(13, "s")]
    comm = [c(12, "s"), c(11, "s"), c(10, "s"), c(2, "h"), c(3, "d")]
    score, _ = best_hand(hole, comm)
    assert hand_rank_name(score) == "로열 플러시"
