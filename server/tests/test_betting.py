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


# ── 폴드 플레이어 포함 사이드팟 테스트 ──────────────────────────────────────

def test_compute_pots_folded_excluded_from_eligible():
    # carol이 200칩 넣고 폴드 → 팟에는 포함되지만 eligible 아님
    contribs = {"alice": 500, "bob": 500, "carol": 200}
    pots = compute_pots(contribs, folded_pids={"carol"})
    # 레이어 0~200: 200*3=600, eligible=[alice, bob] (carol 폴드)
    # 레이어 200~500: 300*2=600, eligible=[alice, bob]
    assert len(pots) == 2
    assert pots[0].amount == 600
    assert set(pots[0].eligible) == {"alice", "bob"}
    assert pots[1].amount == 600
    assert set(pots[1].eligible) == {"alice", "bob"}


def test_compute_pots_allin_and_fold():
    # A 올인 500, B 콜 1500, C 폴드 800 (멀티웨이 사이드팟)
    contribs = {"alice": 500, "bob": 1500, "carol": 800}
    pots = compute_pots(contribs, folded_pids={"carol"})
    # 레이어 0~500: 500*3=1500, eligible=[alice, bob]
    # 레이어 500~800: 300*2=600, eligible=[bob] (alice 올인 초과, carol 폴드)
    # 레이어 800~1500: 700*1=700, eligible=[bob]
    total = sum(p.amount for p in pots)
    assert total == 500 + 1500 + 800   # 전체 칩 합산
    assert "carol" not in pots[0].eligible
    assert "alice" in pots[0].eligible and "bob" in pots[0].eligible
    # bob만 접근 가능한 사이드팟 존재
    bob_only = [p for p in pots if p.eligible == ["bob"]]
    assert len(bob_only) >= 1


def test_compute_pots_all_folded_edge():
    # 극단적 케이스: 기여자 전원 폴드 → eligible 비어있으면 전체 허용
    contribs = {"alice": 100, "bob": 100}
    pots = compute_pots(contribs, folded_pids={"alice", "bob"})
    assert len(pots) == 1
    assert pots[0].amount == 200
    assert set(pots[0].eligible) == {"alice", "bob"}  # fallback


# ── 헤즈업 SB/BB 순서 테스트 ───────────────────────────────────────────────

def test_headsup_sb_is_button():
    """헤즈업에서 SB = 버튼(딜러). 프리플랍 SB가 먼저 행동."""
    from game.game_state import GameState
    g = GameState("test", small_blind=50, big_blind=100, starting_chips=1000)
    g.add_player("alice", "Alice")
    g.add_player("bob",   "Bob")
    g.seats["alice"].is_ready = True
    g.seats["bob"].is_ready   = True

    events = g.start_hand()

    # dealer_index=0 → dealer=alice (sb=alice, bb=bob)
    # 또는 dealer_index=1 → dealer=bob (sb=bob, bb=alice)
    # 어느 경우든 SB == dealer_id
    assert g.sb_id == g.dealer_id

    # action_required 는 SB(버튼) 에게 먼저 와야 함
    ar = next(e for e in events if e["event"] == "action_required")
    assert ar["player_id"] == g.sb_id


def test_headsup_postflop_bb_acts_first():
    """헤즈업 포스트플랍: BB(비버튼)가 먼저 행동."""
    from game.game_state import GameState
    g = GameState("test", small_blind=50, big_blind=100, starting_chips=5000)
    g.add_player("alice", "Alice")
    g.add_player("bob",   "Bob")
    g.seats["alice"].is_ready = True
    g.seats["bob"].is_ready   = True
    g.start_hand()

    sb_id = g.sb_id
    bb_id = g.bb_id

    # 프리플랍: SB 콜 → BB 체크 → 플랍으로
    g.apply_action(sb_id, "call")
    events = g.apply_action(bb_id, "check")

    ar = next((e for e in events if e["event"] == "action_required"), None)
    if ar:
        # 포스트플랍에서는 BB(비버튼)가 먼저
        assert ar["player_id"] == bb_id


# ── 3인 게임 UTG 순서 테스트 ────────────────────────────────────────────────

def test_three_player_utg_acts_first():
    """3인: UTG(BB 왼쪽)가 프리플랍 첫 행동."""
    from game.game_state import GameState
    g = GameState("test", small_blind=50, big_blind=100, starting_chips=5000)
    g.add_player("alice", "Alice")
    g.add_player("bob",   "Bob")
    g.add_player("carol", "Carol")
    for pid in ["alice", "bob", "carol"]:
        g.seats[pid].is_ready = True

    events = g.start_hand()

    active = [pid for pid in g.seat_order if g.seats[pid].stack > 0]
    n = len(active)
    expected_utg = active[(g.dealer_index + 3) % n]

    ar = next(e for e in events if e["event"] == "action_required")
    assert ar["player_id"] == expected_utg


def test_fold_does_not_shift_index():
    """폴드 후 current_player_index 가 틀어지지 않아야 함 (BUG-Fix 검증)."""
    from game.game_state import GameState
    g = GameState("test", small_blind=50, big_blind=100, starting_chips=5000)
    g.add_player("alice", "Alice")
    g.add_player("bob",   "Bob")
    g.add_player("carol", "Carol")
    for pid in ["alice", "bob", "carol"]:
        g.seats[pid].is_ready = True

    g.start_hand()

    # UTG(첫 행동자) 확인
    active = g._active_players()
    utg = active[g.current_player_index % len(active)]

    # UTG 폴드
    events = g.apply_action(utg, "fold")

    # 다음 action_required 는 UTG+1 이어야 함 (NOT_YOUR_TURN 없어야 함)
    errors = [e for e in events if e.get("event") == "error"]
    assert errors == [], f"Unexpected errors: {errors}"
    ar = next((e for e in events if e["event"] == "action_required"), None)
    assert ar is not None
    # 폴드한 UTG에게 다시 요청하지 않음
    assert ar["player_id"] != utg
