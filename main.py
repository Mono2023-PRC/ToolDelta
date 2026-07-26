import os
import tooldelta
from tui import run_with_tui

run_with_tui(
    tooldelta.client_title,
    ".".join(str(i) for i in tooldelta.get_tool_delta_version()),
)
os._exit(1)
