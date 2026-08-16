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
id                      STRING,
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
def create_vector_index(conn):
    """Creates the HNSW index on the Goal embedding safely (idempotent)."""
    try:
        conn.execute("CALL CREATE_VECTOR_INDEX('Goal', 'goal_hnsw', 'embedding')")
        print("Created vector index: goal_hnsw")
    except Exception:
        pass