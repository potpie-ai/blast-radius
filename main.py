import os
import tempfile
import requests
from github import Github, GithubIntegration
import time
import functions_framework
from github.Auth import AppAuth
from parse import analyze_directory
from change_detection import get_updated_function_list
from blast_radius_detection import get_paths_from_identifiers

from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def github_app():
    # Existing logic here
    payload = request.json


    # Extract relevant information from the payload
    pull_request = payload["pull_request"]
    pull_request_url = pull_request["url"]
    pull_request_number = pull_request["number"]
    head_branch = pull_request["head"]["ref"]
    base_branch = pull_request["base"]["ref"]
    repository = payload["repository"]
    repository_id = repository["id"]
    repository_name = repository["full_name"]
    # Get the app's private key and app ID from environment variables
    private_key = os.environ["GITHUB_PRIVATE_KEY"]
    # Read the private key from the environment variable
    private_key = private_key.replace(" ", "\n")
    # Add the necessary header and footer to the private key
    private_key = "-----BEGIN RSA PRIVATE KEY-----\n" + private_key + "\n-----END RSA PRIVATE KEY-----\n"
    # Encode the private key as bytes
    private_key_bytes = private_key
    app_id = os.environ["GITHUB_APP_ID"]

    installation_id = payload["installation"]["id"]
    
    print(f"{repository_name}::{pull_request_number}\n{payload}")

    auth = AppAuth(app_id=app_id, private_key=private_key_bytes).get_installation_auth(installation_id)
    github_instance = Github(auth=auth)

    repo = github_instance.get_repo(repository_name)


    blast_radius = []
# Clone the base branch in a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Get the repository contents for the base branch
        contents = repo.get_contents("", ref=base_branch)
        temp_dir = os.path.join(temp_dir, f"{repository['name']}")
        # Create the temporary directory
        os.makedirs(temp_dir, exist_ok=True)
        import concurrent.futures

        def download_file(content, base_path):
            if content.type == "file" and content.name.endswith(".py"):
                file_path = os.path.join(base_path, content.name)
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, "wb") as file:
                    file.write(content.decoded_content)

        def download_contents(contents, base_path):
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = []
                for content in contents:
                    if content.type == "dir":
                        new_dir_path = os.path.join(base_path, content.name)
                        os.makedirs(new_dir_path, exist_ok=True)
                        sub_contents = repo.get_contents(content.path, ref=base_branch)
                        futures.append(executor.submit(download_contents, sub_contents, new_dir_path))
                    elif content.type == "file" and content.name.endswith(".py"):
                        futures.append(executor.submit(download_file, content, base_path))
                for future in futures:
                    future.result()

        download_contents(contents, temp_dir)
        # Create a folder .momentum with write access in the same directory
        momentum_folder = os.path.join(temp_dir, ".momentum")
        os.makedirs(momentum_folder, exist_ok=True)
        os.chmod(momentum_folder, 0o777)  # Grant write access to the folder
        analyze_directory(temp_dir)
        # Checkout to the current branch
        pull_request = repo.get_pull(pull_request_number)

        identifiers = []
        try:
            identifiers = get_updated_function_list(base_branch, head_branch, repo, temp_dir, pull_request )
        except Exception as e:
            raise e
        if identifiers.count == 0:
            return []
        blast_radius = get_paths_from_identifiers(identifiers, temp_dir)

    blast_radius_table = parse_blast_radius(blast_radius)
    
    # Construct the comment message
    comment_message = f"""**Pull Request:** #{pull_request_number}\n**Current Branch:** {head_branch}\n**Base Branch:** {base_branch}\n**The blast radius of your current changes.** Learn more about blast radius [here](https://momentum.sh).
{blast_radius_table}"""

    # Create a comment on the pull request
    pull_request.create_issue_comment(comment_message)

    return "Comment posted successfully"

def parse_blast_radius(blast_radius):
    markdown_output = "| Filename | Entry Point |\n"
    markdown_output += "| --- | --- |\n"
    
    for filename, endpoints in blast_radius.items():
        for endpoint in endpoints:
            entry_point = endpoint["entryPoint"]
            markdown_output += f"| {filename} | {entry_point} |\n"
    
    return markdown_output