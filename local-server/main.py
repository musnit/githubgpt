from dotenv import load_dotenv
import subprocess
from urllib.parse import urlparse

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

@app.post(
    "/index-repo",
    response_model=IndexResponse,
)
async def index_repo(
    request: IndexRequest = Body(...),
):
    repo_name = convert_url_to_name(request.repo_url)
    print(f"Indexing {repo_name}")

    # subprocess.run(['python3', '../scripts/process_zip/process_zip.py'
    # f"--filepath ../tmp/{repo_name}`.zip"])

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
    global datastore
    datastore = await get_datastore(PINECONE_INDEX)


def start():
    uvicorn.run("local-server.main:app", host="localhost", port=PORT, reload=True)
