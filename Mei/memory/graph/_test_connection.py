import os
import shutil
import pytest
from unittest.mock import patch, MagicMock

# Import the module so we can access _instance directly for resetting state
import Mei.memory.graph.connection as connection_module
from Mei.memory.graph.connection import KuzuConnection, get_kuzu_connection


# import connection as connection_module
# from connection import KuzuConnection, get_kuzu_connection
@pytest.fixture(autouse=True)
def reset_singleton():
    """Ensure the singleton is reset before and after each test."""
    connection_module._instance = None
    yield
    if connection_module._instance is not None:
        connection_module._instance.close()
    connection_module._instance = None

def test_kuzu_connection_execute(tmp_path):
    """
    Test: Instantiate on a temp path, call execute("RETURN 1 AS x"), 
    assert result is [{"x": 1}].
    """
    db_path = str(tmp_path / "temp_kuzu_db")
    
    # 1. Instantiate on a temp path
    conn = KuzuConnection(db_path)
    
    # 2. Call execute
    result = conn.execute("RETURN 1 AS x")
    
    # 3. Assert result format and value
    assert result == [{"x": 1}]
    
    # Clean up
    conn.close()

@patch("Mei.memory.graph.connection.get_config")
def test_kuzu_connection_singleton(mock_get_config):
    """
    Test: Call get_kuzu_connection() twice and assert is identity. 
    Confirm data/kuzu_memory/ is created.
    """
    test_db_path = "data/kuzu_memory"
    
    os.makedirs("data", exist_ok=True)
    
    if os.path.exists(test_db_path):
        if os.path.isdir(test_db_path):
            shutil.rmtree(test_db_path)
        else:
            os.remove(test_db_path)
            
    mock_config = MagicMock()
    mock_config.kuzu.database_path = test_db_path
    mock_get_config.return_value = mock_config

    try:
        # Call get_kuzu_connection() twice
        conn1 = get_kuzu_connection()
        conn2 = get_kuzu_connection()
        
        # Assert identity 
        assert conn1 is conn2
        
        # Confirm Kuzu created the database artifact at the path
        assert os.path.exists(test_db_path), f"Path {test_db_path} was not created by Kuzu!"
        
    finally:
        if connection_module._instance:
            connection_module._instance.close()
            connection_module._instance = None
            
        # Clean up after test passes
        if os.path.exists(test_db_path):
            if os.path.isdir(test_db_path):
                shutil.rmtree(test_db_path)
            else:
                os.remove(test_db_path)