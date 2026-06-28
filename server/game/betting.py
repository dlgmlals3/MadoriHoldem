from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PotSlice:
    amount: int
    eligible: list[str]  # player_ids who can win this slice


def compute_pots(
    contributions: dict[str, int],
    folded_pids: set[str] | None = None,
) -> list[PotSlice]:
    """
    Build main pot + side pots from per-player chip contributions.
    contributions : {player_id: total_chips_put_in_this_hand}
    folded_pids   : players who folded — contribute chips but cannot win any pot
    """
    if folded_pids is None:
        folded_pids = set()

    if not contributions:
        return []

    active = {pid: amt for pid, amt in contributions.items() if amt > 0}
    if not active:
        return []

    pots: list[PotSlice] = []
    remaining = dict(active)

    while remaining:
        min_contrib = min(remaining.values())
        pot_amount  = min_contrib * len(remaining)

        # 폴드한 플레이어는 칩을 넣었어도 수령 자격 없음
        eligible = [pid for pid in remaining if pid not in folded_pids]
        # 만약 살아있는 플레이어가 없으면(극단적 엣지케이스) 전체 허용
        if not eligible:
            eligible = list(remaining.keys())

        pots.append(PotSlice(amount=pot_amount, eligible=eligible))

        remaining = {pid: amt - min_contrib for pid, amt in remaining.items()}
        remaining = {pid: amt for pid, amt in remaining.items() if amt > 0}

    # 폴드된 플레이어의 소액 기여가 동일 eligible 슬라이스를 두 개로 쪼갤 수 있음.
    # eligible set이 같은 연속 슬라이스는 하나의 팟으로 합산.
    merged: list[PotSlice] = []
    for s in pots:
        if merged and set(merged[-1].eligible) == set(s.eligible):
            prev = merged[-1]
            merged[-1] = PotSlice(amount=prev.amount + s.amount, eligible=prev.eligible)
        else:
            merged.append(s)
    return merged


@dataclass
class BettingRound:
    players: list[str]                  # ordered active player ids
    stacks: dict[str, int]              # current chip stacks
    min_bet: int = 0                    # 최소 베팅 단위 (= big blind); 레이즈 최솟값의 하한
    current_bets: dict[str, int] = field(default_factory=dict)
    total_contributions: dict[str, int] = field(default_factory=dict)
    current_max_bet: int = 0
    last_raise_amount: int = 0
    action_count: int = 0
    folded: set[str] = field(default_factory=set)
    all_in: set[str] = field(default_factory=set)
    # Players who have made a voluntary action this street (excludes blind posts).
    # Resets to {aggressor} on every raise so opponents must re-act.
    acted: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for pid in self.players:
            self.current_bets.setdefault(pid, 0)
            self.total_contributions.setdefault(pid, 0)

    def post_blind(self, player_id: str, amount: int) -> int:
        actual = min(amount, self.stacks[player_id])
        self.stacks[player_id] -= actual
        self.current_bets[player_id] += actual
        self.total_contributions[player_id] += actual
        if actual > self.current_max_bet:
            self.last_raise_amount = actual - self.current_max_bet
            self.current_max_bet = actual
        if self.stacks[player_id] == 0:
            self.all_in.add(player_id)
        return actual

    def valid_actions(self, player_id: str) -> dict:
        stack = self.stacks[player_id]
        my_bet = self.current_bets[player_id]
        call_amount = min(self.current_max_bet - my_bet, stack)
        # 최소 레이즈 = max(직전 레이즈 크기, BB 금액) — 최소 1칩 보장
        min_raise = max(self.last_raise_amount, self.min_bet, 1)
        can_check = self.current_max_bet == my_bet

        # Can't raise if all other active (non-folded) players are already all-in
        others_active = [p for p in self.players if p != player_id and p not in self.folded]
        all_others_allin = bool(others_active) and all(p in self.all_in for p in others_active)

        can_raise = (not all_others_allin) and stack > call_amount and (stack - call_amount) >= min_raise

        return {
            "fold": True,
            "check": can_check,
            "call": not can_check,
            "call_amount": call_amount,
            "raise": can_raise,
            "min_raise": min_raise if can_raise else 0,
            "allin": stack > 0,
            "allin_amount": stack,
            "is_opening": len(self.acted) == 0,
        }

    def apply_action(self, player_id: str, action: str, amount: int = 0) -> None:
        stack = self.stacks[player_id]
        my_bet = self.current_bets[player_id]
        call_needed = self.current_max_bet - my_bet

        if action == "fold":
            self.folded.add(player_id)
            self.acted.add(player_id)
            self.action_count += 1

        elif action == "check":
            if call_needed != 0:
                raise ValueError("Cannot check when there is a bet to call")
            self.acted.add(player_id)
            self.action_count += 1

        elif action == "call":
            actual = min(call_needed, stack)
            self.stacks[player_id] -= actual
            self.current_bets[player_id] += actual
            self.total_contributions[player_id] += actual
            if self.stacks[player_id] == 0:
                self.all_in.add(player_id)
            self.acted.add(player_id)
            self.action_count += 1

        elif action == "raise":
            total_put_in = call_needed + amount
            actual = min(total_put_in, stack)
            self.stacks[player_id] -= actual
            self.current_bets[player_id] += actual
            self.total_contributions[player_id] += actual
            if self.stacks[player_id] == 0:
                self.all_in.add(player_id)
            new_max = self.current_bets[player_id]
            self.last_raise_amount = new_max - self.current_max_bet
            self.current_max_bet = new_max
            # Raise resets acted — everyone else must act again
            self.acted = {player_id}
            self.action_count += 1

        elif action == "allin":
            actual = stack
            self.stacks[player_id] -= actual
            self.current_bets[player_id] += actual
            self.total_contributions[player_id] += actual
            self.all_in.add(player_id)
            new_max = self.current_bets[player_id]
            if new_max > self.current_max_bet:
                self.last_raise_amount = new_max - self.current_max_bet
                self.current_max_bet = new_max
                # All-in as a raise — everyone else must act again
                self.acted = {player_id}
            else:
                self.acted.add(player_id)
            self.action_count += 1

    def is_round_over(self, players_in_hand: list[str]) -> bool:
        active = [p for p in players_in_hand if p not in self.folded and p not in self.all_in]
        if len(active) == 0:
            return True
        # Every active player must have made a voluntary action (covers BB option
        # and all-in response) AND all bets must be equal.
        all_acted = all(p in self.acted for p in active)
        bets_even = all(self.current_bets[p] == self.current_max_bet for p in active)
        return all_acted and bets_even
