import os
import sqlite3
import json
from typing import Optional
from simple_graph_sqlite import database as graph
from tree_sitter import Language, Parser
import subprocess 
from tree_sitter_languages import get_parser
from pathlib import Path
import re

subprocess.run(["python", "./build/build.py"])

PY_LANGUAGE = Language('./build/my-languages.so', 'python')

# Initialize SQLite Database and Graph
parser = Parser()
parser.set_language(PY_LANGUAGE)

codebase_map = f'./.momentum/momentum.db'

class EndpointManager: 
    
    def __init__(self, directory: Optional[str] = os.getcwd(), router_prefix_file_mapping: Optional[dict] = {}):
        self.directory = directory
        self.db_path= f'{directory}/.momentum/momentum.db'
        self.router_prefix_file_mapping = router_prefix_file_mapping

    # SQLite database setup
    def setup_database(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS endpoints (
                path TEXT, 
                identifier TEXT UNIQUE,
                test_plan TEXT,
                preferences TEXT
            )
        ''')
        conn.commit()
        if conn:
            conn.close()
    
    def extract_path(self, decorator):
        # Find the position of the first opening parenthesis and the following comma
        start = decorator.find('(') + 1
        end = decorator.find(',', start)

        # Extract the string between these positions
        path = decorator[start:end].strip()

        # Remove single or double quotes
        if path.startswith(("'", '"')) and path.endswith(("'", '"')):
            path = path[1:-1]
        if path=='':
            path = '/'
        return path

    def identify_django_endpoints(self, project_path):
        parser = get_parser("python")

        endpoints = []

        # Find all urls.py files in the project
        urls_files = list(Path(project_path).rglob("urls.py"))

        for urls_file in urls_files:
            # Read the content of the urls.py file
            with open(urls_file, "r") as file:
                content = file.read()

            # Parse the urls.py file using tree-sitter
            tree = parser.parse(bytes(content, "utf8"))
            root_node = tree.root_node

            # Initialize urlpatterns list
            urlpatterns_list = []

            # Find the assignment node for the urlpatterns variable
            for node in root_node.children:
                if node.type == "expression_statement" and 'urlpatterns' in content[node.start_byte:node.end_byte]:
                    expression = node.children[0]
                    if expression.type == "assignment":
                        urlpatterns_node = expression.children[2]
                        if urlpatterns_node.type == "list":
                            urlpatterns_list.extend(urlpatterns_node.children)
                    elif expression.type == "augmented_assignment" and 'extend' in content[expression.start_byte:expression.end_byte]:
                        # Handle the case where urlpatterns is extended
                        extended_list = expression.children[2]
                        if extended_list.type == "list":
                            urlpatterns_list.extend(extended_list.children)

            # Process each URL pattern in urlpatterns_list
            for url_pattern_node in urlpatterns_list:
                if url_pattern_node.type == "call":
                    url_pattern = None
                    view_name = None
                    endpoint_name = None

                    # Find the argument list node
                    argument_list_node = None
                    for child_node in url_pattern_node.children:
                        if child_node.type == "argument_list":
                            argument_list_node = child_node
                            break

                    if argument_list_node:
                        # Iterate over the arguments in the argument list
                        for argument_node in argument_list_node.children:
                            if argument_node.type == "string":
                                url_pattern = argument_node.text.decode("utf8").strip("'\"")
                                if url_pattern == "":
                                    url_pattern = "/"
                            elif argument_node.type == "call":
                                # Find the identifier node inside the call
                                identifier_node = None
                                for child_node in argument_node.children:
                                    if child_node.type == "attribute":
                                        identifier_node = child_node
                                        break

                                if identifier_node:
                                    view_name = identifier_node.text.decode("utf8")
                            elif argument_node.type == "identifier":
                                # This handles function-based views directly referred by name
                                view_name = argument_node.text.decode("utf8")
                            elif argument_node.type == "attribute":
                                # This handles function-based views directly referred by name
                                view_name = argument_node.text.decode("utf8")

                    if url_pattern and view_name:
                        # Determine the view type (function or class-based)
                        view = view_name if not view_name.endswith("as_view") else view_name.rsplit(".", 1)[0]
                        file_path, identifier = self.resolve_called_view_name(view, str(urls_file), self.file_index, self.directory)
                        if identifier:
                            entry_point = file_path.replace(self.directory, "") + ":" + identifier
                            # Append the endpoint information to the list
                            endpoints.append(("HTTP " + url_pattern, entry_point))

        return endpoints
    # Function to parse a Python file and return FastAPI endpoint functions with additional details
    def find_endpoints_from_decorator(self, source_code, filename):
        parser = get_parser("python")
        tree = parser.parse(bytes(source_code, "utf8"))

        endpoints = []
        def visit_node(node):
            if node.type == "decorated_definition":
                for child in node.children:
                    if child.type == "decorator":
                        decorator_text = source_code[child.start_byte : child.end_byte]
                        decorators = [
                            ".get",
                            ".post",
                            ".put",
                            ".patch",
                            ".delete",
                            ".options",
                            ".head",
                            ".trace",
                            ".websocket",
                            ".route",
                        ]
                        if any(decorator in decorator_text for decorator in decorators):
                            if (
                                ".patch." in decorator_text
                            ):  # hardcoded to handle decorators with 3 levels
                                continue
                            function_name, parameters, start, end, text = (
                                self.extract_function_metadata(node)
                            )
                            function_identifier = (
                                filename.replace(self.directory, "")
                                + ":"
                                + function_name
                            )
                            endpoint = (
                                ((decorator_text.split("(")[0]).split(".")[-1]).upper()
                                + " "
                                + self.extract_path(decorator_text)
                            )
                            endpoint_list = [endpoint]
                            # handle flask endpoint definitions
                            if (
                                ".route" in decorator_text
                                and "methods" in decorator_text
                            ):
                                methods_text = (
                                    decorator_text.split("methods=")[1]
                                    .split(")")[0]
                                    .strip()
                                )
                                methods_text = methods_text.strip("[").strip("]")
                                methods = [
                                    method.strip().replace("'", "").replace('"', "")
                                    for method in methods_text.split(",")
                                ]
                                endpoint_list = [
                                    endpoint.replace("ROUTE", method.upper())
                                    for method in methods
                                ]
                            elif (
                                ".route" in decorator_text
                                and "methods" not in decorator_text
                            ):
                                endpoint_list = [endpoint.replace("ROUTE", "GET")]
                            
                            for grandchild in child.children:
                                if grandchild.type == "call":
                                    for element in grandchild.children:
                                        if element.type == "argument_list":
                                            for kid in element.children:
                                                if kid.type == "keyword_argument":
                                                    if (
                                                        kid.children[0].text.decode(
                                                            "utf8"
                                                        )
                                                        == "response_model"
                                                    ):
                                                        response = kid.children[
                                                            2
                                                        ].text.decode("utf8")
                                                        obj = self.get_node(
                                                            function_identifier
                                                        )
                                                        obj["response"] = response
                                                        self.update_node(
                                                            function_identifier, obj
                                                        )
                            for entrypoint in endpoint_list:
                                endpoints.append((entrypoint, function_identifier))

            for child in node.children:
                visit_node(child)

        visit_node(tree.root_node)
        return [(decorator, func_name) for decorator, func_name in endpoints]


    def get_python_filepaths(self, directory_path):
        python_filepaths = []
        for root, dirs, files in os.walk(directory_path):
            for file in files:
                if file.endswith(".py") and not file.startswith("test"):
                    file_path = os.path.join(root, file)
                    python_filepaths.append(file_path)
        return python_filepaths
    
    def extract_function_metadata(self, node):
        function_name = None

        if node.type == "decorated_definition":
            # Find the actual function_definition node
            for child in node.children:
                if child.type == 'function_definition':
                    function_name = self.extract_function_metadata(child)[0]
                    
        
        parameters = []

        for child in node.children:
            if child.type == 'identifier' and function_name is None:
                function_name = child.text.decode('utf8')
            elif child.type == 'parameters':
                parameters = [param.text.decode('utf8') for param in child.children if param.type == 'identifier']
        start,_ = node.start_point
        end,_ = node.end_point
        text = node.text.decode('utf8')
        
        return function_name, parameters, start, end, text
    
    def analyse_endpoints(self):
        self.setup_database()
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        cursor = conn.cursor()
        detected_endpoints = []
        detected_endpoints = self.identify_django_endpoints(self.directory)

        file_paths = self.get_python_filepaths(self.directory)
        for file_path in file_paths:
            with open(file_path, "r", encoding="utf-8") as file:
                source_code = file.read()
                decorator_endpoints = self.find_endpoints_from_decorator(
                    source_code, file_path
                )
                if decorator_endpoints:
                    detected_endpoints.extend(decorator_endpoints)
        for path, identifier in detected_endpoints:
            router_info = self.router_prefix_file_mapping.get(identifier.split(":")[0], {})
            prefix = router_info.get("prefix", None)
            depends = router_info.get("depends", [])
            path = self.get_qualified_endpoint_name(path, prefix)
            try:
                cursor.execute("INSERT INTO endpoints (path, identifier) VALUES (?, ?)", (path, identifier))
                conn.commit()
            except sqlite3.IntegrityError:
                print(f"Duplicate entry for identifier {identifier} skipped.")
            for dependency in depends:
                graph.atomic(self.db_path, graph.connect_nodes(identifier, dependency, {'action': 'calls'}))
        
        conn.close()

    def get_qualified_endpoint_name(self, path, prefix):
        if prefix == None:
            return path
        prefix = prefix.strip('"').strip('/')
        return path.split('/')[0] + "/" + prefix + "/" + "/".join(path.split('/')[1:])
        
    def display_endpoints(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        paths = []
        try:
            cursor.execute("SELECT path, identifier FROM endpoints")
            endpoints = cursor.fetchall()
            paths = {}
            for endpoint in endpoints:
                filename = endpoint[1].split(":")[0]
                if filename not in paths:
                    paths[filename] = []
                paths[filename].append({
                    "entryPoint": endpoint[0],
                    "identifier": endpoint[1]
                })
            
        except sqlite3.Error as e:
            print("An error occurred:", e)
        finally:
            conn.close()
        
        return paths
    

        
    def update_test_plan(self,  identifier, plan):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            query = "UPDATE endpoints SET test_plan = ? WHERE identifier = ?"
            params = (plan, identifier) 
            cursor.execute(query, params)        
        except sqlite3.IntegrityError as e:
            print(e.sqlite_errorname)

        conn.commit()
        conn.close()
    
    def update_test_preferences(self,  identifier, preferences):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            query = "UPDATE endpoints SET preferences = ? WHERE identifier = ?"
            params = (json.dumps(preferences), identifier) 
            cursor.execute(query, params)        
        except sqlite3.IntegrityError as e:
            print(e.sqlite_errorname)

        conn.commit()
        conn.close()
        
    def get_test_plan(self, identifier):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            query = "SELECT test_plan FROM endpoints WHERE identifier = ?"
            cursor.execute(query, (identifier,))
            row = cursor.fetchone()
            if row[0]:
                return json.loads(row[0])  # Deserialize the test plan back into a Python dictionary
            else:
                return None  # No test plan found for the given identifier
        except sqlite3.Error as e:
            print(f"SQLite error: {e}")
            return None
        finally:
            conn.close()
            
    def get_preferences(self, identifier):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        try:
            query = "SELECT preferences FROM endpoints WHERE identifier = ?"
            cursor.execute(query, (identifier,))
            row = cursor.fetchone()
            if row and row[0]:
                return json.loads(row[0])  # Deserialize the test plan back into a Python dictionary
            else:
                return None  # No test plan found for the given identifier
        except sqlite3.Error as e:
            print(f"SQLite error: {e}")
            return None
        finally:
            conn.close()
            
    def get_test_plan_preferences(self, identifier):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        test_plan = None
        preferences = None
        try:
            query = "SELECT test_plan, preferences FROM endpoints WHERE identifier = ?"
            cursor.execute(query, (identifier,))
            row = cursor.fetchone()
            if row and row[0]:
                test_plan = json.loads(row[0])  # Deserialize the test plan back into a Python dictionary
            else:
                test_plan = None  # No test plan found for the given identifier
            
            if row[1]:
                preferences = json.loads(row[1])  # Deserialize the test plan back into a Python dictionary
            else:
                preferences = None  # No test plan found for the given identifier
        except sqlite3.Error as e:
            print(f"SQLite error: {e}")
            return None, None
        finally:
            conn.close()
        return test_plan, preferences
            
    def get_node(self, function_identifier):
        codebase_map = f'{self.directory}/.momentum/momentum.db'
        return graph.atomic(codebase_map, graph.find_node(function_identifier))

    def update_node(self, function_identifier, body):
        codebase_map = f'{self.directory}/.momentum/momentum.db'
        return graph.atomic(codebase_map, graph.upsert_node(function_identifier, body))

