# 구현 계획 — poker-ts 분석 기반 버그/개선 정리

---

## 1. poker-ts 에서 배울 핵심 설계

| 항목 | poker-ts | 우리 현재 구현 | 문제 여부 |
|------|----------|--------------|---------|
| 사이드팟 | `PotManager` + `Pot` 레이어 분리, 폴드 기여금 별도 집계 | `compute_pots()` 단일 함수 | **폴드한 플레이어가 eligible에 포함됨 → 버그** |
| 라운드 종료 | `_lastAggressiveActor` 추적 — 그 플레이어가 다시 차례 오면 종료 | `acted` 집합 + `bets_even` | 논리는 동일, 구현 OK |
| 헤즈업 SB/BB | 버튼 = SB, 상대 = BB; 프리플랍에서 SB(버튼)가 먼저 행동 | SB = 딜러 왼쪽, BB = 그 다음 → 헤즈업 시 역전 | **헤즈업 SB/BB 배치 버그** |
| 포스트플랍 선행자 | 버튼 왼쪽 첫 번째 생존자 | `_first_postflop_index` | 전반적으로 OK, 헤즈업 예외 처리 누락 |
| 폴드 기여금 팟 배분 | 폴드된 베팅을 eligible 플레이어 팟에 비례 분배 | eligible 계산에 폴드 플레이어 포함 | **버그** |
| 액션 인덱스 안정성 | player 리스트를 고정, skip으로 처리 | `_active_players()`가 폴드 시 줄어듦 | **이미 수정 완료 (06/28)** |

---

## 2. 확인된 버그 목록 (우선순위 순)

### 🔴 P0 — 즉시 수정 필요

#### BUG-1: 사이드팟 eligible에 폴드 플레이어 포함
**위치**: `server/game/betting.py` — `compute_pots()`

**현상**: A 올인(500), B 콜(1000), C 폴드(200) 상황에서
메인팟 eligible = [A, B, C] 가 돼버림 → C(폴드)가 팟 수령 가능

**수정 방향**:
```python
def compute_pots(contributions: dict[str, int],
                 folded_pids: set[str] | None = None) -> list[PotSlice]:
    if folded_pids is None:
        folded_pids = set()
    ...
    while remaining:
        min_contrib = min(remaining.values())
        pot_amount = min_contrib * len(remaining)
        # 폴드한 플레이어는 칩을 넣었어도 eligible 제외
        eligible = [pid for pid in remaining if pid not in folded_pids]
        pots.append(PotSlice(amount=pot_amount, eligible=eligible))
        ...
```

`_do_showdown()`에서 호출 시:
```python
pots = compute_pots(total_contributions,
                    folded_pids=self.betting_round.folded)
```

---

#### BUG-2: 헤즈업(2인) SB/BB 배치 오류
**위치**: `server/game/game_state.py` — `start_hand()`

**현상**: 2인 게임에서 딜러=A 라면
- 현재: SB=B, BB=A (역전)
- 정상: SB=A(딜러=버튼), BB=B

**표준 헤즈업 규칙**:
- 버튼 = SB (먼저 블라인드 포스팅)
- 상대 = BB
- 프리플랍: SB(버튼)가 먼저 행동 (UTG = SB 위치)
- 포스트플랍: BB(비버튼)가 먼저 행동

**수정 방향**:
```python
n = len(active)
if n == 2:
    sb_index  = self.dealer_index          # 버튼 = SB
    bb_index  = (self.dealer_index + 1) % n
    utg_index = self.dealer_index          # 프리플랍: SB 먼저
else:
    sb_index  = (self.dealer_index + 1) % n
    bb_index  = (self.dealer_index + 2) % n
    utg_index = (bb_index + 1) % n
```

---

#### BUG-3: `total_contribution` 누적 오류 (사이드팟 계산 기반 데이터)
**위치**: `server/game/game_state.py` — `_advance_phase()` / `apply_action()`

**현상**: `total_contribution`이 `_advance_phase()`에서 중복 누적될 가능성 있음
`betting_round.total_contributions`와 `seats[pid].total_contribution`이 동기화 시점 불일치

**수정 방향**: 스트릿 종료 시 한 번만 정산, `_do_showdown`에서만 `total_contribution` 읽도록 단일화

---

### 🟡 P1 — 다음 버전에서 수정

#### BUG-4: 포스트플랍 혼자 남은 경우 auto-advance 누락
**현상**: 상대가 전부 올인/폴드 → 1명만 행동 가능 → 무의미한 action_required 발송

**수정 방향**: `_advance_phase` 진입 직전에 `non_allin` 수 체크하여 자동 진행

---

#### BUG-5: 팟 표시에 현재 스트릿 베팅 미포함
**현상**: 팟 금액이 이전 스트릿 합산만 표시. 현재 베팅 중인 칩은 bet-zone에는 보이지만 팟 숫자에는 없음

**수정 방향**: 클라이언트 `pot-text`에 `pot + sum(current_bets)` 표시

---

### 🟢 P2 — 개선/추가

#### FEAT-1: 쇼다운 시 폴드한 플레이어 카드 숨김 처리 보장
#### FEAT-2: 리버에서 베팅 없이 check-check 시 showdown 자동 진행
#### FEAT-3: 멀티웨이(3인+) 사이드팟 테스트 케이스 추가

---

## 3. 베팅 라운드 순서 — 확정 규칙

### 프리플랍

```
[3인 이상]
  포스팅 순서: SB → BB
  행동 순서:  UTG(BB 왼쪽) → UTG+1 → ... → 딜러 → SB → BB
  BB 옵션: 레이즈 없이 콜만 있으면 BB는 체크 또는 레이즈 가능

[헤즈업 2인]
  포스팅 순서: SB(버튼) → BB
  행동 순서:  SB(버튼) → BB
  BB 옵션: 동일 적용
```

### 포스트플랍 (플랍/턴/리버)

```
[3인 이상]
  행동 순서: 딜러 왼쪽 첫 생존자 → ... → 딜러

[헤즈업 2인]
  행동 순서: BB(비버튼) → SB(버튼)
```

### 라운드 종료 조건

```
활성 플레이어 = (폴드 아님) AND (올인 아님) 인 플레이어

종료 ← 아래 두 조건 동시 충족:
  1. 모든 활성 플레이어가 자발적으로 1번 이상 행동 (acted 집합)
  2. 모든 활성 플레이어 베팅 금액 동일

레이즈 발생 시: acted 집합 = {레이저} 로 리셋 → 나머지 플레이어 재행동 필요
```

---

## 4. 올바른 사이드팟 계산 알고리즘

poker-ts 의 레이어드 접근법을 Python 으로 표현:

```
입력: contributions = {pid: total_chips_put_in}, folded = {pid, ...}

layers = contributions 값들을 오름차순 정렬 후 dedupe
prev = 0
pots = []

for level in layers:
    pot_amount = 0
    eligible = []
    for pid, contrib in contributions.items():
        take = min(contrib, level) - min(contrib, prev)
        pot_amount += take
        if pid not in folded and contrib >= level:
            eligible.append(pid)
    if pot_amount > 0:
        pots.append(PotSlice(pot_amount, eligible))
    prev = level

return pots
```

**예시**: A 올인 500, B 올인 1500, C 콜 1500, D 폴드 800

| 레이어 | 금액 | eligible |
|--------|------|----------|
| 0~500 | 500×4=2000 | [A, B, C] (D 폴드 제외) |
| 500~800 | 300×3=900 | [B, C] (A 올인 초과, D 폴드) |
| 800~1500 | 700×2=1400 | [B, C] |

D의 기여 800은 레이어 계산에 들어가지만 eligible 에서 제외 → 팟에 더해지되 수령 불가

---

## 5. 구현 순서 (Sprint Plan)

### Sprint 1 — 핵심 버그 수정 (즉시)
- [ ] BUG-1: `compute_pots()` folded_pids 파라미터 추가
- [ ] BUG-2: `start_hand()` 헤즈업 SB/BB 분기 처리
- [ ] BUG-3: `total_contribution` 정산 로직 정리

### Sprint 2 — 안정화
- [ ] BUG-4: 포스트플랍 단독 액션 auto-advance
- [ ] BUG-5: 클라이언트 팟 표시에 현재 스트릿 베팅 합산
- [ ] FEAT-3: 멀티웨이 사이드팟 단위 테스트 추가 (`test_betting.py`)

### Sprint 3 — 완성도
- [ ] FEAT-1: 쇼다운 카드 공개 로직 강화
- [ ] FEAT-2: 체크-체크 리버 자동 쇼다운 검증
- [ ] 전체 E2E 테스트 (test_client.py) 로 3인 시나리오 커버

---

## 6. 테스트 체크리스트

```
□ 헤즈업: SB=버튼, BB=상대, 프리플랍 SB 먼저
□ 3인: UTG → SB → BB 순, BB 옵션 동작
□ 올인 사이드팟: 금액 다른 올인 시 팟 분리 확인
□ 폴드 기여금: 폴드 플레이어 칩이 메인팟에 반영되되 수령 불가
□ 스트릿 전환: 폴드 carry-over 로 인덱스 안정 확인
□ 타임아웃: 30초 후 자동 폴드, 다음 플레이어로 정상 이동
```
