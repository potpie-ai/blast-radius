import sqlite3

codebase_map = f'./.momentum/momentum.db'

from simple_graph_sqlite import database as graph


def find_entry_points( identifiers, directory):
    all_inbound_nodes = set()
    codebase_map = f'{directory}/.momentum/momentum.db'
    for identifier in identifiers:
        traversal_result = graph.traverse(codebase_map, identifier, neighbors_fn=graph.find_inbound_neighbors)
        all_inbound_nodes.update(traversal_result)

    entry_points = set()
    for node in all_inbound_nodes:

        inbound_to_node = set(graph.traverse(codebase_map, node, neighbors_fn=graph.find_inbound_neighbors))
        if len(inbound_to_node)==1 and inbound_to_node == {node}:
            entry_points.add(node)

    return entry_points


def find_paths(entry_points, directory):
    # Connect to the endpoints database
    conn_endpoints = sqlite3.connect(f'{directory}/.momentum/momentum.db')
    endpoints_cursor = conn_endpoints.cursor()
    
    paths = {}
    
    for entry_point in entry_points:
        endpoints_cursor.execute("SELECT path FROM endpoints WHERE identifier = ?", (entry_point,))
        path = endpoints_cursor.fetchone()
        if path:
            paths[entry_point] = path[0]
    
    conn_endpoints.close()
    return paths

def get_paths_from_identifiers(identifiers, temp_dir):
    entry_points = find_entry_points(identifiers,temp_dir)
    paths = find_paths(entry_points, temp_dir)
    grouped_by_filename = {}
    for entry_point, path in paths.items():
        file, function = entry_point.split(':')
        if file not in grouped_by_filename:
            grouped_by_filename[file] = []
        grouped_by_filename[file].append({"entryPoint": path, "identifier": entry_point})
    return grouped_by_filename
