"""Launch the DuckDB web UI against playon.duckdb.

Opens a local SQL editor in the browser (http://localhost:4213) with the `raw` schema — and
later the dbt-built staging/intermediate/marts schemas — browsable in the sidebar.

    .venv/Scripts/python.exe scripts/duckdb_ui.py

Ctrl-C to stop.

IMPORTANT — DuckDB allows a single read-write process at a time. While this UI is running it
holds the write lock, so `dbt run` will fail with an IO error until you stop it. Stop the UI
before running dbt; restart it afterwards. (Read-only connections can coexist, which is why
the profiling scripts all open with read_only=True.)
"""

import pathlib
import duckdb

DB = pathlib.Path(__file__).resolve().parent.parent / "playon.duckdb"

con = duckdb.connect(str(DB))
con.execute("INSTALL ui")
con.execute("LOAD ui")
con.execute("CALL start_ui()")

print(f"DuckDB UI serving {DB.name} at http://localhost:4213")
print("holding the write lock -- stop this (Ctrl-C) before running dbt")
try:
    import time

    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    print("\nshutting down")
    con.close()
