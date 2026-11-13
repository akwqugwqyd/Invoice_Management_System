from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

from app.extraction import InvoiceDraft, draft_from_text, extract_text
from app.storage import InvoiceStore
from app.synthetic import SYNTHETIC_INVOICES, synthetic_invoice_pdf, synthetic_records

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATABASE_PATH = Path(os.getenv("DATABASE_PATH", str(ROOT / "data" / "invoices.db")))
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024
SAMPLE_DATA_MODE = os.getenv("SAMPLE_DATA", "true").strip().lower() in {"1", "true", "yes"}
store = InvoiceStore(DATABASE_PATH)

app = FastAPI(title="Invoice OCR Review", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
source_records: dict[str, dict[str, str]] = {}
processing_jobs: dict[str, dict[str, Any]] = {}
workflow_generation = 0
MAX_RETAINED_JOBS = 200


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: InvoiceDraft


def _allowed_hosts(api_url: str) -> set[str]:
    configured = os.getenv("INVOICE_API_ALLOWED_FILE_HOSTS", "")
    hosts = {host.strip().lower() for host in configured.split(",") if host.strip()}
    if not hosts:
        api_host = urlparse(api_url).hostname
        if api_host:
            hosts.add(api_host.lower())
    return hosts


async def _download_document(
    client: httpx.AsyncClient,
    url: str,
    hosts: set[str],
    allow_insecure_http: bool = False,
) -> tuple[bytes, str]:
    parsed = urlparse(url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http"
        and (
            os.getenv("ALLOW_INSECURE_HTTP", "").lower() == "true"
            or allow_insecure_http
        )
    ):
        raise ValueError("Invoice file URLs must use HTTPS")
    if not parsed.hostname or parsed.hostname.lower() not in hosts:
        raise ValueError("Invoice file host is not in INVOICE_API_ALLOWED_FILE_HOSTS")

    async with client.stream("GET", url, follow_redirects=False) as response:
        if not response.is_success:
            response.raise_for_status()
            raise ValueError(f"Invoice file request returned HTTP {response.status_code}")
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) > MAX_DOCUMENT_BYTES:
            raise ValueError("Invoice file exceeds the 20 MB processing limit")
        filename = Path(parsed.path).name
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            suffix = {
                "application/pdf": ".pdf",
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/tiff": ".tiff",
                "image/bmp": ".bmp",
            }.get(response.headers.get("content-type", "").split(";", maxsplit=1)[0].lower(), "")
            filename = f"invoice{suffix}"
        chunks: list[bytes] = []
        size = 0
        async for chunk in response.aiter_bytes():
            size += len(chunk)
            if size > MAX_DOCUMENT_BYTES:
                raise ValueError("Invoice file exceeds the 20 MB processing limit")
            chunks.append(chunk)
        return b"".join(chunks), filename


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/sample-api/invoices")
async def get_synthetic_invoices(request: Request) -> dict[str, list[dict[str, str]]]:
    return synthetic_records(str(request.base_url))


@app.get("/sample-api/files/{invoice_id}.pdf")
async def get_synthetic_invoice_file(invoice_id: str) -> Response:
    if invoice_id not in SYNTHETIC_INVOICES:
        raise HTTPException(status_code=404, detail="Synthetic invoice not found.")
    return Response(
        content=synthetic_invoice_pdf(invoice_id),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{invoice_id}.pdf"'},
    )


@app.get("/api/source-invoices")
async def list_source_invoices(request: Request) -> dict[str, list[dict[str, str | None]]]:
    api_url = (
        f"{str(request.base_url).rstrip('/')}/sample-api/invoices"
        if SAMPLE_DATA_MODE
        else os.getenv("INVOICE_API_URL")
    )
    if not api_url:
        raise HTTPException(status_code=503, detail="Configure INVOICE_API_URL first.")

    parsed_api_url = urlparse(api_url)
    if not parsed_api_url.hostname or (
        parsed_api_url.scheme != "https"
        and not (
            (SAMPLE_DATA_MODE and parsed_api_url.scheme == "http")
            or (
                os.getenv("ALLOW_INSECURE_HTTP", "").lower() == "true"
                and parsed_api_url.scheme == "http"
            )
        )
    ):
        raise HTTPException(status_code=503, detail="The invoice API URL must use HTTPS.")

    headers: dict[str, str] = {}
    token = os.getenv("INVOICE_API_TOKEN")
    if token and not SAMPLE_DATA_MODE:
        headers["Authorization"] = f"Bearer {token}"

    try:
        options: dict[str, Any] = {"timeout": 30, "headers": headers}
        if SAMPLE_DATA_MODE:
            options.update(
                transport=httpx.ASGITransport(app=app),
                base_url=str(request.base_url),
            )
        async with httpx.AsyncClient(**options) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"Invoice API request failed: {error}") from error

    records = payload.get("invoices") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise HTTPException(
            status_code=502,
            detail="Invoice API must return an array or an object with an 'invoices' array.",
        )

    latest_by_source: dict[str, dict[str, Any]] = {}
    for invoice in store.list():
        latest_by_source.setdefault(invoice["source_id"], invoice)

    source_records.clear()
    result: list[dict[str, str | None]] = []
    for record in records:
        source_id = str(record.get("id", "")) if isinstance(record, dict) else ""
        file_url = record.get("file_url") if isinstance(record, dict) else None
        if not source_id or not isinstance(file_url, str):
            raise HTTPException(
                status_code=502,
                detail="Every invoice source record must include an 'id' and 'file_url'.",
            )
        source_records[source_id] = {"id": source_id, "file_url": file_url}
        previous = latest_by_source.get(source_id)
        extension = Path(urlparse(file_url).path).suffix.lower()
        file_type = {
            ".pdf": "PDF",
            ".png": "PNG",
            ".jpg": "JPG",
            ".jpeg": "JPG",
            ".tif": "TIFF",
            ".tiff": "TIFF",
            ".bmp": "BMP",
        }.get(extension, "DOCUMENT")
        result.append(
            {
                "id": source_id,
                "status": previous["status"] if previous else "available",
                "invoice_id": previous["id"] if previous else None,
                "file_type": file_type,
            }
        )
    return {"invoices": result}


async def _load_source_document(request: Request, source_id: str) -> tuple[bytes, str]:
    record = source_records.get(source_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found. Fetch the source invoice list first.",
        )

    api_url = (
        f"{str(request.base_url).rstrip('/')}/sample-api/invoices"
        if SAMPLE_DATA_MODE
        else os.getenv("INVOICE_API_URL", "")
    )
    hosts = _allowed_hosts(api_url)
    if SAMPLE_DATA_MODE:
        sample_host = urlparse(str(request.base_url)).hostname
        if sample_host:
            hosts.add(sample_host.lower())

    options: dict[str, Any] = {"timeout": 30}
    if SAMPLE_DATA_MODE:
        options.update(
            transport=httpx.ASGITransport(app=app),
            base_url=str(request.base_url),
        )
    try:
        async with httpx.AsyncClient(**options) as client:
            return await _download_document(
                client,
                record["file_url"],
                hosts,
                allow_insecure_http=SAMPLE_DATA_MODE,
            )
    except (httpx.HTTPError, OSError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"Invoice download failed: {error}") from error


@app.get("/api/source-invoices/{source_id}/preview")
async def preview_source_invoice(source_id: str, request: Request) -> Response:
    document, filename = await _load_source_document(request, source_id)
    media_type = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".bmp": "image/bmp",
    }.get(Path(filename).suffix.lower(), "application/octet-stream")
    return Response(
        content=document,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{Path(filename).name}"'},
    )


async def _run_ocr_job(
    job_id: str,
    source_id: str,
    request: Request,
    generation: int,
) -> None:
    job = processing_jobs[job_id]
    try:
        job.update(status="running", stage="downloading", progress=15)
        document, filename = await _load_source_document(request, source_id)

        job.update(stage="recognizing", progress=55)
        raw_text = await asyncio.to_thread(extract_text, document, filename)

        job.update(stage="extracting", progress=82)
        draft = draft_from_text(raw_text)
        if generation != workflow_generation:
            return
        invoice_id = str(uuid.uuid4())
        store.create(invoice_id, source_id, draft, raw_text)
        job.update(
            status="completed",
            stage="completed",
            progress=100,
            invoice_id=invoice_id,
        )
    except HTTPException as error:
        job.update(status="failed", stage="failed", error=str(error.detail))
    except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
        job.update(status="failed", stage="failed", error=str(error))


@app.post("/api/source-invoices/{source_id}/process", status_code=202)
async def process_source_invoice(
    source_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, str | int]:
    if source_id not in source_records:
        raise HTTPException(
            status_code=404,
            detail="Invoice not found. Fetch the source invoice list first.",
        )
    invoice = store.get_by_source_id(source_id)
    if invoice and invoice["status"] != "rejected":
        return {
            "invoice_id": invoice["id"],
            "source_id": source_id,
            "status": invoice["status"],
        }

    for job_id in reversed(list(processing_jobs)):
        if (
            processing_jobs[job_id]["source_id"] == source_id
            and processing_jobs[job_id]["status"] in {"queued", "running"}
        ):
            return {"job_id": job_id, "source_id": source_id, "status": 202}

    for job_id in list(processing_jobs):
        if len(processing_jobs) <= MAX_RETAINED_JOBS:
            break
        if processing_jobs[job_id]["status"] in {"completed", "failed"}:
            del processing_jobs[job_id]

    job_id = str(uuid.uuid4())
    processing_jobs[job_id] = {
        "id": job_id,
        "source_id": source_id,
        "status": "queued",
        "stage": "queued",
        "progress": 0,
    }
    background_tasks.add_task(
        _run_ocr_job, job_id, source_id, request, workflow_generation
    )
    return {"job_id": job_id, "source_id": source_id, "status": 202}


@app.get("/api/jobs/{job_id}")
async def get_processing_job(job_id: str) -> dict[str, Any]:
    job = processing_jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="OCR job not found.")
    return dict(job)


@app.post("/api/fetch")
async def fetch_invoices(request: Request) -> dict[str, object]:
    api_url = (
        f"{str(request.base_url).rstrip('/')}/sample-api/invoices"
        if SAMPLE_DATA_MODE
        else os.getenv("INVOICE_API_URL")
    )
    if not api_url:
        raise HTTPException(
            status_code=503,
            detail="Configure INVOICE_API_URL before fetching invoices.",
        )
    parsed_api_url = urlparse(api_url)
    is_local_sample_data = SAMPLE_DATA_MODE
    if not parsed_api_url.hostname or (
        parsed_api_url.scheme != "https"
        and not (
            parsed_api_url.scheme == "http"
            and (
                os.getenv("ALLOW_INSECURE_HTTP", "").lower() == "true"
                or is_local_sample_data
            )
        )
    ):
        raise HTTPException(
            status_code=503,
            detail="INVOICE_API_URL must use HTTPS unless ALLOW_INSECURE_HTTP=true.",
        )
    headers: dict[str, str] = {}
    token = os.getenv("INVOICE_API_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        api_client_options: dict[str, object] = {"timeout": 30, "headers": headers}
        if is_local_sample_data:
            api_client_options.update(
                transport=httpx.ASGITransport(app=app),
                base_url=str(request.base_url),
            )
        async with httpx.AsyncClient(**api_client_options) as client:
            response = await client.get(api_url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError) as error:
        raise HTTPException(status_code=502, detail=f"Invoice API request failed: {error}") from error

    records = payload.get("invoices") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise HTTPException(
            status_code=502,
            detail="Invoice API must return an array or an object with an 'invoices' array.",
        )

    results: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    hosts = _allowed_hosts(api_url)
    if is_local_sample_data and parsed_api_url.hostname:
        hosts.add(parsed_api_url.hostname.lower())
    download_client_options: dict[str, object] = {"timeout": 30}
    if is_local_sample_data:
        download_client_options.update(
            transport=httpx.ASGITransport(app=app),
            base_url=str(request.base_url),
        )
    async with httpx.AsyncClient(**download_client_options) as client:
        for record in records:
            source_id = str(record.get("id", "")) if isinstance(record, dict) else ""
            file_url = record.get("file_url") if isinstance(record, dict) else None
            if not source_id or not isinstance(file_url, str):
                errors.append(
                    {"source_id": source_id or "unknown", "error": "Record needs 'id' and 'file_url'."}
                )
                continue
            try:
                document, filename = await _download_document(
                    client, file_url, hosts, allow_insecure_http=is_local_sample_data
                )
                raw_text = extract_text(document, filename)
                draft = draft_from_text(raw_text)
                invoice_id = str(uuid.uuid4())
                store.create(invoice_id, source_id, draft, raw_text)
                results.append({"id": invoice_id, "source_id": source_id, "status": "needs_review"})
            except (httpx.HTTPError, OSError, ValueError, RuntimeError) as error:
                errors.append({"source_id": source_id, "error": str(error)})

    return {"created": results, "errors": errors}


@app.get("/api/invoices")
async def list_invoices(
    status: str | None = Query(default=None, pattern="^(needs_review|approved|rejected)$"),
) -> list[dict[str, object]]:
    return store.list(status)


@app.post("/api/reset")
async def reset_workflow() -> dict[str, str]:
    global workflow_generation
    workflow_generation += 1
    store.clear()
    source_records.clear()
    processing_jobs.clear()
    return {"status": "reset"}


@app.get("/api/invoices/{invoice_id}")
async def get_invoice(invoice_id: str) -> dict[str, object]:
    invoice = store.get(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    return invoice


@app.post("/api/invoices/{invoice_id}/approve")
async def approve_invoice(invoice_id: str, request: ApprovalRequest) -> dict[str, object]:
    if store.get(invoice_id) is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    draft = request.draft.model_dump()
    if not store.decide(invoice_id, "approved", draft):
        raise HTTPException(status_code=409, detail="Invoice has already been reviewed.")
    return {"id": invoice_id, "status": "approved", "result": draft}


@app.post("/api/invoices/{invoice_id}/reject")
async def reject_invoice(invoice_id: str) -> dict[str, str]:
    if store.get(invoice_id) is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if not store.decide(invoice_id, "rejected"):
        raise HTTPException(status_code=409, detail="Invoice has already been reviewed.")
    return {"id": invoice_id, "status": "rejected"}


@app.get("/api/invoices/{invoice_id}/result")
async def get_approved_result(invoice_id: str) -> dict[str, object]:
    invoice = store.get(invoice_id)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if invoice["status"] != "approved":
        raise HTTPException(status_code=409, detail="Invoice must be approved before its JSON is returned.")
    return invoice["draft"]
