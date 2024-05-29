import subprocess
import os
from itertools import islice
# from tree_sitter import Language, Parser
# # Load Python grammar for Tree-sittefrom tree_sitter import Language, Parser


# PY_LANGUAGE = Language('./build/my-languages.so', 'python')

# # Initialize SQLite Database and Graph
# parser = Parser()
# parser.set_language(PY_LANGUAGE)

from tree_sitter_languages import get_parser, get_language
parser = get_parser("python")
PY_LANGUAGE = get_language("python")

def _get_git_diff_detail(base_branch, head_branch, repo, pull):
    """Fetch detailed diff information, focusing on changed lines."""
    diff_text = ""
    files = list(islice(pull.get_files(), 51))
    for file in files:
        path = file.filename
        patch = file.patch
        diff_text += f"--- a/{path}\n+++ b/{path}\n{patch}\n"
    return diff_text


def _parse_diff_detail(diff_detail, repo_path):
    changed_files = {}
    current_file = None
    for line in diff_detail.split('\n'):
        if line.startswith('+++ b/'):
            relative_file_path = line.split('+++ b/')[1].strip()
           
            current_file = os.path.normpath(os.path.join(repo_path, relative_file_path))
            changed_files[current_file] = set()
        elif line.startswith('@@'):
            parts = line.split()
            add_start_line, add_num_lines = map(int, parts[2][1:].split(',')) if ',' in parts[2] else (int(parts[2][1:]), 1)
            for i in range(add_start_line, add_start_line + add_num_lines -1):
                changed_files[current_file].add(i)
    return changed_files




def _parse_functions_and_classes_from_file(file_path):
    """Parse a file and build a map of function and class names to their line ranges."""
    with open(file_path, 'rb') as file:
        content = file.read()
    tree = parser.parse(content)
    root_node = tree.root_node
    functions_and_classes = {}

    def extract_functions_and_classes(node, class_name=None):
        if node.type == 'function_definition':
            function_name = next((child for child in node.children if child.type == 'identifier'), None)
            if function_name:
                function_name = function_name.text.decode('utf-8')
                full_name = f"{class_name}:{function_name}" if class_name else function_name
                functions_and_classes[full_name] = (node.start_point[0] + 1, node.end_point[0] + 1)
        elif node.type == 'class_definition':
            class_name = next((child for child in node.children if child.type == 'identifier'), None)
            if class_name:
                class_name = class_name.text.decode('utf-8')
                functions_and_classes[class_name] = (node.start_point[0] + 1, node.end_point[0] + 1)
                for child in node.children:
                    extract_functions_and_classes(child, class_name)
        else:
            for child in node.children:
                extract_functions_and_classes(child, class_name)

    extract_functions_and_classes(root_node)
    return functions_and_classes

def _find_changed_functions(changed_files, repo_path):
    result = []
    for file_path, lines in changed_files.items():
        try:
            functions = _parse_functions_and_classes_from_file(file_path)
            for full_name, (start_line, end_line) in functions.items():
                if any(start_line <= line <= end_line for line in lines):
                    internal_path = os.path.relpath(file_path, start=repo_path)
                    if not internal_path.startswith(os.sep):
                        internal_path = os.sep+internal_path
                    result.append(f"{internal_path}:{full_name}")
        except FileNotFoundError:
            print(f"File not found: {file_path}")
    return result



def get_updated_function_list(base_branch, head_branch, repo, repo_path, pull_request):
    diff_detail = _get_git_diff_detail(base_branch, head_branch, repo, pull_request)
    changed_files = _parse_diff_detail(diff_detail, repo_path)
    return _find_changed_functions(changed_files, repo_path)
