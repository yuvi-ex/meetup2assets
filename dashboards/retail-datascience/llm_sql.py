"""Optional LLM-backed text-to-SQL, with a guard the model cannot talk past.

The key is resolved in two steps, environment first:

  1. ANTHROPIC_API_KEY in the process environment.
  2. ~/.exasol-starter-kit/credentials/anthropic_api_key, owner-readable only.

Step 2 exists because dash-server is started by a launchd boot entry with no
EnvironmentVariables, so a key exported in a login shell never reaches it. The
kit already resolves the database password this way. The key is never written
to a file by this module, never logged, and never placed in app source.

With no key present the caller falls back to the deterministic template engine
and the panel still works, so this module is optional by construction.

Every candidate query, whoever wrote it, must survive the guard below before it
reaches the database. The database user is read-only, which is the floor; the
guard is what stops expensive, sprawling or off-schema queries above it.
"""
import os, re, stat

MODEL = "claude-opus-5"
KEY_FILE = os.path.join(os.path.expanduser("~"), ".exasol-starter-kit",
                        "credentials", "anthropic_api_key")
FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|"
    r"commit|rollback|call|execute|import|export)\b", re.I)

SYSTEM = (
    "You translate a business question into exactly one Exasol SELECT statement. "
    "Return SQL only: no prose, no code fence, no semicolon, no comments."
)


def read_key():
    """(key, error). Never returns the key in the error, and never logs it."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key.strip(), None
    try:
        info = os.stat(KEY_FILE)
    except OSError:
        return None, None                      # not configured; not an error
    if info.st_mode & (stat.S_IRGRP | stat.S_IROTH):
        return None, (f"{KEY_FILE} is readable by other users. "
                      f"Run: chmod 600 {KEY_FILE}")
    try:
        with open(KEY_FILE) as handle:
            key = handle.read().strip()
    except OSError as exc:
        return None, f"could not read the key file: {exc.strerror}"
    return (key, None) if key else (None, "the key file is empty")


def guard(sql, schema, table, row_cap=500):
    """Return (safe_sql, error). Rejects anything that is not one bounded SELECT."""
    if not sql or not sql.strip():
        return None, "empty query"
    text = sql.strip().rstrip(";").strip()
    if ";" in text:
        return None, "rejected: more than one statement"
    if "--" in text or "/*" in text:
        return None, "rejected: comments can hide a second statement"
    if not re.match(r"^(select|with)\b", text, re.I):
        return None, "rejected: only SELECT is allowed"
    if FORBIDDEN.search(text):
        return None, "rejected: contains a data- or schema-modifying keyword"
    sources = re.findall(r'\b(?:from|join)\s+"([A-Za-z0-9_ ]+)"\s*\.\s*"([A-Za-z0-9_ ]+)"',
                         text, re.I)
    unqualified = re.findall(r'\b(?:from|join)\s+(?!")([A-Za-z0-9_]+)', text, re.I)
    if not sources:
        return None, "rejected: every table must be written as \"SCHEMA\".\"TABLE\""
    for ref_schema, _ in sources:
        if ref_schema.upper() != schema.upper():
            return None, f"rejected: reads from schema {ref_schema}, outside this dashboard"
    if unqualified:
        return None, (f"rejected: unqualified table reference "
                      f"{unqualified[0]}; every table must name its schema")
    return f"SELECT * FROM ({text}) LIMIT {row_cap}", None


def propose_sql(question, schema, table, columns, joins=None):
    """Ask the model for SQL. Returns (sql, error). Not configured -> (None, None)."""
    key, key_error = read_key()
    if key_error:
        return None, key_error
    if not key:
        return None, None
    try:
        import anthropic
    except ImportError:
        return None, ("the anthropic package is not installed in this app "
                      "environment; add it to requirements.txt and redeploy")

    catalog = "\n".join(
        f'  "{c.get("table", table)}"."{c["name"]}"  {c["role"]}  {c["additivity"]}'
        for c in columns)
    join_text = ("\nAuthoritative facts about this table — follow these exactly:\n  "
                 + "\n  ".join(joins)) if joins else ""
    prompt = (
        f'Fact table: "{schema}"."{table}" (alias it as "{table}").\n'
        f"Columns (table.name, semantic role, additivity):\n"
        f"{catalog}{join_text}\n\nRules:\n"
        f'- Schema-qualify every table as "{schema}"."TABLE", aliased to its own name.\n'
        f"- Quote every identifier with double quotes.\n"
        f"- NEVER SUM a column whose additivity is non_additive, attribute or "
        f"count_only. Average those instead.\n"
        f"- A semi_additive column may not be summed across time.\n\n"
        f"Question: {question}")

    client = anthropic.Anthropic(api_key=key)
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError:
        return None, "the model is rate limited; try again shortly"
    except anthropic.AuthenticationError:
        return None, "the API key was rejected"
    except anthropic.APIStatusError as exc:
        return None, f"model call failed (HTTP {exc.status_code})"
    except anthropic.APIConnectionError:
        return None, "could not reach the API; check the network"

    # A refusal returns HTTP 200 with no usable content: check before reading it.
    if getattr(response, "stop_reason", None) == "refusal":
        return None, "the model declined to answer this question"
    text = "".join(block.text for block in response.content
                   if getattr(block, "type", None) == "text")
    text = re.sub(r"^```(?:sql)?|```$", "", text.strip(), flags=re.M).strip()
    return (text, None) if text else (None, "the model returned no SQL")
