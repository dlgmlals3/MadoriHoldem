from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .card import Card, Deck
from .hand_evaluator import best_hand, hand_rank_name
from .betting import BettingRound, compute_pots

# 카드 딜 애니메이션 대기 시간 (main.py DEAL_DELAY 와 동기화)
_DEAL_DELAY = 3.5


class Phase(str, Enum):
    WAITING = "WAITING"
    STARTING = "STARTING"
    PRE_FLOP = "PRE_FLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"
    SHOWDOWN = "SHOWDOWN"
    HAND_END = "HAND_END"


@dataclass
class PlayerSeat:
    player_id: str
    nickname: str
    stack: int
    is_ready: bool = False
    hole_cards: list[Card] = field(default_factory=list)
    is_folded: bool = False
    is_all_in: bool = False
    current_bet: int = 0
    total_contribution: int = 0
    seat_index: int = 0

    def to_public_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "nickname": self.nickname,
            "stack": self.stack,
            "is_ready": self.is_ready,
            "is_folded": self.is_folded,
            "is_all_in": self.is_all_in,
            "current_bet": self.current_bet,
            "seat_index": self.seat_index,
            "hole_cards": ["??" for _ in self.hole_cards],  # hidden
        }

    def to_private_dict(self) -> dict:
        d = self.to_public_dict()
        d["hole_cards"] = [c.to_dict() for c in self.hole_cards]
        return d


class GameState:
    def __init__(
        self,
        room_id: str,
        small_blind: int = 10,
        big_blind: int = 20,
        starting_chips: int = 1000,
        turn_timeout: int = 30,
        max_players: int = 9,
    ) -> None:
        self.room_id = room_id
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.starting_chips = starting_chips
        self.turn_timeout = turn_timeout
        self.max_players = max_players

        self.phase: Phase = Phase.WAITING
        self.seats: dict[str, PlayerSeat] = {}          # player_id -> seat
        self.seat_order: list[str] = []                 # ordered by seat_index

        self.dealer_index: int = 0                      # index into seat_order
        self.community_cards: list[Card] = []
        self.deck: Optional[Deck] = None
        self.pot: int = 0
        self.current_player_index: int = 0
        self.betting_round: Optional[BettingRound] = None
        self.hand_history: list[dict] = []
        self.turn_deadline: Optional[float] = None
        self.dealer_id: Optional[str] = None
        self.sb_id: Optional[str] = None
        self.bb_id: Optional[str] = None

    # ------------------------------------------------------------------ seats
    def add_player(self, player_id: str, nickname: str) -> bool:
        if player_id in self.seats:
            return True
        if len(self.seats) >= self.max_players:
            return False
        seat_index = len(self.seat_order)
        seat = PlayerSeat(
            player_id=player_id,
            nickname=nickname,
            stack=self.starting_chips,
            seat_index=seat_index,
        )
        self.seats[player_id] = seat
        self.seat_order.append(player_id)
        return True

    def remove_player(self, player_id: str) -> None:
        if player_id not in self.seats:
            return
        self.seats.pop(player_id)
        self.seat_order.remove(player_id)

    def set_ready(self, player_id: str) -> None:
        if player_id in self.seats:
            self.seats[player_id].is_ready = True

    # ------------------------------------------------------------------ FSM
    def can_start(self) -> bool:
        ready = [p for p in self.seat_order
                 if self.seats[p].is_ready and self.seats[p].stack > 0]
        return len(ready) >= 2 and self.phase in (Phase.WAITING, Phase.HAND_END)

    def start_hand(self) -> list[dict]:
        """Transition WAITING/HAND_END → PRE_FLOP. Returns events to broadcast."""
        events: list[dict] = []

        # reset per-hand state
        self.community_cards = []
        self.deck = Deck()
        self.pot = 0

        active = [pid for pid in self.seat_order if self.seats[pid].stack > 0]
        if len(active) < 2:
            self.phase = Phase.WAITING
            return [{"event": "game_over", "reason": "not_enough_players"}]

        for pid in self.seat_order:
            if pid in self.seats:
                s = self.seats[pid]
                s.hole_cards = []
                s.is_folded = False
                s.is_all_in = False
                s.current_bet = 0
                s.total_contribution = 0

        # advance dealer button
        n = len(active)
        self.dealer_index = (self.dealer_index + 1) % n

        if n == 2:
            # 헤즈업: 버튼 = SB (프리플랍에서 먼저 행동), 상대 = BB
            sb_index  = self.dealer_index
            bb_index  = (self.dealer_index + 1) % n
            utg_index = self.dealer_index   # SB/버튼이 프리플랍 선행
        else:
            sb_index  = (self.dealer_index + 1) % n
            bb_index  = (self.dealer_index + 2) % n
            utg_index = (bb_index + 1) % n  # UTG = BB 왼쪽

        stacks = {pid: self.seats[pid].stack for pid in active}
        self.betting_round = BettingRound(players=active, stacks=stacks, min_bet=self.big_blind)

        # track dealer/blinds for public state
        self.dealer_id = active[self.dealer_index]
        sb_id = active[sb_index]
        bb_id = active[bb_index]
        self.sb_id = sb_id
        self.bb_id = bb_id
        sb_paid = self.betting_round.post_blind(sb_id, self.small_blind)
        bb_paid = self.betting_round.post_blind(bb_id, self.big_blind)
        self._sync_stacks_from_betting()

        # deal hole cards
        for pid in active:
            card1, card2 = self.deck.deal(), self.deck.deal()
            self.seats[pid].hole_cards = [card1, card2]
            events.append({
                "event": "deal_hole_cards",
                "target": pid,
                "cards": [card1.to_dict(), card2.to_dict()],
            })

        self.current_player_index = utg_index
        self.phase = Phase.PRE_FLOP
        # 딜 애니메이션(_DEAL_DELAY) 이 끝난 뒤부터 실제 카운트다운 시작
        self.turn_deadline = time.time() + _DEAL_DELAY + self.turn_timeout

        events.append({
            "event": "game_state",
            **self._public_state(active),
            "sb_paid": sb_paid,
            "bb_paid": bb_paid,
        })
        events.append(self._action_required_event(active))
        return events

    def apply_action(self, player_id: str, action: str, amount: int = 0) -> list[dict]:
        events: list[dict] = []
        active = self._active_players()

        if not active or self.betting_round is None:
            return [{"event": "error", "code": "NO_ACTIVE_HAND"}]

        current_pid = active[self.current_player_index % len(active)]
        if player_id != current_pid:
            return [{"event": "error", "code": "NOT_YOUR_TURN", "player_id": player_id}]

        prev_bet = self.betting_round.current_bets.get(player_id, 0)
        was_opening = self.betting_round.current_max_bet == 0
        self.betting_round.apply_action(player_id, action, amount)
        self._sync_stacks_from_betting()
        display_amount = self.betting_round.current_bets.get(player_id, 0) - prev_bet
        display_action = "bet" if action == "raise" and was_opening else action
        display_text = self._format_action_text(display_action, display_amount)

        events.append({"event": "player_acted", "player_id": player_id,
                       "action": action, "amount": amount,
                       "display_action": display_action,
                       "display_amount": display_amount,
                       "display_text": display_text})

        # check if only one player remains
        still_in = [p for p in active if p not in self.betting_round.folded]
        if len(still_in) == 1:
            winner = still_in[0]
            self.pot += sum(self.betting_round.current_bets.values())
            for pid in self.betting_round.players:
                self.seats[pid].total_contribution += self.betting_round.total_contributions.get(pid, 0)
            self.seats[winner].stack += self.pot
            self.pot = 0
            self.phase = Phase.HAND_END
            events.append({"event": "hand_end", "winner": winner, "reason": "all_folded"})
            return events

        if self.betting_round.is_round_over(active):
            # Show the closing action's chips before the next street collects them.
            events.append({"event": "game_state", **self._public_state(active)})
            events += self._advance_phase(active)
        else:
            self._next_player(active)
            # 매 액션 후 game_state 전송 → 베팅존/팟 즉시 갱신
            events.append({"event": "game_state", **self._public_state(active)})
            events.append(self._action_required_event(active))

        return events

    # ------------------------------------------------------------------ phase advance
    def _advance_phase(self, active: list[str], _reveal_sent: bool = False) -> list[dict]:
        events: list[dict] = []

        # collect bets into pot — uncalled bet은 즉시 반환
        street_contributions = {
            pid: self.betting_round.current_bets.get(pid, 0)
            for pid in self.betting_round.players
        }
        _, uncalled = compute_pots(street_contributions,
                                   folded_pids=self.betting_round.folded)
        for pid, amt in uncalled.items():
            if pid in self.seats:
                self.seats[pid].stack += amt
                street_contributions[pid] -= amt

        round_pot = sum(street_contributions.values())
        self.pot += round_pot
        for pid in self.betting_round.players:
            self.seats[pid].total_contribution += self.betting_round.total_contributions.get(pid, 0)

        still_in = [p for p in active if p not in self.betting_round.folded]
        non_allin = [p for p in still_in if p not in self.betting_round.all_in]

        # reset bets for next street — carry over folds so indices stay stable
        prev_folded = self.betting_round.folded.copy()
        new_stacks = {pid: self.seats[pid].stack for pid in active}
        self.betting_round = BettingRound(players=active, stacks=new_stacks, min_bet=self.big_blind)
        self.betting_round.all_in = {pid for pid in active if new_stacks[pid] == 0}
        self.betting_round.folded = prev_folded

        if self.phase == Phase.PRE_FLOP:
            self.deck.burn()
            for _ in range(3):
                self.community_cards.append(self.deck.deal())
            self.phase = Phase.FLOP

        elif self.phase == Phase.FLOP:
            self.deck.burn()
            self.community_cards.append(self.deck.deal())
            self.phase = Phase.TURN

        elif self.phase == Phase.TURN:
            self.deck.burn()
            self.community_cards.append(self.deck.deal())
            self.phase = Phase.RIVER

        elif self.phase == Phase.RIVER:
            events += self._do_showdown(active)
            return events

        # if only allin players remain, run out the board automatically
        if len(non_allin) <= 1:
            # 첫 진입 시에만 모든 홀카드 공개 이벤트 발송
            if not _reveal_sent:
                all_cards = [
                    {"player_id": pid,
                     "cards": [c.to_dict() for c in self.seats[pid].hole_cards]}
                    for pid in still_in
                ]
                events.append({"event": "reveal_all_cards", "players": all_cards})
            events.append({"event": "game_state", **self._public_state(active)})
            events += self._advance_phase(active, _reveal_sent=True)
            return events

        self.current_player_index = self._first_postflop_index(active, still_in)
        self.turn_deadline = time.time() + self.turn_timeout
        events.append({"event": "game_state", **self._public_state(active)})
        events.append(self._action_required_event(active))
        return events

    def _do_showdown(self, active: list[str]) -> list[dict]:
        still_in = [p for p in active
                    if p not in self.betting_round.folded]
        total_contributions = {
            pid: self.seats[pid].total_contribution for pid in active
        }
        # 레이어 방식 팟 계산 — uncalled bet은 해당 플레이어에게 즉시 반환
        pots, uncalled = compute_pots(total_contributions,
                                      folded_pids=self.betting_round.folded)
        for pid, amt in uncalled.items():
            if pid in self.seats:
                self.seats[pid].stack += amt

        results: list[dict] = []
        for pid in still_in:
            score, best5 = best_hand(self.seats[pid].hole_cards, self.community_cards)
            results.append({
                "player_id": pid,
                "nickname": self.seats[pid].nickname,
                "cards": [c.to_dict() for c in self.seats[pid].hole_cards],
                "best_hand": [c.to_dict() for c in best5],
                "hand_rank": hand_rank_name(score),
                "score": score,
                "won": 0,
            })

        # award each pot slice and build breakdown for client
        pot_labels = ["메인팟", "세컨팟", "서드팟", "팟4", "팟5"]
        pot_results: list[dict] = []
        board_displays = {str(c) for c in self.community_cards}

        def _is_playing_board(best5: list[dict]) -> bool:
            return all(c["display"] in board_displays for c in best5)

        for i, pot_slice in enumerate(pots):
            eligible_results = [r for r in results if r["player_id"] in pot_slice.eligible]
            if not eligible_results:
                continue
            best_score = max(eligible_results, key=lambda r: r["score"])["score"]
            winners = [r for r in eligible_results if r["score"] == best_score]
            share = pot_slice.amount // len(winners)
            remainder = pot_slice.amount % len(winners)
            for r in winners:
                r["won"] += share
            if remainder:
                winners[0]["won"] += remainder

            chop_label = None
            if len(winners) > 1:
                chop_label = (
                    "보드 찹"
                    if all(_is_playing_board(r["best_hand"]) for r in winners)
                    else "스플릿"
                )

            pot_results.append({
                "label": pot_labels[i] if i < len(pot_labels) else f"팟{i+1}",
                "amount": pot_slice.amount,
                "chop_label": chop_label,
                "winners": [
                    {"player_id": r["player_id"], "nickname": r["nickname"],
                     "hand_rank": r["hand_rank"], "share": share}
                    for r in winners
                ],
            })

        for r in results:
            self.seats[r["player_id"]].stack += r["won"]

        self.phase = Phase.HAND_END
        return [{"event": "showdown", "results": results,
                 "pot_results": pot_results,
                 "community_cards": [c.to_dict() for c in self.community_cards]}]

    # ------------------------------------------------------------------ helpers
    def _active_players(self) -> list[str]:
        # 인덱스 안정성을 위해 폴드된 플레이어를 제외하지 않음.
        # 파산(칩 0이고 올인 아님) 플레이어만 제외.
        return [pid for pid in self.seat_order
                if pid in self.seats
                and (self.seats[pid].stack > 0 or self.seats[pid].is_all_in)]

    def _sync_stacks_from_betting(self) -> None:
        if self.betting_round is None:
            return
        for pid, stack in self.betting_round.stacks.items():
            if pid in self.seats:
                self.seats[pid].stack = stack
                self.seats[pid].current_bet = self.betting_round.current_bets.get(pid, 0)
                if pid in self.betting_round.folded:
                    self.seats[pid].is_folded = True
                if pid in self.betting_round.all_in:
                    self.seats[pid].is_all_in = True

    def _next_player(self, active: list[str]) -> None:
        n = len(active)
        for i in range(1, n + 1):
            idx = (self.current_player_index + i) % n
            pid = active[idx]
            if pid not in self.betting_round.folded and pid not in self.betting_round.all_in:
                self.current_player_index = idx
                self.turn_deadline = time.time() + self.turn_timeout
                return

    def _first_postflop_index(self, active: list[str], still_in: list[str]) -> int:
        # first still-in player left of dealer
        n = len(active)
        for i in range(1, n + 1):
            idx = (self.dealer_index + i) % n
            pid = active[idx]
            if pid in still_in and pid not in self.betting_round.all_in:
                return idx
        return 0

    def _live_pots(self, active: list[str]) -> list[dict]:
        """스트리트 종료 후에만 메인팟/사이드팟 분리 표시.

        poker-ts의 PotManager.collectBetsForm과 동일한 원칙:
        스트리트 베팅이 진행 중(current_bets > 0)이면 단일 팟만 표시.
        스트리트가 끝나 current_bets가 모두 0이 된 시점(새 라운드 시작)에
        total_contribution 기준으로 메인팟/사이드팟을 분리 표시.
        """
        if not self.betting_round:
            return []

        # 현재 스트리트에서 베팅이 진행 중인지 확인
        street_has_bets = any(
            self.betting_round.current_bets.get(pid, 0) > 0 for pid in active
        )

        contributions: dict[str, int] = {
            pid: self.seats[pid].total_contribution
                 + self.betting_round.current_bets.get(pid, 0)
            for pid in active
        }
        total = sum(contributions.values())
        if total <= 0:
            return []

        # 베팅 진행 중 or 올인 없음 → 단일 팟 (사이드팟 미표시)
        if street_has_bets or not self.betting_round.all_in:
            return [{"label": "메인팟", "amount": total}]

        # 스트리트 종료 후 새 라운드 시작 (current_bets=0, all_in 확정)
        # → total_contribution 기준으로 메인팟/사이드팟 분리 표시
        pots, _ = compute_pots(contributions, folded_pids=self.betting_round.folded)
        labels = ["메인팟", "세컨팟", "서드팟", "팟4", "팟5"]
        return [
            {"label": labels[i] if i < len(labels) else f"팟{i+1}",
             "amount": s.amount}
            for i, s in enumerate(pots)
        ]

    def _public_state(self, active: list[str]) -> dict:
        return {
            "phase": self.phase.value,
            "pot": self.pot,
            "live_pots": self._live_pots(active),
            "community_cards": [c.to_dict() for c in self.community_cards],
            "current_player": active[self.current_player_index % len(active)] if active else None,
            "players": [self.seats[pid].to_public_dict() for pid in self.seat_order if pid in self.seats],
            "dealer": self.dealer_id,
            "sb": self.sb_id,
            "bb": self.bb_id,
        }

    def _format_action_text(self, action: str, amount: int) -> str:
        labels = {
            "fold": "FOLD",
            "check": "CHECK",
            "call": "CALL",
            "bet": "BET",
            "raise": "RAISE",
            "allin": "ALL-IN",
        }
        label = labels.get(action, action.upper())
        if action in ("fold", "check"):
            return label
        return f"{label} {amount:,}"

    def _action_required_event(self, active: list[str]) -> dict:
        pid = active[self.current_player_index % len(active)]
        va = self.betting_round.valid_actions(pid) if self.betting_round else {}
        return {
            "event": "action_required",
            "player_id": pid,
            "valid_actions": va,
            "deadline": self.turn_deadline,
        }

    def public_snapshot(self) -> dict:
        active = self._active_players()
        return {
            "room_id": self.room_id,
            "phase": self.phase.value,
            "pot": self.pot,
            "community_cards": [c.to_dict() for c in self.community_cards],
            "current_player": active[self.current_player_index % len(active)] if active else None,
            "players": [self.seats[pid].to_public_dict() for pid in self.seat_order if pid in self.seats],
        }
