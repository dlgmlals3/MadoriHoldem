from __future__ import annotations
import random
from dataclasses import dataclass
from enum import IntEnum


class Suit(IntEnum):
    SPADE = 0
    HEART = 1
    DIAMOND = 2
    CLUB = 3


SUIT_SYMBOLS = {Suit.SPADE: "♠", Suit.HEART: "♥", Suit.DIAMOND: "♦", Suit.CLUB: "♣"}
RANK_SYMBOLS = {2: "2", 3: "3", 4: "4", 5: "5", 6: "6", 7: "7", 8: "8",
                9: "9", 10: "10", 11: "J", 12: "Q", 13: "K", 14: "A"}


@dataclass(frozen=True)
class Card:
    rank: int   # 2~14 (A=14)
    suit: Suit

    def __str__(self) -> str:
        return f"{RANK_SYMBOLS[self.rank]}{SUIT_SYMBOLS[self.suit]}"

    def to_dict(self) -> dict:
        return {"rank": self.rank, "suit": self.suit.value, "display": str(self)}


class Deck:
    def __init__(self) -> None:
        self._cards: list[Card] = [
            Card(rank, suit)
            for suit in Suit
            for rank in range(2, 15)
        ]
        self.shuffle()

    def shuffle(self) -> None:
        random.shuffle(self._cards)

    def deal(self) -> Card:
        if not self._cards:
            raise RuntimeError("Deck is empty")
        return self._cards.pop()

    def burn(self) -> None:
        self._cards.pop()

    def __len__(self) -> int:
        return len(self._cards)
