"""Optional bridge used by ToolDelta when the TUI adapter is active."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol


class TUIBridge(Protocol):
    def select(
        self,
        prompt: str,
        choices: Sequence[tuple[str, str]],
        default_index: int = 0,
        show_when_empty: bool = True,
    ) -> str: ...


_current: TUIBridge | None = None


def set_current(tui: TUIBridge | None) -> None:
    global _current
    _current = tui


def is_active() -> bool:
    return _current is not None


def select(
    prompt: str,
    choices: Sequence[tuple[str, str]],
    default_index: int = 0,
    show_when_empty: bool = True,
) -> str | None:
    if _current is None:
        return None
    return _current.select(prompt, choices, default_index, show_when_empty)
