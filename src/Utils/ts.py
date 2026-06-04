from datetime import datetime


def ts(msg=""):
    """Returns msg prefixed with [HH:MM:SS] — same format as the shell scripts."""
    return f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
