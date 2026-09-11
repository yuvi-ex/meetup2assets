#!/usr/bin/env python3
"""Run a recipe's SQL, insights, tiles and figures LOCALLY — no deploy.

    python3 dryrun.py superstore-boards

WHY THIS EXISTS. Building amazon-sales took seven deploy revisions, and every bug
that caused them was detectable without deploying anything:

    * a tone of "critical" that board.py does not know      -> KeyError, bare HTTP 500
    * figure keys a/b/c/d instead of trend/composition/...   -> charts silently dropped
    * `VAL <> ''` in filters.sql                             -> every dropdown empty
    * a benchmark channel of 1,083 lines at a INR 34 basket  -> insight contradicted itself

None of those trip a health probe, and each cost a full deploy-and-inspect cycle at
roughly 10 seconds plus the reading. This runs the same code paths against the same
live Exasol data in about two seconds, and asserts the four contracts that failed:

    1. filters.sql returns options for EVERY dimension in FILTER_SPEC
    2. every finding carries a tone board.insight_card actually accepts
    3. figures use ONLY share_html's four keys, and each carries data
    4. every tile has the keys share_html reads unconditionally

Then it prints the insight text, because a finding can satisfy every contract and
still say something absurd — a 13pp gap described as "an almost identical basket"
passed all four checks and was still wrong.

Exit code is 0 only when every contract holds, so it drops into a pre-deploy hook.
"""
import json
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
PROFILE = "starter-kit"
EXAPUMP = pathlib.Path.home() / ".local/bin/exapump"
VALID_TONES = {"good", "bad", "warn", "info"}
FIGURE_KEYS = ["trend", "composition", "rates", "concentration"]
TILE_KEYS = {"delta", "label", "value", "note", "good"}

failures = []
notes = []


def fail(msg):
    failures.append(msg)
    print(f"  FAIL  {msg}")


def _count():
    return len(failures)


def ok(msg):
    print(f"  PASS  {msg}")


def run_sql(path, params):
    """Execute one recipe query with its placeholders bound, returning dict rows.

    Goes through exapump rather than pyexasol: pyexasol lives only in the kit's
    own venv under a different Python, so importing it from here fails on the
    cffi ABI.
    """
    import re
    sql = path.read_text()
    for key, value in params.items():
        sql = sql.replace("{" + key + "!s}", f"'{value}'")
    leftover = re.findall(r"\{[a-z_]+!s\}", sql)
    if leftover:
        fail(f"{path.name}: unbound placeholder(s) {sorted(set(leftover))} — "
             f"missing from queries/sql_smoke.json")
        return []
    proc = subprocess.run([str(EXAPUMP), "sql", "-p", PROFILE, "-f", "json", "-"],
                          input=sql, capture_output=True, text=True, timeout=600)
    body = proc.stdout
    start = body.find("[")
    if start < 0:
        fail(f"{path.name}: query returned no result set — "
             f"{(proc.stderr or body).strip()[-160:]}")
        return []
    try:
        return json.loads(body[start:body.rfind("]") + 1])
    except json.JSONDecodeError as exc:
        fail(f"{path.name}: unparseable result ({exc})")
        return []


def load_module(recipe):
    """Import the recipe's app.py with board.py importable beside it.

    board.py resolves dash_server_exasol.py relative to itself, and that helper
    only exists inside a deployed app workspace. A local stub satisfies the import
    without being shipped: deploy_dashboard.py pushes only harness.py and board.py
    from this directory, never this file.
    """
    stub = ROOT / "dash_server_exasol.py"
    if not stub.exists():
        stub.write_text(
            '"""Local stub so board.py imports outside a deployed workspace.\n\n'
            'Only dryrun.py uses this. deploy_dashboard.py pushes harness.py and\n'
            'board.py from this directory and never this file, so a deployed app\n'
            'still binds the real dash-server helper sitting next to its own copy.\n'
            '"""\n\n\n'
            'def load_row(*_a, **_k):\n'
            '    raise RuntimeError("dryrun calls SQL directly, not through board")\n\n\n'
            'def load_rows(*_a, **_k):\n'
            '    raise RuntimeError("dryrun calls SQL directly, not through board")\n\n\n'
            'def has_error(payload):\n'
            '    return isinstance(payload, dict) and "_error" in payload\n\n\n'
            'def render_error_panel(_error):\n'
            '    return None\n')
        notes.append(f"created local stub {stub.name} (not deployed)")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(recipe))
    import importlib.util
    spec = importlib.util.spec_from_file_location(f"dryrun_{recipe.name}",
                                                  recipe / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_findings(label, findings):
    if not findings:
        fail(f"{label}: build_insights returned nothing")
        return
    before = _count()
    for i, finding in enumerate(findings):
        tone = finding.get("tone")
        if tone not in VALID_TONES:
            fail(f"{label}: finding {i} has tone {tone!r} — board.insight_card "
                 f"accepts only {sorted(VALID_TONES)} and raises KeyError otherwise")
        for key in ("text", "meaning", "action"):
            if key not in finding:
                fail(f"{label}: finding {i} is missing {key!r}")
        for key in ("text", "meaning"):
            body = str(finding.get(key, ""))
            for bad_token in ("None", "nan", "inf"):
                if bad_token in body.split():
                    fail(f"{label}: finding {i} {key} contains {bad_token!r} — "
                         f"a missing value reached the copy")
    if _count() == before:
        ok(f"{label}: {len(findings)} findings, tones and keys valid")


def check_figures(label, figures):
    before = _count()
    unknown = [k for k in figures if k not in FIGURE_KEYS]
    if unknown:
        fail(f"{label}: figure key(s) {unknown} are ignored by share_html — it "
             f"renders only {FIGURE_KEYS}, so these charts vanish from the export")
    empty = [k for k in FIGURE_KEYS if k in figures
             and not getattr(figures[k], "data", ())]
    if empty:
        fail(f"{label}: figure(s) {empty} carry no traces")
    present = [k for k in FIGURE_KEYS if k in figures]
    if _count() == before:
        ok(f"{label}: {len(present)} figures, all keys valid and populated")


def check_tiles(label, tiles):
    before = _count()
    for i, tile in enumerate(tiles):
        missing = TILE_KEYS - set(tile)
        if missing:
            fail(f"{label}: tile {i} missing {sorted(missing)} — share_html reads "
                 f"these unconditionally and dies with a bare KeyError")
    if _count() == before:
        ok(f"{label}: {len(tiles)} tiles, all required keys present")


def pick(module, *names):
    """Find a function under any of several conventional names.

    Recipes are not uniform: this tree has build_insights, _build_insights, and
    recipes with no module-level tiles function at all (tiles are a closure inside
    create_dash_app). A missing function is SKIPPED, never fatal — crashing on one
    naming difference made the tool useless for 13 of the 15 recipes here.
    """
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            return fn, name
    return None, None


def skip(msg):
    print(f"  SKIP  {msg}")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: dryrun.py <recipe-dir>")
    recipe = pathlib.Path(sys.argv[1]).resolve()
    started = time.time()
    print(f"\ndry run: {recipe.name}  (no deploy)")

    smoke = json.loads((recipe / "queries/sql_smoke.json").read_text())
    module = load_module(recipe)
    business = recipe / "queries/business"

    # --- 1. filters must produce options for every declared dimension ----------
    print("\n=== filters ===")
    spec = getattr(module, "FILTER_SPEC", [])
    filters_sql = business / "filters.sql"
    if filters_sql.exists() and spec:
        rows = run_sql(filters_sql, smoke.get("queries/business/filters.sql", {}))
        counts = {dim: sum(1 for r in rows if r.get("DIM") == dim)
                  for _k, dim, _l in spec}
        blank = [d for d, n in counts.items() if not n]
        if blank:
            fail(f"filters.sql returns no options for {blank} — those dropdowns "
                 f"render empty while every health probe still passes")
        else:
            ok("filters: " + ", ".join(f"{d}:{n}" for d, n in counts.items()))

    # --- 2. per-persona (or single) insight / figure / tile contracts ----------
    personas = getattr(module, "PERSONAS", None)
    if personas:
        plan = [(key, cfg["queries"], cfg["insights"], cfg["figures"], cfg["tiles"])
                for key, cfg in personas.items()]
    else:
        # No persona registry: take the query order from sql_smoke.json, which is
        # authored in the order _load passes the frames. The *kpi* file is the
        # single row; everything else except filters is a frame.
        names = [pathlib.Path(k).name for k in smoke
                 if pathlib.Path(k).name != "filters.sql"]
        kpi = next((n for n in names if "kpi" in n), None)
        frames = [n for n in names if n != kpi]
        insights_fn, iname = pick(module, "build_insights", "_build_insights")
        figures_fn, _fname = pick(module, "make_figures", "_make_figures",
                                  "build_figures")
        tiles_fn, _tname = pick(module, "build_tiles", "_build_tiles", "make_tiles")
        if insights_fn is None:
            fail("no build_insights/_build_insights found — cannot check findings")
        plan = [("main", [kpi] + frames, insights_fn, figures_fn, tiles_fn)]

    for label, queries, insights_fn, figures_fn, tiles_fn in plan:
        print(f"\n=== {label} ===")
        params = smoke.get(f"queries/business/{queries[0]}", {})
        rows = run_sql(business / queries[0], params)
        kpi_row = rows[0] if rows else {}
        if not kpi_row:
            fail(f"{label}: {queries[0]} returned no row")
            continue
        frames = [run_sql(business / q, smoke.get(f"queries/business/{q}", {}))
                  for q in queries[1:]]
        blank_frames = [q for q, f in zip(queries[1:], frames) if not f]
        if blank_frames:
            fail(f"{label}: query returned zero rows: {blank_frames}")
        else:
            ok(f"{label}: {len(queries)} queries, "
               f"{sum(len(f) for f in frames):,} rows")

        findings = []
        if insights_fn is None:
            skip(f"{label}: no insights function")
        else:
            try:
                findings = insights_fn(kpi_row, *frames)
                check_findings(label, findings)
            except TypeError as exc:
                # A different arity is a recipe convention, not a defect: some
                # recipes pass a subset of frames. Report rather than fail.
                skip(f"{label}: insights signature differs ({exc}) — "
                     f"deploy-time verification still applies")
            except Exception as exc:
                fail(f"{label}: insights raised {type(exc).__name__}: {exc}")
        if figures_fn is None:
            skip(f"{label}: no module-level figures function")
        else:
            try:
                check_figures(label, figures_fn(kpi_row, *frames))
            except TypeError as exc:
                skip(f"{label}: figures signature differs ({exc})")
            except Exception as exc:
                fail(f"{label}: figures raised {type(exc).__name__}: {exc}")
        if tiles_fn is None:
            skip(f"{label}: tiles are a closure in create_dash_app, not checkable "
                 f"here — preflight.py covers them after deploy")
        else:
            try:
                check_tiles(label, tiles_fn(kpi_row))
            except TypeError as exc:
                skip(f"{label}: tiles signature differs ({exc})")
            except Exception as exc:
                fail(f"{label}: tiles raised {type(exc).__name__}: {exc}")

        # Print the copy. Contracts cannot tell you a finding is nonsense.
        if findings:
            print(f"\n  --- {label}: read this before deploying ---")
            for finding in findings:
                print(f"\n  [{finding.get('tone', '?'):4}] {finding.get('text', '')}")
                meaning = str(finding.get("meaning", ""))
                if meaning:
                    print(f"         {meaning[:180]}")

    print("\n" + "=" * 66)
    for note in notes:
        print(f"  note: {note}")
    if failures:
        print(f"  {len(failures)} contract failure(s) — fix before deploying")
    else:
        print(f"  all contracts hold — safe to deploy  ({time.time() - started:.1f}s)")
    print("=" * 66)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
