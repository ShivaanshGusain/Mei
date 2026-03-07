import sqlite3

def check_db():
    print("🧠 Inspecting Mei's Memory...\n")
    try:
        conn = sqlite3.connect("data/memory.db")
        cursor = conn.cursor()
        
        # Pulling use_count, success_count, and failure_count
        cursor.execute("""
            SELECT intent_pattern, plan_strategy, use_count, success_count, failure_count 
            FROM plan_cache
            ORDER BY use_count DESC
        """)
        plans = cursor.fetchall()
        print(f"--- CACHED PLANS ({len(plans)}) ---")
        for p in plans:
            # p[0]=pattern, p[1]=strategy, p[2]=uses, p[3]=success, p[4]=fails
            print(f"Pattern: {p[0]:<18} | Uses: {p[2]} (✅ {p[3]} / ❌ {p[4]}) | Strategy: {p[1]}")
            
        print("\n")
        
        # Check task history
        cursor.execute("SELECT raw_command, success, duration_ms FROM task_executions ORDER BY timestamp DESC LIMIT 5")
        tasks = cursor.fetchall()
        print(f"--- LAST 5 TASKS ---")
        for t in tasks:
            status = "✅ Success" if t[1] else "❌ Failed "
            print(f"{status} | {t[2]:>7.0f}ms | {t[0]}")
            
        conn.close()
    except Exception as e:
        print(f"Failed to read database: {e}")

if __name__ == "__main__":
    check_db()