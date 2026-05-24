"""Internal utilities shared across paper_agent entry points."""
import sys


def reconfigure_utf8() -> None:
    """Windows cp936 fallback (PEP 686 / Python 3.15 default-UTF-8 prep).

    Called at the top of any CLI main() that may run as a subprocess on
    Windows, so stdout/stderr emit UTF-8 instead of cp936.
    """
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
