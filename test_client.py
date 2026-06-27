"""
2인 홀덤 시뮬레이션 테스트 클라이언트

서버를 먼저 실행하세요:
  cd server && python -m uvicorn main:app --port 8000

실행:
  python test_client.py
"""
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import asyncio
import json
import websockets

SERVER = "ws://localhost:8000/ws"
ROOM   = "TESTROOM1"

RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
GRAY   = "\033[90m"


def card_str(card: dict) -> str:
    return card.get("display", "??")

def cards_str(cards: list) -> str:
    return " ".join(card_str(c) for c in cards) if cards else "-"

def log(tag: str, msg: str, color: str = RESET) -> None:
    print(f"{color}{BOLD}[{tag:^10}]{RESET} {msg}")

def separator(char: str = "-", n: int = 54) -> None:
    print(GRAY + char * n + RESET)


def print_game_state(ev: dict) -> None:
    phase   = ev.get("phase", "")
    pot     = ev.get("pot", 0)
    comm    = cards_str(ev.get("community_cards", []))
    cur     = ev.get("current_player", "")
    players = ev.get("players", [])

    separator("=")
    print(f"{CYAN}{BOLD}  페이즈: {phase}   팟: {pot}칩   차례: {cur}{RESET}")
    separator()
    print(f"  커뮤니티카드:  {BOLD}{comm}{RESET}")
    separator()
    for p in players:
        marks = ""
        if p.get("is_folded"): marks += f"{RED}[폴드]{RESET}"
        if p.get("is_all_in"): marks += f"{YELLOW}[올인]{RESET}"
        bet = f"  베팅:{YELLOW}{p['current_bet']}{RESET}" if p.get("current_bet") else ""
        print(f"  {BOLD}{p['nickname']:8s}{RESET}  스택:{GREEN}{p['stack']:4d}{RESET}{bet}  {marks}")
    separator("=")


# ───────────────────────────────────────── 플레이어 코루틴
async def run_player(
    name: str,
    player_id: str,
    is_host: bool,
    action_plan: list,        # [("raise", 60), ("call", 0), ...]
    partner_joined: asyncio.Event,
    game_over: asyncio.Event,
) -> None:
    uri = f"{SERVER}/{ROOM}/{player_id}"
    plan_idx = 0

    async with websockets.connect(uri) as ws:

        # ── 입장
        await ws.send(json.dumps({
            "event":         "join_room",
            "room_id":       ROOM,
            "player_id":     player_id,
            "nickname":      name,
            "starting_chips": 500,
            "small_blind":   10,
            "big_blind":     20,
        }))
        log(name, "서버에 접속했습니다", CYAN)

        async for raw in ws:
            ev    = json.loads(raw)
            event = ev.get("event")

            # ── 누군가 입장
            if event == "player_joined":
                nick = ev["nickname"]
                log(name, f"'{nick}' 입장")
                # host가 상대방 입장을 감지하면 게임 시작
                if is_host and nick != name:
                    partner_joined.set()
                    await asyncio.sleep(0.1)
                    log(name, "→ start_game 전송", YELLOW)
                    await ws.send(json.dumps({"event": "start_game"}))

            # ── 홀카드 수신
            elif event == "deal_hole_cards":
                cards = cards_str(ev.get("cards", []))
                log(name, f"내 홀카드: {BOLD}{cards}{RESET}", GREEN)

            # ── 게임 상태 (host만 출력해서 중복 방지)
            elif event == "game_state":
                if is_host:
                    print_game_state(ev)

            # ── 내 차례
            elif event == "action_required":
                target = ev.get("player_id")
                va     = ev.get("valid_actions", {})

                if target == player_id:
                    call_amt  = va.get("call_amount", 0)
                    min_raise = va.get("min_raise", 0)

                    opts = []
                    if va.get("check"):  opts.append("check")
                    if va.get("call"):   opts.append(f"call({call_amt})")
                    if va.get("raise"):  opts.append(f"raise(min {min_raise})")
                    if va.get("allin"):  opts.append(f"allin({va.get('allin_amount')})")
                    opts.append("fold")

                    print(f"\n  {BOLD}★ {name}의 차례{RESET}  가능: {' / '.join(opts)}")

                    # 플랜에서 액션 꺼내기
                    if plan_idx < len(action_plan):
                        action, amount = action_plan[plan_idx]
                        plan_idx += 1
                    else:
                        # 플랜 소진 → check 우선, 없으면 call
                        if va.get("check"):
                            action, amount = "check", 0
                        else:
                            action, amount = "call", 0

                    log(name, f"→ {YELLOW}{action}{RESET}" + (f" {amount}" if amount else ""))
                    await ws.send(json.dumps({
                        "event":  "player_action",
                        "action": action,
                        "amount": amount,
                    }))

            # ── 액션 결과 알림
            elif event == "player_acted":
                pid    = ev.get("player_id")
                action = ev.get("action")
                amt    = ev.get("amount", 0)
                who    = "Alice" if pid == "alice" else "Bob"
                amt_txt = f" +{amt}" if amt else ""
                log("ACTION", f"{who}: {BOLD}{action}{RESET}{amt_txt}", GRAY)

            # ── 쇼다운
            elif event == "showdown":
                separator("=")
                log("SHOWDOWN", "카드 공개!", YELLOW)
                comm = cards_str(ev.get("community_cards", []))
                print(f"  커뮤니티: {BOLD}{comm}{RESET}")
                separator()
                for r in ev.get("results", []):
                    pid   = r["player_id"]
                    nick  = "Alice" if pid == "alice" else "Bob"
                    hand  = cards_str(r.get("cards", []))
                    best  = cards_str(r.get("best_hand", []))
                    rank  = r.get("hand_rank", "")
                    won   = r.get("won", 0)
                    color = GREEN if won > 0 else GRAY
                    print(f"  {color}{BOLD}{nick:6s}{RESET}  홀카드:{hand}  최강패:{best}")
                    print(f"          족보:{BOLD}{rank}{RESET}  획득:{color}{BOLD}{won}칩{RESET}")
                separator("=")
                game_over.set()
                break

            # ── 폴드로 핸드 종료
            elif event == "hand_end":
                winner = ev.get("winner")
                reason = ev.get("reason")
                nick   = "Alice" if winner == "alice" else "Bob"
                separator("=")
                log("HAND END", f"{BOLD}{nick}{RESET} 승리 ({reason})", GREEN)
                separator("=")
                game_over.set()
                break

            # ── 에러
            elif event == "error":
                log("ERROR", f"{RED}{ev.get('code')}{RESET} {ev.get('detail','')}", RED)

            if game_over.is_set():
                break


# ───────────────────────────────────────── 메인
async def main() -> None:
    separator("=")
    print(f"  {BOLD}Texas Hold'em 2인 시뮬레이션{RESET}  룸: {ROOM}")
    separator("=")

    partner_joined = asyncio.Event()
    game_over      = asyncio.Event()

    # 액션 플랜 설정
    # Alice: 프리플랍 레이즈 60 → 이후 자동(check/call)
    alice_plan = [("raise", 60)]

    # Bob: 프리플랍 call → 이후 자동(check/call)
    bob_plan   = [("call", 0)]

    alice_task = asyncio.create_task(run_player(
        name="Alice", player_id="alice", is_host=True,
        action_plan=alice_plan,
        partner_joined=partner_joined,
        game_over=game_over,
    ))

    # Bob은 Alice가 접속한 뒤 잠깐 후에 입장
    await asyncio.sleep(0.4)

    bob_task = asyncio.create_task(run_player(
        name="Bob", player_id="bob", is_host=False,
        action_plan=bob_plan,
        partner_joined=partner_joined,
        game_over=game_over,
    ))

    try:
        await asyncio.wait_for(
            asyncio.gather(alice_task, bob_task),
            timeout=20,
        )
    except asyncio.TimeoutError:
        log("TIMEOUT", "20초 초과 — 강제 종료", RED)
        alice_task.cancel()
        bob_task.cancel()

    separator("=")
    print(f"  {BOLD}시뮬레이션 종료{RESET}")
    separator("=")


if __name__ == "__main__":
    asyncio.run(main())
