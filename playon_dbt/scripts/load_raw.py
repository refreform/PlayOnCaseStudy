"""Land the four PrepCast CSV extracts into DuckDB as a `raw` schema.

Deliberate choice: every column is ingested as VARCHAR (`all_varchar=true`), with no type
sniffing and no header-based coercion.

DuckDB's CSV sniffer is good enough that it would quietly paper over the exact defects this
case study is about. Given a column mixing ISO-8601 and epoch-second timestamps it will pick
one type and null the rest, and the null then looks like missing data rather than a format
collision. Landing everything as text keeps the raw layer a faithful copy of what the source
systems emitted; casting is a decision made explicitly in staging, where it can be tested.

This mirrors how a real warehouse's raw/bronze layer behaves: preserve the bytes, argue about
types downstream.

Re-runnable: drops and recreates the raw schema each time.
"""

import pathlib
import duckdb

HERE = pathlib.Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA = PROJECT.parent / "data"
DB = PROJECT / "playon.duckdb"

TABLES = {
    "playback_events": "playback_events.csv",
    "subscriptions": "subscriptions.csv",
    "asset_catalog": "asset_catalog.csv",
    "users": "users.csv",
}


def main() -> None:
    con = duckdb.connect(str(DB))
    con.execute("DROP SCHEMA IF EXISTS raw CASCADE")
    con.execute("CREATE SCHEMA raw")

    for table, filename in TABLES.items():
        path = DATA / filename
        if not path.exists():
            raise FileNotFoundError(f"missing source extract: {path}")
        con.execute(
            f"""
            CREATE TABLE raw.{table} AS
            SELECT *
            FROM read_csv(
                ?,
                all_varchar = true,   -- no sniffing; see module docstring
                header = true,
                sample_size = -1      -- read the whole file, don't infer from a sample
            )
            """,
            [str(path)],
        )
        rows = con.execute(f"SELECT count(*) FROM raw.{table}").fetchone()[0]
        cols = con.execute(
            "SELECT count(*) FROM duckdb_columns "
            "WHERE schema_name = 'raw' AND table_name = ?",
            [table],
        ).fetchone()[0]
        print(f"raw.{table:<18} {rows:>8,} rows  {cols:>2} cols  <- {filename}")

    con.close()
    print(f"\nwrote {DB}")


if __name__ == "__main__":
    main()
