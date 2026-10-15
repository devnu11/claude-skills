"""Test helper: hold a chat directory's lock until killed.

``python tests/hold_lock.py <chat dir>`` installs the CLI's SIGTERM handler,
takes ``Store(<chat dir>).hold_lock()``, prints ``locked`` and sleeps.
"""

from __future__ import annotations

import signal
import sys
import time
from pathlib import Path

from group_chat.cli import exit_on_sigterm
from group_chat.state import Store


def main(directory: str) -> None:
    signal.signal(signal.SIGTERM, exit_on_sigterm)
    with Store(Path(directory)).hold_lock():
        print("locked", flush=True)
        time.sleep(60)


if __name__ == "__main__":
    main(sys.argv[1])
