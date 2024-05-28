import os
import tempfile
import requests
from github import Github
import time
from github.Auth import AppAuth
from parse import analyze_directory
from change_detection import get_updated_function_list
from blast_radius_detection import get_paths_from_identifiers
from dotenv import dotenv_values
import tarfile
from fastapi import FastAPI, Request
import json

config = dotenv_values(".env")

app = FastAPI()

@app.post('/webhook')
def github_app(request: Request):
    
    start_time = time.time() 
    
    payload = request.json()
    #payload = request.get_json()
    print(payload)
    if payload["action"]=='closed':
        return []
    
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
    private_key = config["GITHUB_PRIVATE_KEY"]
    # Read the private key from the environment variable
    private_key = private_key.replace(" ", "\n")
    # Add the necessary header and footer to the private key
    private_key = "-----BEGIN RSA PRIVATE KEY-----\n" + private_key + "\n-----END RSA PRIVATE KEY-----\n"
    # Encode the private key as bytes
    private_key_bytes = private_key
    app_id = config["GITHUB_APP_ID"]

    installation_id = payload["installation"]["id"]
    
    print(f"{repository_name}::{pull_request_number}\n{payload}")

    auth = AppAuth(app_id=app_id, private_key=private_key_bytes).get_installation_auth(installation_id)
    github_instance = Github(auth=auth)

    repo = github_instance.get_repo(repository_name)
 
    blast_radius = []
# Clone the base branch in a temporary directory
    with tempfile.TemporaryDirectory() as temp_dir:
        # Get the repository contents for the base branch
        # # contents = repo.get_contents("", ref=base_branch)
        # repo_dir = os.path.join(temp_dir, f"{repository['name']}")
        # # Create the temporary directory
        # os.makedirs(repo_dir, exist_ok=True)

        # Use the archive link to download the repository as a tarball
        archive_link = repo.get_archive_link('tarball', base_branch)

        # Download and extract the tarball in the temporary directory
        response = requests.get(archive_link, stream=True, headers={'Authorization': f'token {auth.token}'})
        with tarfile.open(fileobj=response.raw, mode='r|gz') as tar:
            tar.extractall(path=temp_dir)
            extracted_folder_name = os.listdir(temp_dir)[0]
            extracted_folder_path = os.path.join(temp_dir, extracted_folder_name)
            repo_folder_path = os.path.join(temp_dir, repository['name'])
            temp_dir = repo_folder_path
            os.rename(extracted_folder_path, repo_folder_path)
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
    # Calculate the elapsed time
    elapsed_time = time.time() - start_time
    print(f"Time taken for processing: {elapsed_time:.2f} seconds")

    return "Comment posted successfully"

def parse_blast_radius(blast_radius):
    markdown_output = "| Filename | Entry Point |\n"
    markdown_output += "| --- | --- |\n"
    
    for filename, endpoints in blast_radius.items():
        for endpoint in endpoints:
            entry_point = endpoint["entryPoint"]
            markdown_output += f"| {filename} | {entry_point} |\n"
    
    return markdown_output