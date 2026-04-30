"""
core/config.py

Runtime configuration flags set by the CLI and read by matching/identity modules.

Keeping these as module-level variables (rather than threading them through every
function signature) avoids cluttering the internal APIs.  The CLI sets them once
at startup before any diffing work begins.
"""

# When True, verbose matching/pairing decisions are printed to stdout.
# Enable with --debug-match.
DEBUG_MATCH: bool = False

def debug_log(*args, **kwargs):
    """Print only when DEBUG_MATCH is active."""
    if DEBUG_MATCH:
        print(*args, **kwargs)