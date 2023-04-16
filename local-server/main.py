from dotenv import load_dotenv
from urllib.parse import urlparse, unquote

load_dotenv()

import os

# This is a version of the main.py file found in ../../../server/main.py for testing the plugin locally.
# Use the command `poetry run dev` to run this.
from typing import Optional
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Body, UploadFile
import uuid
import zipfile
import os
import json
import argparse
import asyncio

from models.models import Document, DocumentMetadata, Source
from datastore.datastore import DataStore
from datastore.factory import get_datastore
from services.extract_metadata import extract_metadata_from_document
from services.file import extract_text_from_filepath
from services.pii_detection import screen_text_for_pii

DOCUMENT_UPSERT_BATCH_SIZE = 50


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

async def process_file_dump(
    filepath: str,
    datastore: DataStore,
    custom_metadata: dict,
    screen_for_pii: bool,
    extract_metadata: bool,
):
    # create a ZipFile object and extract all the files into a directory named 'dump'
    with zipfile.ZipFile(filepath) as zip_file:
        zip_file.extractall("dump")

    documents = []
    skipped_files = []
    # use os.walk to traverse the dump directory and its subdirectories
    for root, dirs, files in os.walk("dump"):
        for filename in files:
            if len(documents) % 20 == 0:
                print(f"Processed {len(documents)} documents")

            filepath = os.path.join(root, filename)

            try:
                extracted_text = extract_text_from_filepath(filepath)
                print(f"extracted_text from {filepath}")

                # create a metadata object with the source and source_id fields
                metadata = DocumentMetadata(
                    source=Source.file,
                    source_id=filename,
                )

                # update metadata with custom values
                for key, value in custom_metadata.items():
                    if hasattr(metadata, key):
                        setattr(metadata, key, value)

                # screen for pii if requested
                if screen_for_pii:
                    pii_detected = screen_text_for_pii(extracted_text)
                    # if pii detected, print a warning and skip the document
                    if pii_detected:
                        print("PII detected in document, skipping")
                        skipped_files.append(
                            filepath
                        )  # add the skipped file to the list
                        continue

                # extract metadata if requested
                if extract_metadata:
                    # extract metadata from the document text
                    extracted_metadata = extract_metadata_from_document(
                        f"Text: {extracted_text}; Metadata: {str(metadata)}"
                    )
                    # get a Metadata object from the extracted metadata
                    metadata = DocumentMetadata(**extracted_metadata)

                # create a document object with a random id, text and metadata
                document = Document(
                    id=str(uuid.uuid4()),
                    text=extracted_text,
                    metadata=metadata,
                )
                documents.append(document)
            except Exception as e:
                # log the error and continue with the next file
                print(f"Error processing {filepath}: {e}")
                skipped_files.append(filepath)  # add the skipped file to the list

    # do this in batches, the upsert method already batches documents but this allows
    # us to add more descriptive logging
    for i in range(0, len(documents), DOCUMENT_UPSERT_BATCH_SIZE):
        # Get the text of the chunks in the current batch
        batch_documents = [doc for doc in documents[i : i + DOCUMENT_UPSERT_BATCH_SIZE]]
        print(f"Upserting batch of {len(batch_documents)} documents, batch {i}")
        print("documents: ", documents)
        await datastore.upsert(batch_documents)

    # delete all files in the dump directory
    for root, dirs, files in os.walk("dump", topdown=False):
        for filename in files:
            filepath = os.path.join(root, filename)
            os.remove(filepath)
        for dirname in dirs:
            dirpath = os.path.join(root, dirname)
            os.rmdir(dirpath)

    # delete the dump directory
    os.rmdir("dump")

    # print the skipped files
    print(f"Skipped {len(skipped_files)} files due to errors or PII detection")
    for file in skipped_files:
        print(file)


def convert_url_to_name(url):
    print("doing convert..")

    print(f"repo_url is {url}")

    if url.endswith('.git'):
        url = url[:-4]

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

    zip_filename = f"./{repo_name}.zip"

    index_name = convert_url_to_name(request.repo_url)

    # initialize the db instance once as a global variable
    datastore = await get_datastore(index_name, True)
    custom_metadata = {}
    screen_for_pii = False
    extract_metadata = False

    await process_file_dump(filepath=zip_filename, datastore=datastore, custom_metadata=custom_metadata, screen_for_pii=screen_for_pii, extract_metadata=extract_metadata)

    os.remove(zip_filename)

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


@app.on_event("startup")
async def startup():
    return

def start():
    uvicorn.run("local-server.main:app", host="localhost", port=PORT, reload=True)
