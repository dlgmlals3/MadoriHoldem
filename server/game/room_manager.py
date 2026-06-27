from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from typing import Optional
from .game_state import GameState, Phase


@dataclass
class Room:
    room_id: str
    host_id: str
    game: GameState
    websockets: dict = field(default_factory=dict)  # player_id -> WebSocket

    def is_empty(self) -> bool:
        return len(self.websockets) == 0


class RoomManager:
    def __init__(self) -> None:
        self._rooms: dict[str, Room] = {}

    def create_room(
        self,
        host_id: str,
        small_blind: int = 10,
        big_blind: int = 20,
        starting_chips: int = 1000,
        turn_timeout: int = 30,
        max_players: int = 9,
    ) -> Room:
        room_id = str(uuid.uuid4())[:8].upper()
        game = GameState(
            room_id=room_id,
            small_blind=small_blind,
            big_blind=big_blind,
            starting_chips=starting_chips,
            turn_timeout=turn_timeout,
            max_players=max_players,
        )
        room = Room(room_id=room_id, host_id=host_id, game=game)
        self._rooms[room_id] = room
        return room

    def get_room(self, room_id: str) -> Optional[Room]:
        return self._rooms.get(room_id)

    def delete_room(self, room_id: str) -> None:
        self._rooms.pop(room_id, None)

    def list_rooms(self) -> list[dict]:
        return [
            {
                "room_id": r.room_id,
                "host_id": r.host_id,
                "phase": r.game.phase.value,
                "players": len(r.game.seats),
                "max_players": r.game.max_players,
            }
            for r in self._rooms.values()
        ]

    def join_room(self, room_id: str, player_id: str, nickname: str, ws) -> Optional[str]:
        """Returns error string or None on success."""
        room = self.get_room(room_id)
        if room is None:
            return "ROOM_NOT_FOUND"
        if room.game.phase not in (Phase.WAITING, Phase.HAND_END):
            if player_id not in room.game.seats:
                return "GAME_IN_PROGRESS"
        ok = room.game.add_player(player_id, nickname)
        if not ok:
            return "ROOM_FULL"
        room.websockets[player_id] = ws
        return None

    def leave_room(self, room_id: str, player_id: str) -> None:
        room = self.get_room(room_id)
        if room is None:
            return
        room.websockets.pop(player_id, None)
        if room.game.phase in (Phase.WAITING, Phase.HAND_END):
            room.game.remove_player(player_id)
        if room.is_empty():
            self.delete_room(room_id)
