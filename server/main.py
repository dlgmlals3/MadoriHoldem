from __future__ import annotations
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from game.room_manager import RoomManager
from game.game_state import Phase

room_manager = RoomManager()


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
    """Send events — deal_hole_cards go private, rest broadcast.
    Consecutive game_state events (all-in runout) get a 1.5s pause between
    streets so clients can see each street before the next is dealt."""
    for i, ev in enumerate(events):
        if ev.get("event") == "deal_hole_cards":
            await send_to(room_id, ev["target"], ev)
        else:
            await broadcast(room_id, ev)

        if ev.get("event") == "game_state":
            nxt = events[i + 1] if i + 1 < len(events) else None
            if nxt and nxt.get("event") in ("game_state", "showdown"):
                # All-in runout: pause between streets
                await asyncio.sleep(1.5)


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
                events = g.apply_action(pid, "fold")
                await dispatch_events(room.room_id, events)


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

    # first message must be join_room
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

    # auto-create room if it doesn't exist
    if room_manager.get_room(room_id_payload) is None:
        room_manager.create_room(
            host_id=player_id,
            small_blind=raw.get("small_blind", 10),
            big_blind=raw.get("big_blind", 20),
            starting_chips=raw.get("starting_chips", 1000),
            turn_timeout=raw.get("turn_timeout", 30),
            max_players=raw.get("max_players", 9),
        )
        # override generated id — reuse path param
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
    await broadcast(room_id_payload, {
        "event": "player_joined",
        "player_id": player_id,
        "nickname": nickname,
        "snapshot": room.game.public_snapshot(),
    })

    try:
        while True:
            data: dict[str, Any] = await ws.receive_json()
            event = data.get("event")

            if event == "ready":
                room.game.set_ready(player_id)
                await broadcast(room_id_payload, {"event": "player_ready", "player_id": player_id})
                if room.game.can_start():
                    events = room.game.start_hand()
                    await dispatch_events(room_id_payload, events)

            elif event == "player_action":
                action = data.get("action", "")
                amount = int(data.get("amount", 0))
                events = room.game.apply_action(player_id, action, amount)
                await dispatch_events(room_id_payload, events)
                # auto-start next hand after HAND_END
                if room.game.phase == Phase.HAND_END:
                    await asyncio.sleep(5)
                    for pid in room.game.seat_order:
                        room.game.set_ready(pid)
                    if room.game.can_start():
                        events = room.game.start_hand()
                        await dispatch_events(room_id_payload, events)

            elif event == "start_game":
                if player_id == room.host_id:
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
