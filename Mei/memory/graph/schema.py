KUZU_SCHEMA = [
    """
    CREATE NODE TABLE IF NOT EXISTS Goal (
    id                  STRING,
    raw_command         STRING,
    action              STRING,
    target              STRING,
    session_id          STRING,
    created_at          STRING,
    embedding           FLOAT[384],
    stability_score     DOUBLE,
    success_count       INT64 DEFAULT 0,
    fail_count          INT64 DEFAULT 0,
    verified_success_count INT64 DEFAULT 0,
    verified_total_count   INT64 DEFAULT 0,
    verified_reliability   DOUBLE DEFAULT 0.5,
    last_executed_at    STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS SchemaVersion (
    id                  STRING,
    version             INT64,
    applied_at          STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Action (
    id                  STRING,
    tool_name           STRING,
    parameters_json     STRING,
    command             STRING,
    cwd                 STRING,
    background          BOOLEAN,
    started_at          STRING,
    completed_at        STRING,
    duration_ms         DOUBLE,
    method_used         STRING,
    step_description    STRING,
    step_domain         STRING,
    step_expected_output STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Observation (
    id                  STRING,
    success             BOOLEAN,
    error               STRING,
    foreground_window   STRING,
    result_data_json    STRING,
    created_at          STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Entity (
    id                  STRING,
    name                STRING,
    canonical_name      STRING,
    entity_type         STRING,
    resolution          STRING,
    confidence          DOUBLE,
    source_app          STRING,
    created_at          STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Session (
    id                  STRING,
    started_at          STRING,
    ended_at            STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS ElementCache (
    id                  STRING,
    element_query       STRING,
    app_name            STRING,
    window_pattern      STRING,
    center_x            INT64,
    center_y            INT64,
    bounding_box_x      INT64,
    bounding_box_y      INT64,
    bounding_box_w      INT64,
    bounding_box_h      INT64,
    source              STRING,
    element_type        STRING,
    automation_id       STRING,
    element_name        STRING,
    hit_count           INT64,
    confidence          DOUBLE,
    is_valid            BOOLEAN,
    last_hit            STRING,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS AppLibrary (
    id                  STRING,
    display_name        STRING,
    executable_name     STRING,
    executable_path     STRING,
    category            STRING,
    launch_method       STRING,
    is_available        BOOLEAN,
    PRIMARY KEY (id))
    """,
    """
    CREATE NODE TABLE IF NOT EXISTS Preference (
    id              STRING,
    pref_key        STRING,
    pref_value      STRING,
    value_type      STRING,
    category        STRING,
    confidence      DOUBLE,
    is_explicit     BOOLEAN,
    learned_at      STRING,
    PRIMARY KEY (id))
    """,
    "CREATE REL TABLE IF NOT EXISTS ACHIEVED_BY ( FROM Goal TO Action, execution_id STRING)",
    "CREATE REL TABLE IF NOT EXISTS NEXT_ACTION ( FROM Action TO Action, wait_ms DOUBLE, condition STRING)",
    "CREATE REL TABLE IF NOT EXISTS RESULTED_IN ( FROM Action TO Observation)",
    "CREATE REL TABLE IF NOT EXISTS REQUIRES (From Goal TO Entity, role STRING)",
    "CREATE REL TABLE IF NOT EXISTS PART_OF_SESSION ( FROM Goal TO Session)",
]

def apply_schema(conn):
    """Executes the KUZU_SCHEMA and prints names of newly created tables."""
    for query in KUZU_SCHEMA:
        tables_before = {row["name"] for row in conn.execute("CALL show_tables() RETURN *")}

        conn.execute(query)

        tables_after = {row["name"] for row in conn.execute("CALL show_tables() RETURN *")}
        new_tables = tables_after - tables_before

        for table in new_tables:
            print(f"Created table: {table}")

    _migrate_goal_columns(conn)


def _existing_goal_columns(conn) -> set:
    """Introspect Goal's current columns so migration can be a clean skip
    rather than a blind try/except swallow. Falls back to an empty set (which
    just means every ALTER below gets attempted, each still individually
    guarded) if this Kuzu version's introspection call differs."""
    try:
        rows = conn.execute("CALL TABLE_INFO('Goal') RETURN *")
        return {row.get("name") for row in rows if row.get("name")}
    except Exception:
        return set()


def _migrate_goal_columns(conn):
    """Best-effort migration for databases created before goal-level
    verification tracking existed. CREATE TABLE IF NOT EXISTS above won't add
    columns to an already-existing Goal table, so add them explicitly here."""
    existing = _existing_goal_columns(conn)
    for column, col_type, default in (
        ("verified_success_count", "INT64", "0"),
        ("verified_total_count", "INT64", "0"),
        ("verified_reliability", "DOUBLE", "0.5"),
    ):
        if column in existing:
            continue
        try:
            conn.execute(f"ALTER TABLE Goal ADD {column} {col_type} DEFAULT {default}")
            print(f"Migrated Goal table: added {column}")
        except Exception as e:
            print(f"[Schema] Could not add column '{column}' "
                  f"(may already exist, or this Kuzu version's ALTER syntax differs): {e}")


def create_vector_index(conn):
    """Creates the HNSW index on the Goal embedding safely (idempotent)."""
    try:
        conn.execute("CALL CREATE_VECTOR_INDEX('Goal', 'goal_hnsw', 'embedding')")
        print("Created vector index: goal_hnsw")
    except Exception:
        pass