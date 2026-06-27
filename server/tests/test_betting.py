import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from game.betting import BettingRound, compute_pots


def make_round(players=None, stacks=None):
    if players is None:
        players = ["alice", "bob", "carol"]
    if stacks is None:
        stacks = {p: 1000 for p in players}
    return BettingRound(players=players, stacks=dict(stacks))


def test_post_blind():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    assert br.current_max_bet == 20
    assert br.stacks["alice"] == 990
    assert br.stacks["bob"] == 980


def test_call():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    br.apply_action("carol", "call")
    assert br.current_bets["carol"] == 20
    assert br.stacks["carol"] == 980


def test_raise():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    br.apply_action("carol", "raise", 20)  # raise by 20 on top of call
    assert br.current_bets["carol"] == 40
    assert br.current_max_bet == 40


def test_fold():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    br.apply_action("carol", "fold")
    assert "carol" in br.folded


def test_allin():
    br = make_round(stacks={"alice": 1000, "bob": 15, "carol": 1000})
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)  # bob only has 15, so goes all-in for 15
    assert "bob" in br.all_in
    assert br.stacks["bob"] == 0


def test_check():
    br = make_round()
    # no bets yet — everyone can check
    br.apply_action("alice", "check")
    assert br.action_count == 1


def test_check_invalid_when_bet_exists():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    with pytest.raises(ValueError):
        br.apply_action("carol", "check")


def test_round_over_after_all_call():
    br = make_round()
    br.post_blind("alice", 10)
    br.post_blind("bob", 20)
    br.apply_action("carol", "call")
    br.apply_action("alice", "call")
    # BB (bob) still has the option to raise — round is NOT over yet
    players_in = ["alice", "bob", "carol"]
    assert not br.is_round_over(players_in)
    # Bob checks (takes the option without raising) — now round IS over
    br.apply_action("bob", "check")
    assert br.is_round_over(players_in)


def test_compute_pots_no_allin():
    contribs = {"alice": 100, "bob": 100, "carol": 100}
    pots = compute_pots(contribs)
    assert len(pots) == 1
    assert pots[0].amount == 300
    assert set(pots[0].eligible) == {"alice", "bob", "carol"}


def test_compute_pots_with_allin():
    # bob all-in for 50, others put in 100
    contribs = {"alice": 100, "bob": 50, "carol": 100}
    pots = compute_pots(contribs)
    assert len(pots) == 2
    main = pots[0]
    side = pots[1]
    assert main.amount == 150        # 50 * 3
    assert set(main.eligible) == {"alice", "bob", "carol"}
    assert side.amount == 100        # 50 * 2 remaining
    assert set(side.eligible) == {"alice", "carol"}
