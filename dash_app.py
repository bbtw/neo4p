from dash import Dash, html, dcc, Output, Input
import dash_cytoscape as cyto
import requests
import os

API_BASE = os.getenv("API_BASE", "http://fastapi:8000/api")

app = Dash(__name__)

app.layout = html.Div([
    dcc.Location(id="url"),
    html.H2("Graph Viewer"),
    dcc.Store(id="graph-elements"),
    cyto.Cytoscape(
        id='graph-view',
        layout={"name": "cose"},
        style={"width": "100%", "height": "500px"},
        elements=[],  # will be populated dynamically
        stylesheet=[
            {"selector": 'node', "style": {"label": "data(label)", "font-size": 12}},
            {"selector": '.need', "style": {"background-color": "#4CAF50"}},
            {"selector": '.subneed', "style": {"background-color": "#2196F3"}},
            {"selector": '.task', "style": {"background-color": "#FF9800"}},
            {"selector": 'edge', "style": {
                "curve-style": "bezier", "target-arrow-shape": "triangle",
                "label": "data(label)", "font-size": 10
            }}
        ]
    )
])

# Fetch graph from FastAPI when page loads
@app.callback(
    Output("graph-elements", "data"),
    Input("url", "pathname")
)
def load_graph(_):
    try:
        res = requests.get(f"{API_BASE}/graph")
        return res.json() if res.ok else []
    except Exception as e:
        print(f"Error fetching graph: {e}")
        return []

# Push data into Cytoscape
app.clientside_callback(
    """
    function(elements) {
        return elements || [];
    }
    """,
    Output("graph-view", "elements"),
    Input("graph-elements", "data")
)

if __name__ == "__main__":
    app.run_server(host="0.0.0.0", port=8050, debug=True)
