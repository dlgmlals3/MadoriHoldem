from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class PotSlice:
    amount: int
    eligible: list[str]  # player_ids who can win this slice


def compute_pots(
    contributions: dict[str, int],
    folded_pids: set[str] | None = None,
) -> tuple[list[PotSlice], dict[str, int]]:
    """
    레이어 방식 팟 계산 (NL Hold'em 공식 규칙).

    contributions : {player_id: 핸드 전체 누적 기여 칩}
    folded_pids   : 폴드한 플레이어 — 칩은 팟에 포함, 수령 자격 없음

    반환값:
    - pots    : 쇼다운 배분 대상 PotSlice 리스트
    - uncalled : {player_id: 반환 칩} — 상대가 없어 경쟁 불가한 초과 베팅 (Uncalled Bet)

    알고리즘 (공식 문서 Section 20):
    1. totalContribution의 고유 양수 금액을 오름차순 정렬 → 레이어 기준점
    2. 각 레이어에서 해당 금액 이상 기여한 contributors 수만큼 layerAmount 계산
    3. contributors가 1명뿐이면 → Uncalled Bet (상대 없음, 반환 처리)
    4. contributors가 2명 이상 → 폴드 제외 eligible 플레이어로 PotSlice 생성
    5. 인접한 동일 eligible 슬라이스는 합산 (폴드 플레이어의 소액 기여로 인한 인위적 분리 방지)
    """
    if folded_pids is None:
        folded_pids = set()

    contrib = {pid: amt for pid, amt in contributions.items() if amt > 0}
    if not contrib:
        return [], {}

    levels = sorted(set(contrib.values()))

    raw_pots: list[PotSlice] = []
    uncalled: dict[str, int] = {}
    prev_level = 0

    for level in levels:
        # 이 레이어에 기여한 플레이어 (해당 금액 이상을 낸 모든 플레이어)
        contributors = [pid for pid, amt in contrib.items() if amt >= level]
        layer_amount = (level - prev_level) * len(contributors)

        if layer_amount <= 0:
            prev_level = level
            continue

        if len(contributors) == 1:
            # 초과 금액을 경쟁할 상대가 없음 → Uncalled Bet 반환
            pid = contributors[0]
            uncalled[pid] = uncalled.get(pid, 0) + layer_amount
        else:
            # 2명 이상 기여 → 유효 팟 생성 (폴드 플레이어는 수령 자격 제외)
            eligible = [pid for pid in contributors if pid not in folded_pids]
            if not eligible:
                eligible = list(contributors)  # 엣지 케이스: 기여자 전원 폴드
            raw_pots.append(PotSlice(amount=layer_amount, eligible=eligible))

        prev_level = level

    # 인접한 동일 eligible 슬라이스 합산
    # (폴드한 플레이어가 최저 all-in 보다 적게 기여한 경우 같은 eligible이 두 슬라이스로 분리됨)
    merged: list[PotSlice] = []
    for s in raw_pots:
        if merged and set(merged[-1].eligible) == set(s.eligible):
            prev = merged[-1]
            merged[-1] = PotSlice(amount=prev.amount + s.amount, eligible=prev.eligible)
        else:
            merged.append(s)

    return merged, uncalled


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
