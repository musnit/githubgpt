from dotenv import load_dotenv
import subprocess
# from process_zip import process_file_dump
from urllib.parse import urlparse, unquote

load_dotenv()

import os

# This is a version of the main.py file found in ../../../server/main.py for testing the plugin locally.
# Use the command `poetry run dev` to run this.
from typing import Optional
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Body, UploadFile

from models.api import (
    DeleteRequest,
    DeleteResponse,
    IndexRequest,
    IndexResponse,
    QueryRequest,
    QueryResponse,
    UpsertRequest,
    UpsertResponse,
)
from datastore.factory import get_datastore
from services.file import get_document_from_file

from starlette.responses import FileResponse

from models.models import DocumentMetadata, Source
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()

PORT = 3333

origins = [
    f"http://localhost:{PORT}",
    "https://chat.openai.com",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def convert_url_to_name(url):
    print("doing convert..")

    print(f"repo_url is {url}")

    # Parse the URL
    parsed_url = urlparse(url)

    # Extract the path component of the URL
    path = parsed_url.path

    # Split the path into components
    path_components = path.strip('/').split('/')

    # Join the components with a hyphen to form the desired string
    result = '-'.join(path_components)

    return result

@app.route("/.well-known/ai-plugin.json")
async def get_manifest(request):
    file_path = "./local-server/ai-plugin.json"
    return FileResponse(file_path, media_type="text/json")

@app.route("/.well-known/logo.png")
async def get_logo(request):
    file_path = "./local-server/logo.png"
    return FileResponse(file_path, media_type="text/json")

@app.route("/.well-known/openapi.yaml")
async def get_openapi(request):
    file_path = "./local-server/openapi.yaml"
    return FileResponse(file_path, media_type="text/json")

def convert_to_zip_url(repo_url):

    if repo_url.endswith('.git'):
        repo_url = repo_url[:-4]

    # Append the path to the ZIP archive of the main branch to the original URL
    branch_name = get_default_branch_name(repo_url)
    zip_url = repo_url.rstrip('/') + '/archive/refs/heads/' + branch_name + '.zip'
    return zip_url

import requests

def get_default_branch_name(repo_url):
    print(f"repo_url: {repo_url}")

    if repo_url.endswith('.git'):
        repo_url = repo_url[:-4]

    repo_parts = repo_url.rstrip('/').split('/')
    print(f"repo_parts: {repo_parts}")

    repo_owner = repo_parts[-2]
    print(f"repo_owner: {repo_owner}")

    repo_name = repo_parts[-1]
    print(f"repo_name: {repo_name}")

    # Construct the URL for the GitHub API endpoint
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"

    print(f"querying api url: {api_url}")

    # Make a GET request to the GitHub API endpoint
    response = requests.get(api_url)

    # Check if the request was successful
    if response.status_code == 200:
        print(response)
        print(response.json())
        # Parse the JSON response
        repo_info = response.json()

        # Get the default branch name from the JSON response
        default_branch_name = repo_info.get('default_branch')

        return default_branch_name
    else:
        print(f"Failed to get repository information. Status code: {response.status_code}")
        return None


def download_zip_file(filename, url, output_dir='.'):
    output_path = f"{output_dir}/{filename}.zip"
    print(f"Downloading zip to: {output_path}")

    # Send a GET request to the URL to download the file
    response = requests.get(url)

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        # Write the content of the response to a local file
        with open(output_path, 'wb') as file:
            file.write(response.content)
        print(f"File downloaded successfully to {output_path}")
    else:
        print(f"Failed to download file. Status code: {response.status_code}")

@app.post(
    "/index-repo",
    response_model=IndexResponse,
)
async def index_repo(
    request: IndexRequest = Body(...),
):
    repo_name = convert_url_to_name(request.repo_url)
    print(f"Indexing {repo_name}")

    zip_url = convert_to_zip_url(request.repo_url)
    print(f"Downloading {zip_url}")
    download_zip_file(repo_name, zip_url)
    # subprocess.run(['python3', '../scripts/process_zip/process_zip.py'
    # f"--filepath ../tmp/{repo_name}`.zip"])
    # process_file_dump(filepath=f"../tmp/{repo_name}.zip")
    success = True
    return IndexResponse(success=success)

@app.post(
    "/upsert-file",
    response_model=UpsertResponse,
)
async def upsert_file(
    file: UploadFile = File(...),
    metadata: Optional[str] = Form(None),
):
    try:
        metadata_obj = (
            DocumentMetadata.parse_raw(metadata)
            if metadata
            else DocumentMetadata(source=Source.file)
        )
    except:
        metadata_obj = DocumentMetadata(source=Source.file)

    document = await get_document_from_file(file, metadata_obj)

    try:
        ids = await datastore.upsert([document])
        return UpsertResponse(ids=ids)
    except Exception as e:
        print("Error:", e)
        raise HTTPException(status_code=500, detail=f"str({e})")


@app.post(
    "/upsert",
    response_model=UpsertResponse,
)
async def upsert(
    request: UpsertRequest = Body(...),
):
    try:
        ids = await datastore.upsert(request.documents)
        return UpsertResponse(ids=ids)
    except Exception as e:
        print("Error:", e)
        raise HTTPException(status_code=500, detail="Internal Service Error")

@app.post("/query", response_model=QueryResponse)
async def query_main(request: QueryRequest = Body(...)):
    try:
        print("Query - checking datastore")
        index_name = convert_url_to_name(request.repo_url)
        global datastore
        datastore = await get_datastore(index_name)

        results = await datastore.query(
            request.queries,
            request.repo_url
        )
        return QueryResponse(results=results)
    except Exception as e:
        print("Error detail:", e.detail)
        if "not indexed" in e.detail:
            print("not indexed error")
            raise e
        print("Error:", e)
        raise HTTPException(status_code=500, detail="Internal Service Error")


@app.delete(
    "/delete",
    response_model=DeleteResponse,
)
async def delete(
    request: DeleteRequest = Body(...),
):
    if not (request.ids or request.filter or request.delete_all):
        raise HTTPException(
            status_code=400,
            detail="One of ids, filter, or delete_all is required",
        )
    try:
        success = await datastore.delete(
            ids=request.ids,
            filter=request.filter,
            delete_all=request.delete_all,
        )
        return DeleteResponse(success=success)
    except Exception as e:
        print("Error:", e)
        raise HTTPException(status_code=500, detail="Internal Service Error")


PINECONE_INDEX = os.environ.get("PINECONE_INDEX")

@app.on_event("startup")
async def startup():
    return

def start():
    uvicorn.run("local-server.main:app", host="localhost", port=PORT, reload=True)
