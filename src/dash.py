


from dash import Dash, html, dcc, Input, Output, State, ctx, ALL
import dash_bootstrap_components as dbc
import dash_cytoscape as cyto
import requests

API_BASE = "http://localhost:8000/api"

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

# --- Modal UI components ---
modal = html.Div([
    dbc.Modal([
        dbc.ModalHeader("Create Relationship"),
        dbc.ModalBody([
            html.Div(id="modal-node-pair"),
            dcc.Dropdown(id="rel-type-dropdown", placeholder="Select relationship type"),
        ]),
        dbc.ModalFooter([
            dbc.Button("Create", id="create-rel-btn", color="primary"),
            dbc.Button("Cancel", id="cancel-rel-btn", className="ms-2", color="secondary")
        ])
    ], id="rel-modal", is_open=False)
])

app.layout = dbc.Container([
    html.H2("Graph UI with Relationship Builder"),
    html.Hr(),
    cyto.Cytoscape(
        id='graph-view',
        layout={"name": "cose"},
        style={"width": "100%", "height": "500px"},
        elements=[],
        stylesheet=[
            {"selector": 'node', "style": {"label": "data(label)", "font-size": 12}},
            {"selector": '.need', "style": {"background-color": "#4CAF50"}},
            {"selector": '.subneed', "style": {"background-color": "#2196F3"}},
            {"selector": '.task', "style": {"background-color": "#FF9800"}},
            {"selector": 'edge', "style": {"curve-style": "bezier", "target-arrow-shape": "triangle", "label": "data(label)", "font-size": 10}}
        ],
        userPanningEnabled=True,
        userZoomingEnabled=True,
        boxSelectionEnabled=True,
        multiple=True
    ),
    html.Div(id="node-info"),
    modal
])

# Store for selected nodes
selected_nodes = []

@app.callback(
    Output("graph-view", "elements"),
    Input("graph-view", "tapNode"),
    prevent_initial_call=True
)
def record_selection(tapNode):
    if tapNode and tapNode['data']['id'] not in selected_nodes:
        selected_nodes.append(tapNode['data']['id'])
    if len(selected_nodes) == 2:
        return dash.no_update  # Wait for modal open
    res = requests.get(f"{API_BASE}/graph")
    return res.json() if res.ok else []

@app.callback(
    Output("rel-type-dropdown", "options"),
    Input("rel-modal", "is_open")
)
def load_dropdown(is_open):
    if not is_open:
        return []
    res = requests.get(f"{API_BASE}/relationship-types")
    return res.json() if res.ok else []

@app.callback(
    Output("modal-node-pair", "children"),
    Output("rel-modal", "is_open"),
    Input("graph-view", "elements"),
    Input("cancel-rel-btn", "n_clicks"),
    Input("create-rel-btn", "n_clicks"),
    State("rel-type-dropdown", "value")
)
def manage_modal(_, cancel_click, create_click, rel_type):
    trigger = ctx.triggered_id
    if trigger == "cancel-rel-btn" or (trigger == "create-rel-btn" and not rel_type):
        selected_nodes.clear()
        return "", False
    if trigger == "create-rel-btn" and rel_type and len(selected_nodes) == 2:
        requests.post(f"{API_BASE}/relationships", json={
            "source": selected_nodes[0],
            "target": selected_nodes[1],
            "rel_type": rel_type
        })
        selected_nodes.clear()
        return "", False
    if len(selected_nodes) == 2:
        return f"From: {selected_nodes[0]} → To: {selected_nodes[1]}", True
    return "", False

@app.callback(
    Output("graph-view", "elements", allow_duplicate=True),
    Input("rel-modal", "is_open"),
    prevent_initial_call="initial_duplicate"
)
def refresh_graph(_):
    res = requests.get(f"{API_BASE}/graph")
    return res.json() if res.ok else []

if __name__ == "__main__":
    app.run_server(debug=True)
