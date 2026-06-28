"""
대화형 홀덤 클라이언트

사용법:
  python interactive_client.py <player_id> <nickname> [room_id]

예:
  터미널1: python interactive_client.py alice Alice ROOM1
  터미널2: python interactive_client.py bob   Bob   ROOM1

서버 먼저 실행:
  cd server && python -m uvicorn main:app --port 8000
"""
from __future__ import annotations
import asyncio
import json
import sys
import io

import websockets

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

SERVER = "ws://localhost:8000/ws"

RESET   = "\033[0m"
BOLD    = "\033[1m"
CYAN    = "\033[96m"
GREEN   = "\033[92m"
YELLOW  = "\033[93m"
RED     = "\033[91m"
GRAY    = "\033[90m"
MAGENTA = "\033[95m"


def card_str(c: dict) -> str:
    return c.get("display", "??")

def cards_str(cards: list) -> str:
    return " ".join(card_str(c) for c in cards) if cards else "-"

def sep(char: str = "─", n: int = 58) -> None:
    print(GRAY + char * n + RESET)

def log(tag: str, msg: str, color: str = RESET) -> None:
    print(f"{color}[{tag}]{RESET} {msg}")


def print_game_state(ev: dict, my_id: str) -> None:
    phase   = ev.get("phase", "")
    pot     = ev.get("pot", 0)
    comm    = cards_str(ev.get("community_cards", []))
    cur     = ev.get("current_player", "")
    players = ev.get("players", [])
    dealer  = ev.get("dealer", "")
    sb      = ev.get("sb", "")
    bb      = ev.get("bb", "")

    sep("═")
    print(f"{CYAN}{BOLD}  페이즈: {phase:<12} 팟: {pot}칩{RESET}")
    if dealer:
        line = f"  딜러:{dealer}"
        if sb: line += f"  SB:{sb}"
        if bb: line += f"  BB:{bb}"
        print(GRAY + line + RESET)
    sep()
    print(f"  커뮤니티:  {BOLD}{comm if comm != '-' else '(없음)'}{RESET}")
    sep()
    for p in players:
        pid   = p.get("player_id", "")
        nick  = p.get("nickname", pid)
        stack = p.get("stack", 0)
        bet   = p.get("current_bet", 0)
        me    = f" {MAGENTA}◀YOU{RESET}" if pid == my_id else ""
        star  = f" {YELLOW}★{RESET}"    if pid == cur  else ""
        marks = ""
        if p.get("is_folded"):  marks += f" {RED}[폴드]{RESET}"
        if p.get("is_all_in"): marks += f" {YELLOW}[올인]{RESET}"
        bet_txt = f"  베팅:{YELLOW}{bet}{RESET}" if bet else ""
        print(f"  {BOLD}{nick:10s}{RESET} 스택:{GREEN}{stack:5d}{RESET}{bet_txt}{me}{star}{marks}")
    sep("═")


def parse_action(text: str):
    parts = text.strip().lower().split()
    if not parts:
        return None
    cmd = parts[0]
    if cmd in ("fold", "f"):
        return "fold", 0
    if cmd in ("check", "c", "x"):
        return "check", 0
    if cmd in ("call", "ca"):
        return "call", 0
    if cmd in ("allin", "all", "a"):
        return "allin", 0
    if cmd in ("raise", "r", "bet", "b"):
        if len(parts) < 2:
            return None
        try:
            return "raise", int(parts[1])
        except ValueError:
            return None
    return None


async def read_action(va: dict, loop: asyncio.AbstractEventLoop):
    opts = []
    if va.get("check"):
        opts.append("체크(c)")
    if va.get("call"):
        call_amt = va.get("call_amount", 0)
        is_allin_call = call_amt >= va.get("allin_amount", call_amt + 1)
        label = f"콜(ca)  {call_amt}칩" + (" [올인]" if is_allin_call else "")
        opts.append(label)
    if va.get("raise"):
        opts.append(f"레이즈(r) <금액>  최소:{va.get('min_raise', 0)}")
    opts.append("폴드(f)")

    print(f"\n{CYAN}{BOLD}  ★ 당신의 차례 ★{RESET}")
    print(f"  가능: {YELLOW}{' / '.join(opts)}{RESET}")

    while True:
        try:
            raw = await loop.run_in_executor(None, lambda: input(f"{BOLD}  액션> {RESET}"))
        except EOFError:
            return "fold", 0

        result = parse_action(raw.strip())
        if result is None:
            print(f"  {RED}알 수 없는 명령. 예: check / call / raise 100 / allin / fold{RESET}")
            continue

        action, amount = result

        if action == "check" and not va.get("check"):
            print(f"  {RED}지금 check는 불가합니다.{RESET}")
            continue
        if action == "call" and not va.get("call"):
            print(f"  {RED}지금 call은 불가합니다.{RESET}")
            continue
        if action == "raise":
            if not va.get("raise"):
                print(f"  {RED}지금 raise는 불가합니다.{RESET}")
                continue
            min_r = va.get("min_raise", 0)
            if amount < min_r:
                print(f"  {RED}최소 레이즈: {min_r}칩{RESET}")
                continue
        if action == "allin" and not va.get("allin"):
            print(f"  {RED}지금 allin은 불가합니다.{RESET}")
            continue

        return action, amount


async def run(player_id: str, nickname: str, room_id: str) -> None:
    uri  = f"{SERVER}/{room_id}/{player_id}"
    loop = asyncio.get_event_loop()
    my_hole: list = []

    sep("═")
    print(f"  {BOLD}Texas Hold'em 대화형 클라이언트{RESET}")
    print(f"  플레이어: {BOLD}{nickname}{RESET} ({player_id})  |  룸: {BOLD}{room_id}{RESET}")
    print(f"  서버: {uri}")
    sep("═")

    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({
                "event":          "join_room",
                "room_id":        room_id,
                "nickname":       nickname,
                "starting_chips": 1000,
                "small_blind":    10,
                "big_blind":      20,
                "turn_timeout":   30,
            }))
            log("접속", "서버 연결 완료", CYAN)

            await ws.send(json.dumps({"event": "ready"}))
            log("준비", "ready 전송", GRAY)

            async for raw in ws:
                ev    = json.loads(raw)
                event = ev.get("event")

                if event == "player_joined":
                    pid  = ev.get("player_id", "?")
                    nick = ev.get("nickname", pid)
                    if pid == player_id:
                        log("입장", "내가 입장함", CYAN)
                    else:
                        log("입장", f"'{nick}' 입장 — 게임 대기 중...", GREEN)

                elif event == "player_ready":
                    pid = ev.get("player_id", "?")
                    who = "나" if pid == player_id else pid
                    log("준비", f"{who} 준비 완료", GRAY)

                elif event == "player_left":
                    pid = ev.get("player_id", "?")
                    log("퇴장", f"{pid} 퇴장", YELLOW)

                elif event == "deal_hole_cards":
                    my_hole = ev.get("cards", [])
                    sep("─")
                    print(f"  {GREEN}{BOLD}내 홀카드: {cards_str(my_hole)}{RESET}")
                    sep("─")

                elif event == "game_state":
                    print_game_state(ev, player_id)
                    if my_hole:
                        print(f"  {GREEN}{BOLD}내 홀카드: {cards_str(my_hole)}{RESET}\n")

                elif event == "action_required":
                    target = ev.get("player_id")
                    va     = ev.get("valid_actions", {})
                    if target == player_id:
                        action, amount = await read_action(va, loop)
                        log("전송", f"{YELLOW}{action}{RESET}" + (f" {amount}" if amount else ""), BOLD)
                        await ws.send(json.dumps({
                            "event":  "player_action",
                            "action": action,
                            "amount": amount,
                        }))
                    else:
                        print(f"  {GRAY}상대방({target}) 차례 — 대기 중...{RESET}")

                elif event == "player_acted":
                    pid    = ev.get("player_id")
                    action = ev.get("action")
                    amt    = ev.get("amount", 0)
                    who    = f"{MAGENTA}나{RESET}" if pid == player_id else pid
                    amt_txt = f" {amt}" if amt else ""
                    log("액션", f"{who}: {YELLOW}{action}{RESET}{amt_txt}", GRAY)

                elif event == "showdown":
                    comm = cards_str(ev.get("community_cards", []))
                    results = ev.get("results", [])
                    sep("═")
                    print(f"  커뮤니티: {BOLD}{comm}{RESET}")
                    sep()
                    for r in results:
                        pid  = r["player_id"]
                        who  = f"{MAGENTA}나{RESET}" if pid == player_id else pid
                        hand = cards_str(r.get("cards", []))
                        best = cards_str(r.get("best_hand", []))
                        rank = r.get("hand_rank", "")
                        won  = r.get("won", 0)
                        color = GREEN if won > 0 else GRAY
                        print(f"  {color}{BOLD}{who}{RESET}  홀카드:{hand}")
                        print(f"        최강패:{best}  족보:{BOLD}{rank}{RESET}  획득:{color}{BOLD}{won}칩{RESET}")
                    sep("═")
                    # 승리 결과 크게 표시
                    winner_r = max(results, key=lambda r: r.get("won", 0)) if results else None
                    if winner_r and winner_r.get("won", 0) > 0:
                        who_w = "나" if winner_r["player_id"] == player_id else winner_r.get("player_id", "?")
                        rank_w = winner_r.get("hand_rank", "")
                        won_w  = winner_r.get("won", 0)
                        wcolor = GREEN if winner_r["player_id"] == player_id else YELLOW
                        banner = f"  ★  {who_w} 승리 — {rank_w}  (+{won_w}칩)  ★"
                        bar    = "═" * (len(banner) - 10)
                        print(f"\n{wcolor}{BOLD}{bar}{RESET}")
                        print(f"{wcolor}{BOLD}{banner}{RESET}")
                        print(f"{wcolor}{BOLD}{bar}{RESET}\n")
                    my_hole = []
                    print(f"  {GRAY}다음 핸드가 5초 후 시작됩니다...{RESET}\n")

                elif event == "hand_end":
                    winner = ev.get("winner")
                    reason = ev.get("reason")
                    wcolor = GREEN if winner == player_id else YELLOW
                    who_label = "나" if winner == player_id else winner
                    banner = f"  ★  {who_label} 승리 — 상대 폴드  ★"
                    bar    = "═" * (len(banner) - 10)
                    print(f"\n{wcolor}{BOLD}{bar}{RESET}")
                    print(f"{wcolor}{BOLD}{banner}{RESET}")
                    print(f"{wcolor}{BOLD}{bar}{RESET}\n")
                    my_hole = []
                    print(f"  {GRAY}다음 핸드가 5초 후 시작됩니다...{RESET}\n")

                elif event == "game_over":
                    sep("═")
                    print(f"{RED}{BOLD}  ★ 게임 종료 — 칩이 부족한 플레이어가 있습니다 ★{RESET}")
                    sep("═")

                elif event == "chat_broadcast":
                    nick = ev.get("nickname", "?")
                    msg  = ev.get("message", "")
                    print(f"  {MAGENTA}[채팅] {nick}: {msg}{RESET}")

                elif event == "kicked":
                    log("강제퇴장", "호스트에 의해 퇴장되었습니다", RED)
                    break

                elif event == "error":
                    code   = ev.get("code", "")
                    detail = ev.get("detail", "")
                    log("에러", f"{RED}{code}{RESET} {detail}", RED)

                else:
                    log("기타", f"{GRAY}{ev}{RESET}", GRAY)

    except websockets.exceptions.ConnectionClosed as e:
        log("연결 끊김", str(e), RED)
    except KeyboardInterrupt:
        print(f"\n{YELLOW}종료합니다.{RESET}")
    except Exception as e:
        log("오류", str(e), RED)
        raise


def main() -> None:
    if len(sys.argv) < 3:
        print("사용법: python interactive_client.py <player_id> <nickname> [room_id]")
        print("예:    python interactive_client.py alice Alice ROOM1")
        sys.exit(1)

    player_id = sys.argv[1]
    nickname  = sys.argv[2]
    room_id   = sys.argv[3] if len(sys.argv) > 3 else "TESTROOM1"

    asyncio.run(run(player_id, nickname, room_id))


if __name__ == "__main__":
    main()
