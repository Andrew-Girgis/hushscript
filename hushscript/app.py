import asyncio
import contextlib
import hashlib
import hmac
import json
import os
import secrets
import signal
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.requests import ClientDisconnect

from .exports import bundle, clean_name, render
from .privacy import anonymous_file, protect_process, readiness

ROOT = Path(__file__).parent
ACTIVE = {"reserved", "uploading", "processing"}


@dataclass
class Settings:
    models: str = field(default_factory=lambda: os.getenv("HUSHSCRIPT_MODELS", "/models"))
    runtime: str = field(
        default_factory=lambda: os.getenv("HUSHSCRIPT_RUNTIME", "/opt/nemo/current")
    )
    guard: str = field(
        default_factory=lambda: os.getenv("HUSHSCRIPT_GUARD", "/host-guard/status.json")
    )
    device: str = field(default_factory=lambda: os.getenv("HUSHSCRIPT_DEVICE", "cpu"))
    max_bytes: int = 250 * 1024 * 1024
    retention: float = 900
    upload_timeout: float = 120
    process_timeout: float = 1800
    disconnect_timeout: float = 90
    hosts: list[str] = field(
        default_factory=lambda: [
            "127.0.0.1",
            "localhost",
            "[::1]",
            *filter(None, os.getenv("HUSHSCRIPT_HOSTS", "").split(",")),
        ]
    )
    origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:8787",
            "http://localhost:8787",
            *filter(None, os.getenv("HUSHSCRIPT_ORIGINS", "").split(",")),
        ]
    )


@dataclass
class Job:
    id: str
    token_hash: bytes
    filename: str
    diarize: bool
    phase: str = "reserved"
    created: float = field(default_factory=time.monotonic)
    touched: float = field(default_factory=time.monotonic)
    finished: float | None = None
    fd: int | None = None
    process: asyncio.subprocess.Process | None = None
    task: asyncio.Task | None = None
    upload_task: asyncio.Task | None = None
    closed: bool = False
    result: dict | None = None
    error: str | None = None


class CreateJob(BaseModel):
    filename: str = Field(min_length=1, max_length=160)
    diarize: bool = False


class Manager:
    def __init__(self, settings, probe):
        self.settings = settings
        self.probe = probe
        self.jobs: dict[str, Job] = {}

    def lookup(self, job_id, request):
        job = self.jobs.get(job_id)
        header = request.headers.get("authorization", "")
        token = header.removeprefix("Bearer ") if header.startswith("Bearer ") else ""
        digest = hashlib.sha256(token.encode()).digest()
        if not job or not hmac.compare_digest(job.token_hash, digest):
            raise HTTPException(404, "Job not found or no longer available.")
        return job

    async def dispose(self, job):
        if job.closed:
            return
        job.closed = True
        self.jobs.pop(job.id, None)
        if (
            job.upload_task
            and job.upload_task is not asyncio.current_task()
            and not job.upload_task.done()
        ):
            job.upload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, HTTPException):
                await job.upload_task
        if job.task and job.task is not asyncio.current_task() and not job.task.done():
            job.task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await job.task
        await self.kill(job)
        if job.fd is not None:
            with contextlib.suppress(OSError):
                os.close(job.fd)
            job.fd = None
        job.result = None
        job.filename = ""
        self.jobs.pop(job.id, None)

    async def kill(self, job):
        if job.process is not None and job.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(job.process.pid, signal.SIGKILL)
            await job.process.wait()

    async def run(self, job):
        output = bytearray()
        try:
            command = [sys.executable, "-m", "hushscript.worker", "--fd", str(job.fd)]
            if job.diarize:
                command.append("--diarize")
            env = dict(
                os.environ,
                HUSHSCRIPT_RUNTIME=self.settings.runtime,
                HUSHSCRIPT_MODELS=self.settings.models,
                HUSHSCRIPT_DEVICE=self.settings.device,
            )
            spawning = asyncio.create_task(
                asyncio.create_subprocess_exec(
                    *command,
                    pass_fds=(job.fd,),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
            )
            try:
                job.process = await asyncio.shield(spawning)
            except asyncio.CancelledError:
                job.process = await spawning
                raise
            os.close(job.fd)
            job.fd = None
            async with asyncio.timeout(self.settings.process_timeout):
                while chunk := await job.process.stdout.read(65536):
                    output.extend(chunk)
                    if len(output) > 16 * 1024 * 1024:
                        raise ValueError("Result size limit")
                await job.process.wait()
            if job.process.returncode != 0:
                raise ValueError("Worker stopped")
            result = json.loads(output)
            if "error" in result:
                job.error = result["error"]
                job.phase = "failed"
            else:
                result["source"] = {"filename": job.filename}
                job.result = result
                job.phase = "ready"
        except asyncio.CancelledError:
            job.phase = "cancelled"
            raise
        except TimeoutError:
            job.phase, job.error = "failed", "Processing timed out. Try a shorter recording."
        except Exception:
            job.phase, job.error = "failed", "The worker stopped. Check memory and model setup."
        finally:
            output[:] = b"\0" * len(output)
            await self.kill(job)
            if job.fd is not None:
                with contextlib.suppress(OSError):
                    os.close(job.fd)
                job.fd = None
            job.finished = time.monotonic()

    async def reap(self):
        while True:
            await asyncio.sleep(1)
            now = time.monotonic()
            protected = not self.probe()
            for job in list(self.jobs.values()):
                stale = (
                    (job.phase == "reserved" and now - job.created > 60)
                    or (
                        job.phase == "uploading"
                        and now - job.created > self.settings.upload_timeout + 60
                    )
                    or (
                        job.phase == "processing"
                        and now - job.touched > self.settings.disconnect_timeout
                    )
                    or (job.finished is not None and now - job.finished > self.settings.retention)
                    or not protected
                )
                if stale:
                    await self.dispose(job)


def create_app(settings=None, *, probe=None, protect=True):
    settings = settings or Settings()
    probe = probe or (lambda: readiness(settings.models, settings.runtime, settings.guard))
    manager = Manager(settings, probe)

    @asynccontextmanager
    async def lifespan(app):
        if protect:
            protect_process(offline=True)
        reaper = asyncio.create_task(manager.reap())
        try:
            yield
        finally:
            reaper.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reaper
            for job in list(manager.jobs.values()):
                await manager.dispose(job)

    app = FastAPI(
        telemetry={"tracing": False, "metrics": False, "logs": False, "auto_configure": False},
        title="Hushscript",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.manager = manager
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.hosts)

    @app.middleware("http")
    async def browser_security(request, call_next):
        origin = request.headers.get("origin")
        if origin is not None and origin not in settings.origins:
            return JSONResponse({"detail": "Origin is not allowed."}, status_code=403)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "DENY",
                "Cross-Origin-Resource-Policy": "same-origin",
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'self'",
            }
        )
        return response

    @app.get("/api/health")
    async def health():
        problems = probe()
        return {
            "ready": not problems,
            "problems": problems,
            "device": settings.device,
            "busy": any(job.phase in ACTIVE for job in manager.jobs.values()),
            "limits": {
                "files": 50,
                "bytes_per_file": settings.max_bytes,
                "seconds_per_file": 1200,
                "result_ttl_seconds": settings.retention,
            },
        }

    @app.post("/api/jobs", status_code=201)
    async def create(body: CreateJob):
        problems = probe()
        if problems:
            raise HTTPException(503, " ".join(problems))
        if any(job.phase in ACTIVE for job in manager.jobs.values()):
            raise HTTPException(
                409,
                "The worker is busy. Keep the file on your device and retry.",
                headers={"Retry-After": "3"},
            )
        if len(manager.jobs) >= 50:
            raise HTTPException(
                429, "Download or discard earlier results before starting more jobs."
            )
        if (
            body.diarize
            and not (Path(settings.models) / "Nemotron-3-Diarization.q8_0.gguf").is_file()
        ):
            raise HTTPException(503, "Download the diarization model during setup.")
        token, job_id = secrets.token_urlsafe(32), secrets.token_urlsafe(18)
        manager.jobs[job_id] = Job(
            job_id, hashlib.sha256(token.encode()).digest(), clean_name(body.filename), body.diarize
        )
        return {"id": job_id, "token": token, "upload_within_seconds": 60}

    @app.put("/api/jobs/{job_id}/audio", status_code=202)
    async def upload(job_id: str, request: Request):
        job = manager.lookup(job_id, request)
        if job.phase != "reserved":
            raise HTTPException(409, "This job has already received its audio.")
        try:
            length = int(request.headers.get("content-length", "0"))
        except ValueError:
            await manager.dispose(job)
            raise HTTPException(400, "Invalid Content-Length.") from None
        if length < 0 or length > settings.max_bytes:
            await manager.dispose(job)
            raise HTTPException(413, "File exceeds the 250 MiB limit.")
        if probe():
            await manager.dispose(job)
            raise HTTPException(503, "Privacy protections are not ready.")
        job.phase = "uploading"
        job.upload_task = asyncio.current_task()
        total = 0
        try:
            job.fd = anonymous_file()
            async with asyncio.timeout(settings.upload_timeout):
                async for chunk in request.stream():
                    total += len(chunk)
                    if total > settings.max_bytes:
                        raise HTTPException(413, "File exceeds the 250 MiB limit.")
                    view = memoryview(chunk)
                    while view:
                        written = os.write(job.fd, view)
                        view = view[written:]
            if not total:
                raise HTTPException(400, "The uploaded file is empty.")
            os.lseek(job.fd, 0, os.SEEK_SET)
            job.phase = "processing"
            job.touched = time.monotonic()
            job.upload_task = None
            job.task = asyncio.create_task(manager.run(job))
            return {"id": job.id, "status": job.phase}
        except (ClientDisconnect, TimeoutError, asyncio.CancelledError):
            await manager.dispose(job)
            raise HTTPException(
                408, "Upload interrupted. Select the file again to retry."
            ) from None
        except Exception:
            await manager.dispose(job)
            raise

    @app.get("/api/jobs/{job_id}")
    async def status(job_id: str, request: Request):
        job = manager.lookup(job_id, request)
        job.touched = time.monotonic()
        return {
            "id": job.id,
            "status": job.phase,
            "error": job.error,
            "elapsed_seconds": round((job.finished or time.monotonic()) - job.created, 1),
        }

    @app.get("/api/jobs/{job_id}/result")
    async def result(
        job_id: str, request: Request, format: Literal["json", "zip", "files"] = "json"
    ):
        job = manager.lookup(job_id, request)
        if job.phase != "ready" or job.result is None:
            raise HTTPException(409, "A completed transcript is not available.")
        if format == "zip":
            return Response(
                bundle(job.result),
                media_type="application/zip",
                headers={"Content-Disposition": 'attachment; filename="hushscript.zip"'},
            )
        if format == "files":
            return {"result": job.result, "files": render(job.result)}
        return job.result

    @app.delete("/api/jobs/{job_id}", status_code=204)
    async def discard(job_id: str, request: Request):
        """Acknowledge receipt, cancel processing, or discard a result."""
        job = manager.lookup(job_id, request)
        await manager.dispose(job)
        return Response(status_code=204)

    @app.get("/")
    async def index():
        return FileResponse(ROOT / "static/index.html")

    @app.get("/app.js")
    async def script():
        return FileResponse(ROOT / "static/app.js", media_type="text/javascript")

    @app.get("/style.css")
    async def style():
        return FileResponse(ROOT / "static/style.css", media_type="text/css")

    return app


app = create_app()
