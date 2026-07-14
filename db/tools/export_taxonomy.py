#!/usr/bin/env python3
"""Export the live taxonomy from Postgres — the sync half of studio-managed vocabularies.

Decision #35: enum VALUES are managed in the database (Curation Studio → Taxonomy page);
this script keeps the repo dynamically linked to it by regenerating:

  db/sql/105_taxonomy_extensions.sql   generated upsert re-seed — `apply.sh` replays
                                       100 (hand-written base) then 105, reproducing the
                                       live vocabulary exactly. Never edit by hand.
  knowledge/data/taxonomy-values.json  the served live values (+ meanings + flags +
                                       usage counts) — read by docs and anything that
                                       wants the current vocabulary without a DB.

taxonomy.md stays the SEMANTIC source of truth (what a family means, tagging rules);
the value LISTS there are documentation that may lag — this export is the live set.

Dependency-free (stdlib; psql / docker exec). Run directly or let curate.py call it
after every taxonomy write:
    python3 db/tools/export_taxonomy.py
"""
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SQL_OUT = ROOT / "db" / "sql" / "105_taxonomy_extensions.sql"
JSON_OUT = ROOT / "knowledge" / "data" / "taxonomy-values.json"
DB_DSN = "postgresql://climbing:climbing@localhost:5432/climbing"
DB_CONTAINER = "climbing-db"

# family → (table, ordered columns, usage-count subquery)
FAMILIES = {
    "discipline": ("discipline", ["code", "meaning"],
                   "SELECT count(*) FROM route_discipline j WHERE j.discipline_code = t.code"),
    "feature": ("feature", ["code", "meaning"],
                "SELECT count(*) FROM route_feature j WHERE j.feature_code = t.code"),
    "character": ("character", ["code", "meaning"],
                  "SELECT count(*) FROM route_character j WHERE j.character_code = t.code"),
    "hazard": ("hazard", ["code", "kind", "meaning", "safety_critical", "feeds"],
               "SELECT count(*) FROM route_hazard j WHERE j.hazard_code = t.code"),
    "rock": ("rock_type", ["code", "friction_dry", "seeps", "fragile_when_wet", "notes"],
             "SELECT count(*) FROM route r WHERE r.rock_code = t.code"),
    "sun_window": ("sun_window", ["code", "meaning"],
                   "SELECT count(*) FROM route r WHERE r.sun_window_code = t.code"),
    "protection": ("protection_grade", ["code", "meaning", "sort_order"],
                   "SELECT count(*) FROM route r WHERE r.protection_code = t.code"),
}


def pg_json(query: str):
    for cmd in (["psql", DB_DSN, "-tAc", query],
                ["docker", "exec", DB_CONTAINER, "psql", "-U", "climbing",
                 "-d", "climbing", "-tAc", query]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                txt = out.stdout.strip()
                txt = txt[txt.index("["):] if "[" in txt else txt  # drop psql SET echo
                return json.loads(txt)
        except Exception:
            continue
    return None


def sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def main():
    data, sql_blocks = {}, []
    for fam, (table, cols, usage_q) in FAMILIES.items():
        rows = pg_json(
            f"SET search_path=climbing; SELECT json_agg(x ORDER BY x.code) FROM "
            f"(SELECT {', '.join(cols)}, ({usage_q}) AS usage FROM {table} t) x;")
        if rows is None:
            sys.exit("[error] Postgres unreachable — taxonomy files left untouched")
        data[fam] = rows
        upd = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "code") or None
        vals = ",\n".join(
            "    (" + ", ".join(sql_lit(r.get(c)) for c in cols) + ")" for r in rows)
        conflict = f"ON CONFLICT (code) DO UPDATE SET {upd}" if upd else "ON CONFLICT (code) DO NOTHING"
        live = ", ".join(sql_lit(r["code"]) for r in rows) or "NULL"
        sql_blocks.append(
            f"-- {fam} ({len(rows)} values)\n"
            # values deleted in the studio must not resurrect when 100 replays;
            # anything NOT IN the live set is unused by definition (delete guard)
            f"DELETE FROM {table} WHERE code NOT IN ({live});\n"
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES\n{vals}\n{conflict};")

    SQL_OUT.write_text(
        "-- 105 — GENERATED taxonomy re-seed (decision #35). Do not edit by hand:\n"
        "-- values are managed in Postgres via the Curation Studio's Taxonomy page and\n"
        "-- exported here by db/tools/export_taxonomy.py so apply.sh reproduces the live\n"
        f"-- vocabulary. Exported {date.today().isoformat()}.\n"
        "SET search_path = climbing, public;\n\n" + "\n\n".join(sql_blocks) + "\n")
    JSON_OUT.write_text(json.dumps(
        {"generated": date.today().isoformat(),
         "note": "Live enum values exported from Postgres (decision #35). Semantic "
                 "definitions & tagging rules: taxonomy.md. Managed via the Curation "
                 "Studio; regenerate with db/tools/export_taxonomy.py.",
         "families": data}, ensure_ascii=False, indent=1) + "\n")
    print(f"exported {sum(len(v) for v in data.values())} values across {len(data)} families "
          f"→ {SQL_OUT.relative_to(ROOT)} + {JSON_OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
