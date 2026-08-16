from Mei.memory.graph import get_kuzu_connection, get_preferences_for_prompt

def inspect():
    conn = get_kuzu_connection()
    print("=== Kùzu Memory Inspector ===\n")
    
    # Show all table node counts
    for row in conn.execute("CALL show_tables() RETURN *"):
        name = row['name']
        try:
            c = conn.execute(f"MATCH (n:{name}) RETURN count(n) AS c")[0]['c']
            print(f"  {name:<20} {c} nodes")
        except:
            print(f"  {name:<20} (rel table)")
    
    print("\n--- Last 5 Goals ---")
    for g in conn.execute(
        "MATCH (g:Goal) RETURN g.raw_command AS cmd, g.created_at AS ts "
        "ORDER BY g.created_at DESC LIMIT 5"):
        print(f"  [{g['ts'][:19]}] {g['cmd']}")
    
    print("\n--- Preferences ---")
    print(get_preferences_for_prompt() or "  (none)")

if __name__ == "__main__":
    inspect()