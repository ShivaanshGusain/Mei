import json
import os
import tempfile
import webbrowser
from ..memory.graph.connection import get_kuzu_connection

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Mei Memory Graph</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body { margin: 0; padding: 0; overflow: hidden; font-family: sans-serif; background-color: #f4f4f9; }
        #graph { width: 100vw; height: 100vh; }
        .node circle { stroke: #fff; stroke-width: 2px; }
        .node text { font-size: 12px; pointer-events: none; }
        .link { stroke: #999; stroke-opacity: 0.6; }
        .link-label { font-size: 10px; fill: #666; }
        .tooltip { position: absolute; background: white; padding: 10px; border: 1px solid #ccc; border-radius: 5px; pointer-events: none; opacity: 0; box-shadow: 0 4px 6px rgba(0,0,0,0.1); font-size: 12px; max-width: 300px; word-wrap: break-word; }
    </style>
</head>
<body>
    <div id="graph"></div>
    <div id="tooltip" class="tooltip"></div>
    <script>
        const data = GRAPH_DATA_HERE;

        const width = window.innerWidth;
        const height = window.innerHeight;

        const svg = d3.select("#graph").append("svg")
            .attr("width", width)
            .attr("height", height)
            .call(d3.zoom().on("zoom", function (event) {
                svg.attr("transform", event.transform);
            }))
            .append("g");

        const simulation = d3.forceSimulation(data.nodes)
            .force("link", d3.forceLink(data.links).id(d => d.id).distance(150))
            .force("charge", d3.forceManyBody().strength(-300))
            .force("center", d3.forceCenter(width / 2, height / 2));

        const link = svg.append("g")
            .selectAll("line")
            .data(data.links)
            .enter().append("line")
            .attr("class", "link")
            .attr("stroke-width", 2);

        const linkLabel = svg.append("g")
            .selectAll("text")
            .data(data.links)
            .enter().append("text")
            .attr("class", "link-label")
            .attr("dy", -5)
            .attr("text-anchor", "middle")
            .text(d => d.label);

        const node = svg.append("g")
            .selectAll(".node")
            .data(data.nodes)
            .enter().append("g")
            .attr("class", "node")
            .call(d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended));

        node.append("circle")
            .attr("r", d => d.size || 10)
            .attr("fill", d => d.color);

        node.append("text")
            .attr("dx", 15)
            .attr("dy", 4)
            .text(d => d.label);

        const tooltip = d3.select("#tooltip");

        node.on("mouseover", function(event, d) {
            tooltip.transition().duration(200).style("opacity", .9);
            tooltip.html(d.details)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 28) + "px");
        })
        .on("mouseout", function(d) {
            tooltip.transition().duration(500).style("opacity", 0);
        });

        simulation.on("tick", () => {
            link
                .attr("x1", d => d.source.x)
                .attr("y1", d => d.source.y)
                .attr("x2", d => d.target.x)
                .attr("y2", d => d.target.y);
            
            linkLabel
                .attr("x", d => (d.source.x + d.target.x) / 2)
                .attr("y", d => (d.source.y + d.target.y) / 2);

            node
                .attr("transform", d => `translate(${d.x},${d.y})`);
        });

        function dragstarted(event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
        }

        function dragged(event, d) {
            d.fx = event.x;
            d.fy = event.y;
        }

        function dragended(event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
        }
    </script>
</body>
</html>
"""

def export_graph():
    conn = get_kuzu_connection()
    nodes = []
    links = []

    try:
        # Sessions
        for row in conn.execute("MATCH (s:Session) RETURN s.id AS id"):
            nodes.append({
                "id": row["id"],
                "label": "Session",
                "group": "Session",
                "color": "#999999",
                "size": 15,
                "details": f"<b>Session</b><br>ID: {row['id']}"
            })

        # Goals
        for row in conn.execute("MATCH (g:Goal) RETURN g.id AS id, g.raw_command AS cmd, g.success_count AS sc, g.fail_count AS fc"):
            sc = row.get("sc") or 0
            fc = row.get("fc") or 0
            nodes.append({
                "id": row["id"],
                "label": row["cmd"],
                "group": "Goal",
                "color": "#1f77b4",
                "size": 12 + min(sc * 2, 20),
                "details": f"<b>Goal</b><br>Command: {row['cmd']}<br>Successes: {sc}<br>Fails: {fc}"
            })

        # Actions
        for row in conn.execute("MATCH (a:Action) RETURN a.id AS id, a.tool_name AS tool, a.parameters_json AS params"):
            nodes.append({
                "id": row["id"],
                "label": row["tool"],
                "group": "Action",
                "color": "#2ca02c",
                "size": 10,
                "details": f"<b>Action</b><br>Tool: {row['tool']}<br>Params: {row['params']}"
            })
            
        # Observations
        for row in conn.execute("MATCH (o:Observation) RETURN o.id AS id, o.success AS success, o.error AS error"):
            err = row.get("error") or "None"
            nodes.append({
                "id": row["id"],
                "label": "Obs",
                "group": "Observation",
                "color": "#ff7f0e" if row["success"] else "#d62728",
                "size": 8,
                "details": f"<b>Observation</b><br>Success: {row['success']}<br>Error: {err}"
            })

        # Relationships
        rels = [
            ("Goal", "ACHIEVED_BY", "Action"),
            ("Action", "NEXT_ACTION", "Action"),
            ("Action", "RESULTED_IN", "Observation"),
            ("Goal", "PART_OF_SESSION", "Session")
        ]
        
        for src_type, rel, tgt_type in rels:
            query = f"MATCH (s:{src_type})-[r:{rel}]->(t:{tgt_type}) RETURN s.id AS src, t.id AS tgt"
            for row in conn.execute(query):
                links.append({
                    "source": row["src"],
                    "target": row["tgt"],
                    "label": rel
                })
    except Exception as e:
        print(f"Graph query failed (perhaps db is empty): {e}")

    data = {"nodes": nodes, "links": links}
    html_content = HTML_TEMPLATE.replace("GRAPH_DATA_HERE", json.dumps(data))

    temp_file = tempfile.mktemp(suffix=".html", prefix="mei_graph_")
    with open(temp_file, "w", encoding="utf-8") as f:
        f.write(html_content)

    webbrowser.open(f"file://{temp_file}")
    return temp_file
