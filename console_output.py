"""Best-effort console mirroring, separate from durable file logging."""

import sys


def write_console(text: str) -> bool:
    stream = sys.stdout
    if stream is None:
        return False
    try:
        try:
            stream.write(text)
        except UnicodeEncodeError:
            encoding = getattr(stream, "encoding", None) or "ascii"
            stream.write(text.encode(encoding, errors="replace").decode(encoding))
        stream.flush()
    except (OSError, ValueError):
        # GUI workers may inherit an invalid/closed Windows console or pipe.
        # Disarm the stream as well: Python's final flush otherwise changes
        # the worker's real exit code to 120 after a failed buffered write.
        if sys.stdout is stream:
            sys.stdout = None
        try:
            stream.close()
        except (OSError, ValueError):
            pass
        return False
    return True
