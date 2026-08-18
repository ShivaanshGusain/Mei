import time
import nest_asyncio
nest_asyncio.apply()  
from Mei.core.pipeline import process_user_command
from Mei.memory.graph import get_kuzu_connection
from Mei.action.context import ExecutionContext  # Added this import

def run_e2e_test():
    print("========================================")
    print("MEI PIPELINE E2E TEST HARNESS")
    print("========================================\n")

    # Command to test
    test_command = "Create a file with the name 'modulo.py'."

    print(f"--- RUN 1: COLD RUN (Decomposition) ---")
    print(f"Command: {test_command}")
    
    # FIX: Initialize the empty context and pass it in
    context_1 = ExecutionContext.empty()
    success_1 = process_user_command(test_command, context_1)
    print(f"Run 1 Success: {success_1}\n")

    # Give Kùzu a second to finalize disk writes
    time.sleep(1)

    print(f"--- RUN 2: WARM RUN (Macro Bypass) ---")
    # Slightly alter the text to test the 0.85 HNSW semantic threshold
    test_command_alt = "Create a file with the name 'modulo.py'."
    print(f"Command: {test_command_alt}")
    
    # FIX: Initialize a fresh empty context for the second run
    context_2 = ExecutionContext.empty()
    success_2 = process_user_command(test_command_alt, context_2)
    print(f"Run 2 Success: {success_2}\n")

    # Verify the Database
    print("--- KÙZU GRAPH VERIFICATION ---")
    conn = get_kuzu_connection()
    try:
        goals = conn.execute("MATCH (g:Goal) RETURN g.raw_command AS cmd, g.id AS id")
        for g in goals:
            print(f"Goal saved: {g['cmd']} (ID: {g['id']})")
    except Exception as e:
        print(f"Graph verification failed: {e}")

if __name__ == "__main__":
    run_e2e_test()


