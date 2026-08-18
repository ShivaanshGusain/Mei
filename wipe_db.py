from Mei.memory.graph.connection import get_kuzu_connection

conn = get_kuzu_connection()
# This wipes all nodes and edges in the graph
conn.execute("MATCH (a)-[r]->(b) DELETE r")
conn.execute("MATCH (n) DELETE n")
print("Kuzu database wiped successfully!")