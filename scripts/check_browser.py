"""Browser acceptance tests with explicitly simulated inference responses."""

import io
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8790"


def main():
    # Browser profile/cache on tmpfs. This check uploads only generated empty bytes,
    # and mocks inference; it is not evidence that the model transcribes correctly.
    os.environ["TMPDIR"] = "/dev/shm"
    output = ROOT / ".runtime/browser"
    output.mkdir(parents=True, exist_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "hushscript.server", "--port", "8790"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(50):
            try:
                urllib.request.urlopen(BASE + "/api/health", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("UI test server did not start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=shutil.which("chromium") or shutil.which("google-chrome"),
                headless=True,
            )
            context = browser.new_context(viewport={"width": 1360, "height": 1020})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            events = []
            jobs = {}
            scenario = {"processing": False}

            def respond(route):
                request = route.request
                path = request.url.removeprefix(BASE)
                method = request.method
                events.append((method, path))
                data = None
                status = 200
                if path == "/api/health":
                    data = {"ready": True, "problems": [], "device": "cuda"}
                elif path == "/api/jobs" and method == "POST":
                    identifier = str(len(jobs) + 1)
                    jobs[identifier] = request.post_data_json
                    status, data = 201, {"id": identifier, "token": "test-only"}
                elif method == "DELETE":
                    status = 204
                elif path.endswith("/audio"):
                    status, data = 202, {"status": "processing"}
                elif "/result?" in path:
                    identifier = path.split("/")[3]
                    result = {
                        "duration_seconds": 10.0,
                        "processing_seconds": 0.5,
                        "diarization": jobs[identifier]["diarize"],
                        "speakers": ["speaker_1", "speaker_2"],
                        "warnings": ["Synthetic UI test; no speech model was run."],
                    }
                    data = {
                        "result": result,
                        "files": {
                            "transcript.txt": "[00:00:00] Speaker 1: Test conversation.\n",
                            "transcript.md": "# Transcript\n\nTest conversation.\n",
                            "transcript.json": json.dumps({"schema_version": "1.0", **result}),
                        },
                    }
                else:
                    data = {
                        "status": "processing" if scenario["processing"] else "ready",
                        "elapsed_seconds": 1,
                        "error": None,
                    }
                route.fulfill(
                    status=status,
                    content_type="application/json",
                    body=json.dumps(data) if data is not None else "",
                )

            page.route(BASE + "/api/**", respond)
            page.goto(BASE)
            page.wait_for_function(
                "() => document.querySelector('#health').textContent.includes('CUDA')"
            )
            page.screenshot(path=output / "desktop.png", full_page=True)
            page.locator("#files").set_input_files(
                [
                    {"name": "<script>.wav", "mimeType": "audio/wav", "buffer": b"\0" * 44},
                    {"name": "Interview.wav", "mimeType": "audio/wav", "buffer": b"\0" * 44},
                ]
            )
            page.locator("#diarize").check()
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#completed').textContent === '2 ready'"
            )
            page.wait_for_function("() => document.querySelector('#cancel').hidden")
            assert all(job["diarize"] for job in jobs.values())
            assert events.index(("DELETE", "/api/jobs/1")) < events.index(
                ("PUT", "/api/jobs/2/audio")
            )
            assert page.locator("#queue script").count() == 0
            assert page.locator("#preview").inner_text().startswith("[00:00:00]")
            with page.expect_download() as download:
                page.locator("#download").click()
            archive_bytes = Path(download.value.path()).read_bytes()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                assert len(archive.namelist()) == 6
                assert archive.testzip() is None
                for name in archive.namelist():
                    assert ".." not in name and not name.startswith("/")
            page.locator("#clear").click()
            assert page.locator("#preview").inner_text() == ""
            assert page.locator("#download").is_disabled()
            scenario["processing"] = True
            page.locator("#files").set_input_files(
                [
                    {"name": "Cancel.wav", "mimeType": "audio/wav", "buffer": b"\0" * 44},
                    {"name": "Never-upload.wav", "mimeType": "audio/wav", "buffer": b"\0" * 44},
                ]
            )
            page.locator("#start").click()
            page.wait_for_function(
                "() => document.querySelector('#queue').textContent.includes('Transcribing')"
            )
            page.locator("#cancel").click()
            page.wait_for_function("() => document.querySelector('#cancel').hidden")
            assert len(jobs) == 3
            assert ("DELETE", "/api/jobs/3") in events
            page.locator("#clear").click()
            page.evaluate("""() => {
                const file = new File(['x'], 'too-big.wav', {type:'audio/wav'});
                Object.defineProperty(file, 'size', {value: 250*1048576+1});
                addFiles([file]);
            }""")
            assert "250 MiB" in page.locator("#notice").inner_text()
            assert page.locator("#queue li").count() == 0
            page.evaluate("""() => addFiles(Array.from({length:51},(_,i)=>
                new File(['x'],i+'.wav',{type:'audio/wav'})))""")
            assert "50 files" in page.locator("#notice").inner_text()
            page.locator("#clear").evaluate("(el) => el.disabled = false")
            page.locator("#clear").click()
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=output / "mobile.png", full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert not errors, errors
            context.close()
            browser.close()
        print("Browser checks passed: uploads, ACK, labels, ZIP CRC, cancel, limits, mobile.")
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
