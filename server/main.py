from __future__ import annotations
import asyncio
import json
import random
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from game.room_manager import RoomManager
from game.game_state import Phase
from game.ai_strategy import decide_action

room_manager = RoomManager()
AI_TURN_TIMEOUT = 3.0

AI_NICK_POOL = ["Bot-강철", "Bot-여우", "Bot-독수리", "Bot-호랑이",
                "Bot-늑대", "Bot-곰", "Bot-사자", "Bot-표범"]


# ------------------------------------------------------------------ broadcast
async def broadcast(room_id: str, payload: dict, exclude: str | None = None) -> None:
    room = room_manager.get_room(room_id)
    if room is None:
        return
    dead: list[str] = []
    for pid, ws in room.websockets.items():
        if pid == exclude:
            continue
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(pid)
    for pid in dead:
        room.websockets.pop(pid, None)


async def send_to(room_id: str, player_id: str, payload: dict) -> None:
    room = room_manager.get_room(room_id)
    if room is None:
        return
    ws = room.websockets.get(player_id)
    if ws:
        try:
            await ws.send_json(payload)
        except Exception:
            room.websockets.pop(player_id, None)


async def dispatch_events(room_id: str, events: list[dict]) -> None:
    """Send events to clients. AI players have no WebSocket so send_to silently skips them.
    After dispatch, schedule AI action or auto-start next hand as appropriate."""
    room = room_manager.get_room(room_id)
    if room is None:
        return

    for i, ev in enumerate(events):
        if ev.get("event") == "action_required" and ev.get("player_id") in room.ai_players:
            room.game.turn_deadline = time.time() + AI_TURN_TIMEOUT
            ev["deadline"] = room.game.turn_deadline

        if ev.get("event") == "deal_hole_cards":
            await send_to(room_id, ev["target"], ev)
        else:
            await broadcast(room_id, ev)

        if ev.get("event") == "game_state":
            nxt = events[i + 1] if i + 1 < len(events) else None
            if nxt and nxt.get("event") in ("game_state", "showdown"):
                await asyncio.sleep(1.5)

    last_ev = events[-1].get("event") if events else None

    # Hand ended -> schedule auto-start
    if last_ev in ("hand_end", "showdown"):
        asyncio.create_task(_auto_start_next_hand(room_id))
        return

    # Action required -> if AI's turn, schedule AI action
    for ev in events:
        if ev.get("event") == "action_required":
            pid = ev.get("player_id")
            if pid in room.ai_players:
                asyncio.create_task(_ai_act(room_id, pid))
            break


# ------------------------------------------------------------------ AI logic
async def _ai_act(room_id: str, player_id: str) -> None:
    await asyncio.sleep(random.uniform(0.4, 1.0))
    room = room_manager.get_room(room_id)
    if room is None:
        return
    g = room.game
    if g.phase not in (Phase.PRE_FLOP, Phase.FLOP, Phase.TURN, Phase.RIVER):
        return
    active = g._active_players()
    if not active:
        return
    if active[g.current_player_index % len(active)] != player_id:
        return  # no longer this AI's turn
    try:
        action, amount = decide_action(g, player_id)
        events = g.apply_action(player_id, action, amount)
        await dispatch_events(room_id, events)
    except Exception as e:
        print(f"[AI ERROR] {player_id}: {e}")


async def _auto_start_next_hand(room_id: str) -> None:
    await asyncio.sleep(5)
    room = room_manager.get_room(room_id)
    if room is None:
        return
    for pid in room.game.seat_order:
        room.game.set_ready(pid)
    if room.game.can_start():
        events = room.game.start_hand()
        await dispatch_events(room_id, events)


def _fill_ai_bots(room_id: str) -> None:
    """Fill remaining seats (up to max_players) with AI bots."""
    room = room_manager.get_room(room_id)
    if room is None:
        return
    nicks = list(AI_NICK_POOL)
    random.shuffle(nicks)
    nick_iter = iter(nicks)
    idx = 1
    while len(room.game.seat_order) < room.game.max_players:
        ai_id = f"AI_BOT_{idx}"
        nick = next(nick_iter, f"Bot{idx}")
        ok = room.game.add_player(ai_id, nick)
        if ok:
            room.ai_players.add(ai_id)
            room.game.set_ready(ai_id)
        idx += 1


# ------------------------------------------------------------------ turn timer
async def turn_timer_loop() -> None:
    while True:
        await asyncio.sleep(1)
        now = time.time()
        for room in list(room_manager._rooms.values()):
            g = room.game
            if g.phase not in (Phase.PRE_FLOP, Phase.FLOP, Phase.TURN, Phase.RIVER):
                continue
            if g.turn_deadline and now > g.turn_deadline:
                active = g._active_players()
                if not active:
                    continue
                pid = active[g.current_player_index % len(active)]
                if pid not in room.ai_players:
                    # 인간 플레이어 타임아웃 → 자동 폴드
                    events = g.apply_action(pid, "fold")
                    await dispatch_events(room.room_id, events)
                else:
                    # AI 봇 타임아웃 폴백 (비정상 종료 대비)
                    try:
                        action, amount = decide_action(g, pid)
                        events = g.apply_action(pid, action, amount)
                        await dispatch_events(room.room_id, events)
                    except Exception as e:
                        print(f"[TIMER AI ERROR] {pid}: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(turn_timer_loop())
    yield
    task.cancel()


# ------------------------------------------------------------------ app
app = FastAPI(title="HoldemServer", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/rooms")
def list_rooms():
    return room_manager.list_rooms()


@app.get("/health")
def health():
    return {"status": "ok"}


# ------------------------------------------------------------------ WebSocket
@app.websocket("/ws/{room_id}/{player_id}")
async def websocket_endpoint(ws: WebSocket, room_id: str, player_id: str):
    await ws.accept()

    try:
        raw = await ws.receive_json()
    except Exception:
        await ws.close()
        return

    if raw.get("event") != "join_room":
        await ws.send_json({"event": "error", "code": "MUST_JOIN_FIRST"})
        await ws.close()
        return

    nickname = raw.get("nickname", player_id)
    room_id_payload = raw.get("room_id", room_id)

    if room_manager.get_room(room_id_payload) is None:
        room_manager.create_room(
            host_id=player_id,
            small_blind=raw.get("small_blind", 500),
            big_blind=raw.get("big_blind", 1000),
            starting_chips=raw.get("starting_chips", 100000),
            turn_timeout=raw.get("turn_timeout", 30),
            max_players=raw.get("max_players", 9),
        )
        room = list(room_manager._rooms.values())[-1]
        room_manager._rooms.pop(room.room_id)
        room.room_id = room_id_payload
        room.game.room_id = room_id_payload
        room_manager._rooms[room_id_payload] = room

    err = room_manager.join_room(room_id_payload, player_id, nickname, ws)
    if err:
        await ws.send_json({"event": "error", "code": err})
        await ws.close()
        return

    room = room_manager.get_room(room_id_payload)
    # 닉네임이 "마도리"이면 접속 순서와 무관하게 방장 권한 부여
    if nickname == "마도리" and room:
        room.host_id = player_id
    await broadcast(room_id_payload, {
        "event": "player_joined",
        "player_id": player_id,
        "nickname": nickname,
        "host_id": room.host_id,
        "snapshot": room.game.public_snapshot(),
    })

    try:
        while True:
            data: dict[str, Any] = await ws.receive_json()
            event = data.get("event")

            if event == "ready":
                room.game.set_ready(player_id)
                await broadcast(room_id_payload, {"event": "player_ready", "player_id": player_id})

            elif event == "player_action":
                action = data.get("action", "")
                amount = int(data.get("amount", 0))
                events = room.game.apply_action(player_id, action, amount)
                await dispatch_events(room_id_payload, events)

            elif event == "start_game":
                if player_id == room.host_id:
                    _fill_ai_bots(room_id_payload)
                    for pid in room.game.seat_order:
                        room.game.set_ready(pid)
                    if room.game.can_start():
                        events = room.game.start_hand()
                        await dispatch_events(room_id_payload, events)

            elif event == "chat":
                msg = data.get("message", "")[:200]
                await broadcast(room_id_payload, {
                    "event": "chat_broadcast",
                    "player_id": player_id,
                    "nickname": nickname,
                    "message": msg,
                    "timestamp": time.time(),
                })

            elif event == "leave_room":
                break

            elif event == "kick_player":
                if player_id == room.host_id:
                    target = data.get("target_id")
                    if target and target in room.websockets:
                        await send_to(room_id_payload, target,
                                      {"event": "kicked", "by": player_id})
                        room_manager.leave_room(room_id_payload, target)
                        await broadcast(room_id_payload,
                                        {"event": "player_left", "player_id": target})

            else:
                await ws.send_json({"event": "error", "code": "UNKNOWN_EVENT", "received": event})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await ws.send_json({"event": "error", "code": "SERVER_ERROR", "detail": str(e)})
        except Exception:
            pass
    finally:
        room_manager.leave_room(room_id_payload, player_id)
        room = room_manager.get_room(room_id_payload)
        if room:
            await broadcast(room_id_payload, {
                "event": "player_left",
                "player_id": player_id,
                "snapshot": room.game.public_snapshot(),
            })
