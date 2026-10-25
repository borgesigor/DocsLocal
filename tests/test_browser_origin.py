"""Opt-in real Chromium check using only temporary data and loopback servers."""
import os
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import uvicorn

from app import main
from app.services import project_service as projects


@unittest.skipUnless(os.environ.get('DOCS_LOCAL_TEST_BROWSER'), 'Set DOCS_LOCAL_TEST_BROWSER to a Chromium executable.')
class BrowserOriginTests(unittest.TestCase):
    def test_cross_port_simple_browser_request_cannot_write(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as temporary:
            root = Path(temporary)
            projects_root = root / 'projects'
            with patch.object(projects, 'PROJECTS', projects_root):
                project_id = projects.create_project('Browser origin')['id']
                self.verify_browser_request(root, projects_root / project_id)

    def verify_browser_request(self, root, project_folder):
        statuses = []

        async def observed_app(scope, receive, send):
            async def observe_response(message):
                if message['type'] == 'http.response.start' and scope['method'] == 'POST':
                    statuses.append(message['status'])
                await send(message)
            await main.app(scope, receive, observe_response)

        api_socket = socket.socket()
        api_socket.bind(('127.0.0.1', 0))
        api_port = api_socket.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(observed_app, lifespan='off', log_level='error'))
        api_thread = threading.Thread(target=lambda: server.run(sockets=[api_socket]), daemon=True)
        completed = threading.Event()
        project_id = project_folder.name
        page = f'''<!doctype html><title>Origin regression</title><body>Running<script>
        (async () => {{
          await fetch('http://127.0.0.1:{api_port}/api/v1/projects/{project_id}/folders', {{
            method: 'POST', mode: 'no-cors', headers: {{'Content-Type': 'text/plain'}},
            body: JSON.stringify({{path: 'docs/foreign-port'}})
          }});
          document.body.textContent = 'Browser request completed';
          await fetch('/done');
        }})().catch(error => document.body.textContent = String(error));
        </script></body>'''.encode()

        class ProbePage(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/done':
                    completed.set()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html')
                self.end_headers()
                self.wfile.write(page if self.path != '/done' else b'OK')

            def log_message(self, *_):
                pass

        page_server = ThreadingHTTPServer(('127.0.0.1', 0), ProbePage)
        page_thread = threading.Thread(target=page_server.serve_forever, daemon=True)
        api_thread.start()
        page_thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(server.started, 'Isolated API server failed to start')
            subprocess.run([
                os.environ['DOCS_LOCAL_TEST_BROWSER'], '--headless=new', '--disable-gpu',
                '--no-first-run', '--no-default-browser-check', '--disable-background-networking',
                f'--user-data-dir={root / "browser-profile"}', '--dump-dom',
                '--virtual-time-budget=5000', f'http://127.0.0.1:{page_server.server_port}/',
            ], capture_output=True, timeout=30, check=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.assertTrue(completed.wait(5), 'Browser did not finish its request')
            self.assertEqual(statuses, [403])
            self.assertFalse((project_folder / 'docs/foreign-port').exists())
        finally:
            server.should_exit = True
            api_thread.join(timeout=10)
            api_socket.close()
            page_server.shutdown()
            page_server.server_close()
            page_thread.join(timeout=5)
