import pytest
from Mei.memory.graph.connection import KuzuConnection
from Mei.memory.graph.schema import apply_schema, create_vector_index

def test_schema_idempotency_and_tables(tmp_path, capsys):
    """
    Test: Call apply_schema() twice on a fresh DB — assert no errors.
    Query CALL SHOW_TABLES() and assert all 8 node tables are present.
    Assert create_vector_index() is idempotent.
    """
    db_path = str(tmp_path / "schema_test_db")
    conn = KuzuConnection(db_path)
    
    try:
        # 1. Apply schema the first time
        apply_schema(conn)
        
        # Capture the stdout to verify the Demo requirement (prints on creation)
        captured_first = capsys.readouterr().out
        assert "Created table: Goal" in captured_first
        assert "Created table: AppLibrary" in captured_first
        
        # 2. Apply schema a second time (asserts idempotency; should not raise errors)
        apply_schema(conn)
        
        # Capture stdout again to verify Demo requirement (prints nothing second time)
        captured_second = capsys.readouterr().out
        assert captured_second == ""  # No new tables created, prints nothing
        
        # 3. Assert all 8 required node tables are present
        tables_result = conn.execute("CALL show_tables() RETURN *")
        created_table_names = {row["name"] for row in tables_result}
        
        expected_node_tables = {
            "Goal", "Action", "Observation", "Entity", 
            "Session", "ElementCache", "AppLibrary", "Preference"
        }
        
        for expected in expected_node_tables:
            assert expected in created_table_names, f"Missing table: {expected}"
            
        # 4. Assert HNSW Vector Index creation is idempotent
        create_vector_index(conn)
        
        # If the above succeeded, a second run must be safely caught by the except block
        create_vector_index(conn) 

    finally:
        conn.close()