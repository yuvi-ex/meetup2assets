"""Local stub so board.py imports outside a deployed workspace.

Only dryrun.py uses this. deploy_dashboard.py pushes harness.py and
board.py from this directory and never this file, so a deployed app
still binds the real dash-server helper sitting next to its own copy.
"""


def load_row(*_a, **_k):
    raise RuntimeError("dryrun calls SQL directly, not through board")


def load_rows(*_a, **_k):
    raise RuntimeError("dryrun calls SQL directly, not through board")


def has_error(payload):
    return isinstance(payload, dict) and "_error" in payload


def render_error_panel(_error):
    return None
