import os
from pathlib import Path

import reflex as rx

# Reflex's dev server hot-reloads the backend whenever a non-ignored file
# under the project root changes — and by default that includes projects/,
# where the coding agent (and now groundhog/lib/runs.py's run-tracking) write
# continuously while an experiment runs. A reload mid-run kills the backend
# worker — and any agent subprocess still attached to it — which looks like
# the run "finishing" with nothing written, and confuses the run-tracking
# lock into (correctly, given the process really did die) reclaiming it as
# stale. Data the agent/runner write must never be treated as an app source
# change, so it's excluded from the watch entirely.
os.environ.setdefault(
    "REFLEX_HOT_RELOAD_EXCLUDE_PATHS",
    str(Path(__file__).resolve().parent / "projects"),
)

config = rx.Config(
    app_name="groundhog",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
    ]
)