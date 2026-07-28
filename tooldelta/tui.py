"""Terminal-friendly TUI adapter for ToolDelta.

This intentionally uses the terminal's normal scrollback instead of an
alternate-screen fullscreen UI. That keeps mouse wheel scrolling and text
selection/copying working exactly like a regular terminal.
"""

from __future__ import annotations

import builtins
import queue
import shutil
import sys
import threading
import traceback
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app_session
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.styles import Style

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes


@dataclass(frozen=True)
class _Choice:
    value: str
    label: str
    command: str
    description: str


@dataclass
class _PromptRequest:
    prompt: str
    choices: list[_Choice] | None
    default_index: int
    show_when_empty: bool
    response: "queue.Queue[str | BaseException]"


class ToolDeltaTUI:
    """Runs ToolDelta with a bordered prompt and native terminal scrollback."""

    def __init__(self, version: str) -> None:
        self.version = version
        self._real_input = builtins.input
        self._real_stdout = sys.stdout
        self._requests: "queue.Queue[_PromptRequest | None]" = queue.Queue()
        self._stopping = threading.Event()
        self._history: deque[str] = deque(maxlen=12)

        self._original_clear_screen: Callable[[], Any] | None = None
        self._original_ansi_cls: Callable[[], Any] | None = None
        self._original_ansi_save_screen: Callable[[], Any] | None = None
        self._original_ansi_load_screen: Callable[[], Any] | None = None
        self._original_rich_console_file: Any | None = None

        self._session: PromptSession[str] | None = None

    def run(self, target: Callable[[], Any]) -> Any:
        if not self._real_stdin_is_tty() or not self._real_stdout_is_tty():
            return target()

        result: dict[str, Any] = {}
        self._session = PromptSession(
            history=InMemoryHistory(),
            output=get_app_session().output,
            erase_when_done=True,
            style=Style.from_dict({
                "bottom-toolbar": "",
                "bottom-toolbar.text": "",
                "rprompt": "",
            }),
        )
        self._print_header()
        self._install_hooks()

        def worker() -> None:
            try:
                result["value"] = target()
            except BaseException as exc:
                result["exception"] = exc
                if not isinstance(exc, (KeyboardInterrupt, EOFError, SystemExit)):
                    traceback.print_exc()
            finally:
                self.stop()

        thread = threading.Thread(
            target=worker,
            name="ToolDelta TUI runner",
            daemon=True,
        )
        try:
            with patch_stdout(raw=True):
                self._install_stdout_hooks()
                try:
                    thread.start()
                    self._prompt_loop()
                finally:
                    self._restore_stdout_hooks()
        finally:
            self._restore_hooks()
            thread.join(timeout=0.2)

        if "exception" in result:
            exc = result["exception"]
            if isinstance(exc, (KeyboardInterrupt, EOFError, SystemExit)):
                return None
            raise exc
        return result.get("value")

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        self._requests.put(None)

    def input(self, prompt: object = "") -> str:
        return self._request_input(str(prompt), None)

    def select(
        self,
        prompt: str,
        choices: Sequence[tuple[str, str]],
        default_index: int = 0,
        show_when_empty: bool = True,
    ) -> str:
        normalized = [
            self._normalize_choice(str(value), str(label))
            for value, label in choices
        ]
        if not normalized:
            return self._request_input(prompt, None)
        return self._request_input(
            prompt,
            normalized,
            default_index,
            show_when_empty,
        )

    def section_break(self) -> None:
        pass

    def _request_input(
        self,
        prompt: str,
        choices: list[_Choice] | None,
        default_index: int = 0,
        show_when_empty: bool = True,
    ) -> str:
        response: "queue.Queue[str | BaseException]" = queue.Queue(maxsize=1)
        self._requests.put(
            _PromptRequest(
                prompt=prompt,
                choices=choices,
                default_index=max(0, min(default_index, len(choices or []) - 1)),
                show_when_empty=show_when_empty,
                response=response,
            )
        )
        item = response.get()
        if isinstance(item, BaseException):
            raise item
        self._remember_history(item, choices)
        return item

    def _prompt_loop(self) -> None:
        while not self._stopping.is_set():
            request = self._requests.get()
            if request is None:
                return
            try:
                request.response.put(self._read_prompt(request))
            except (KeyboardInterrupt, EOFError) as exc:
                request.response.put(exc)
            except BaseException as exc:
                request.response.put(exc)

    def _read_prompt(self, request: _PromptRequest) -> str:
        choices = request.choices
        index = request.default_index
        default = choices[index].command if choices and request.show_when_empty else ""

        def is_menu_active() -> bool:
            if not choices:
                return False
            if request.show_when_empty:
                return True
            assert self._session is not None
            return self._session.default_buffer.text.strip().startswith(".")

        def set_choice(event: Any, delta: int) -> None:
            nonlocal index
            if not choices or not is_menu_active():
                return
            index = (index + delta) % len(choices)
            event.current_buffer.text = choices[index].command
            event.current_buffer.cursor_position = len(event.current_buffer.text)

        key_bindings = KeyBindings()

        @key_bindings.add("tab")
        @key_bindings.add("down")
        def _(event: Any) -> None:
            set_choice(event, 1)

        @key_bindings.add("s-tab")
        @key_bindings.add("up")
        def _(event: Any) -> None:
            set_choice(event, -1)

        @key_bindings.add("pageup")
        def _(event: Any) -> None:
            self._scroll_console_view(-self._scroll_page_size())

        @key_bindings.add("pagedown")
        def _(event: Any) -> None:
            self._scroll_console_view(self._scroll_page_size())

        @key_bindings.add("enter")
        def _(event: Any) -> None:
            event.current_buffer.validate_and_handle()

        assert self._session is not None
        text = self._session.prompt(
            message=self._prompt_message(request.prompt, bool(choices)),
            default=default,
            key_bindings=key_bindings if choices else None,
            mouse_support=False,
            rprompt=self._right_panel,
            bottom_toolbar=lambda: self._bottom_toolbar(
                choices,
                lambda: index,
                request.show_when_empty,
            ),
        )
        if not choices:
            return text
        clean_text = text.strip()
        for choice in choices:
            if clean_text in (choice.command, choice.label, choice.value):
                return choice.value
        if not request.show_when_empty and clean_text == ".":
            return choices[index].value
        if not request.show_when_empty and clean_text == "":
            return ""
        return clean_text or choices[index].value

    def _prompt_message(self, prompt: str, is_choice: bool = False) -> ANSI:
        clean_prompt = prompt.replace("\n", " ")
        width = max(20, shutil.get_terminal_size((80, 24)).columns)
        top = "+" + " input " + "-" * max(0, width - 9) + "+"
        prompt_prefix = "> " if is_choice else clean_prompt
        return ANSI(f"{top}\n| {prompt_prefix}")

    def _bottom_toolbar(
        self,
        choices: list[_Choice] | None,
        index_getter: Callable[[], int],
        show_when_empty: bool = True,
    ) -> str | list[tuple[str, str]]:
        if not choices:
            return "Enter submit | right: history/version"
        assert self._session is not None
        if (
            not show_when_empty
            and not self._session.default_buffer.text.strip().startswith(".")
        ):
            return "Type . to show commands | Enter submit"
        selected_index = index_getter()
        fragments: list[tuple[str, str]] = [
            ("", "Tab/Up/Down/Wheel select | Enter submit\n")
        ]
        visible_count = 5
        start_index = min(
            max(0, selected_index - visible_count // 2),
            max(0, len(choices) - visible_count),
        )
        visible_choices = choices[start_index : start_index + visible_count]
        command_width = min(
            28,
            max(len(choice.command) for choice in visible_choices) + 2,
        )
        if start_index > 0:
            fragments.append(("", "  ...\n"))
        for offset, choice in enumerate(visible_choices):
            idx = start_index + offset
            is_selected = idx == selected_index
            marker = "> " if is_selected else "  "
            line = (
                marker
                + choice.command.ljust(command_width)
                + choice.description
            )
            style = "ansiblue bold" if is_selected else ""
            fragments.append((style, line))
            if offset != len(visible_choices) - 1:
                fragments.append(("", "\n"))
        if start_index + visible_count < len(choices):
            fragments.append(("", "\n  ..."))
        return fragments

    def _right_panel(self) -> str:
        latest = self._history[-1] if self._history else "暂无历史"
        width = 38 if shutil.get_terminal_size((80, 24)).columns >= 100 else 24
        return self._fit_cell(f"历史: {latest}", width) + " | " + f"version {self.version}"

    @staticmethod
    def _scroll_page_size() -> int:
        return max(1, shutil.get_terminal_size((80, 24)).lines - 4)

    @staticmethod
    def _scroll_console_view(delta: int) -> None:
        if sys.platform != "win32":
            return

        class COORD(ctypes.Structure):
            _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

        class SMALL_RECT(ctypes.Structure):
            _fields_ = [
                ("Left", wintypes.SHORT),
                ("Top", wintypes.SHORT),
                ("Right", wintypes.SHORT),
                ("Bottom", wintypes.SHORT),
            ]

        class CONSOLE_SCREEN_BUFFER_INFO(ctypes.Structure):
            _fields_ = [
                ("dwSize", COORD),
                ("dwCursorPosition", COORD),
                ("wAttributes", wintypes.WORD),
                ("srWindow", SMALL_RECT),
                ("dwMaximumWindowSize", COORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.GetStdHandle(-11)
        if handle in (0, -1):
            return
        info = CONSOLE_SCREEN_BUFFER_INFO()
        if not kernel32.GetConsoleScreenBufferInfo(handle, ctypes.byref(info)):
            return
        height = info.srWindow.Bottom - info.srWindow.Top
        max_top = max(0, info.dwSize.Y - height - 1)
        new_top = max(0, min(max_top, info.srWindow.Top + delta))
        new_rect = SMALL_RECT(
            info.srWindow.Left,
            new_top,
            info.srWindow.Right,
            new_top + height,
        )
        kernel32.SetConsoleWindowInfo(handle, True, ctypes.byref(new_rect))

    def _remember_history(
        self,
        value: str,
        choices: list[_Choice] | None,
    ) -> None:
        label = value
        if choices:
            for choice in choices:
                if choice.value == value:
                    label = f"{choice.command} {choice.description}".strip()
                    break
        label = label.strip()
        if label:
            self._history.append(label)

    @staticmethod
    def _fit_cell(text: str, width: int) -> str:
        if width <= 0:
            return ""
        text = text.replace("\n", " ")
        text_width = 0
        chars: list[str] = []
        for char in text:
            char_width = 1 if char.isascii() else 2
            if text_width + char_width > width:
                break
            chars.append(char)
            text_width += char_width
        return "".join(chars) + " " * max(0, width - text_width)

    @staticmethod
    def _normalize_choice(value: str, label: str) -> _Choice:
        clean_label = label.strip()
        if clean_label.startswith(("/", ".")):
            parts = clean_label.split(maxsplit=1)
            command = parts[0]
            description = parts[1] if len(parts) > 1 else ""
            return _Choice(value, clean_label, command, description)

        description = ""
        command = clean_label
        for separator in (" - ", ". "):
            if separator in clean_label:
                _, right = clean_label.split(separator, 1)
                command = right.strip() or clean_label
                break
        return _Choice(value, clean_label, command, description)

    def _print_header(self) -> None:
        label = f"version {self.version}"
        width = shutil.get_terminal_size((80, 24)).columns
        print(label.rjust(max(len(label), width - 1)))

    def _install_hooks(self) -> None:
        builtins.input = self.input
        self._install_clear_hooks()
        try:
            from tooldelta.internal import tui_bridge
        except Exception:
            return
        tui_bridge.set_current(self)

    def _restore_hooks(self) -> None:
        builtins.input = self._real_input
        self._restore_clear_hooks()
        try:
            from tooldelta.internal import tui_bridge
        except Exception:
            return
        tui_bridge.set_current(None)

    def _install_clear_hooks(self) -> None:
        try:
            from tooldelta import plugin_manager
            from tooldelta.utils import fmts
        except Exception:
            return
        self._original_clear_screen = plugin_manager.clear_screen
        self._original_ansi_cls = fmts.ansi_cls
        self._original_ansi_save_screen = fmts.ansi_save_screen
        self._original_ansi_load_screen = fmts.ansi_load_screen
        plugin_manager.clear_screen = self.section_break
        fmts.ansi_cls = self.section_break
        fmts.ansi_save_screen = lambda: None
        fmts.ansi_load_screen = lambda: None

    def _install_stdout_hooks(self) -> None:
        try:
            from tooldelta.utils.fmts import logger
        except Exception:
            return
        self._original_rich_console_file = logger.console._file
        logger.console._file = sys.stdout

    def _restore_stdout_hooks(self) -> None:
        if self._original_rich_console_file is None:
            return
        try:
            from tooldelta.utils.fmts import logger
        except Exception:
            return
        logger.console._file = self._original_rich_console_file
        self._original_rich_console_file = None

    def _restore_clear_hooks(self) -> None:
        try:
            from tooldelta import plugin_manager
            from tooldelta.utils import fmts
        except Exception:
            return
        if self._original_clear_screen is not None:
            plugin_manager.clear_screen = self._original_clear_screen
        if self._original_ansi_cls is not None:
            fmts.ansi_cls = self._original_ansi_cls
        if self._original_ansi_save_screen is not None:
            fmts.ansi_save_screen = self._original_ansi_save_screen
        if self._original_ansi_load_screen is not None:
            fmts.ansi_load_screen = self._original_ansi_load_screen

    def _real_stdin_is_tty(self) -> bool:
        isatty = getattr(sys.stdin, "isatty", None)
        return bool(isatty and isatty())

    def _real_stdout_is_tty(self) -> bool:
        isatty = getattr(self._real_stdout, "isatty", None)
        return bool(isatty and isatty())


def run_with_tui(target: Callable[[], Any], version: str) -> Any:
    return ToolDeltaTUI(version=version).run(target)


def main() -> None:
    import os

    from .launch_options import client_title
    from .version import get_tool_delta_version

    run_with_tui(
        client_title,
        ".".join(str(i) for i in get_tool_delta_version()),
    )
    os._exit(1)


if __name__ == "__main__":
    main()
