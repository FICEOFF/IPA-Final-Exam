import json, os, logging
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from app.integration import process_request
from app.webex_client import WEBEX_API_BASE, WebexClient

LOGGER = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000

def _json_text(response):
    return json.dumps(response, separators=(",", ":"))

class WebexEventHandler:
    def __init__(self, client, bot_person_id, processor=None):
        self.client = client
        self.bot_person_id = bot_person_id
        self.processor = processor or process_request

    def _is_own(self, person_id):
        return bool(self.bot_person_id) and person_id == self.bot_person_id

    @staticmethod
    def _message_id(event):
        if not isinstance(event, dict):
            return None
        if event.get("resource") != "messages" or event.get("event") != "created":
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        message_id = data.get("id")
        if not isinstance(message_id, str) or not message_id:
            return None
        return message_id

    def _run_processor(self, mentioned_people, attachment_path):
        try:
            return self.processor(mentioned_people, attachment_path, self.bot_person_id)
        except Exception:
            LOGGER.exception("request processing failed")
            return {"status": "error", "result": "backend_failed"}

    def _build_response(self, message):
        mentioned_people = message.get("mentionedPeople")
        files = message.get("files") or []
        if len(files) > 1:
            return {"status": "error", "result": "multiple_attachments"}
        if not files:
            return self._run_processor(mentioned_people, None)
        with TemporaryDirectory() as directory:
            path = Path(directory) / "request.yaml"
            try:
                path.write_bytes(self.client.download_file(files[0]))
            except Exception:
                LOGGER.exception("attachment download failed")
                return {"status": "error", "result": "backend_failed"}
            return self._run_processor(mentioned_people, path)

    def handle_event(self, event):
        message_id = self._message_id(event)
        if message_id is None:
            return None
        if self._is_own(event["data"].get("personId")):
            return None
        message = self.client.get_message(message_id)
        if self._is_own(message.get("personId")):
            return None
        response = self._build_response(message)
        self.client.send_message(message["roomId"], _json_text(response))
        return response

def make_http_handler(submit_event):
    class WebhookHandler(BaseHTTPRequestHandler):
        def _send_json(self, status, body):
            payload = json.dumps(body).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _path(self):
            return self.path.split("?", 1)[0]

        def do_GET(self):
            if self._path() == "/health":
                self._send_json(200, {"status": "ok", "result": "healthy"})
            else:
                self._send_json(404, {"status": "error", "result": "not_found"})

        def do_POST(self):
            if self._path() != "/webhook":
                self._send_json(404, {"status": "error", "result": "not_found"})
                return
            invalid = {"status": "error", "result": "invalid_event"}
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = 0
            if not 1 <= length <= MAX_BODY_BYTES:
                self._send_json(400, invalid)
                return
            try:
                payload = json.loads(self.rfile.read(length))
            except (ValueError, RecursionError):
                self._send_json(400, invalid)
                return
            if not isinstance(payload, dict):
                self._send_json(400, invalid)
                return
            try:
                submit_event(payload)
            except Exception:
                LOGGER.exception("could not queue event")
                self._send_json(500, {"status": "error", "result": "backend_failed"})
                return
            self._send_json(200, {"status": "ok", "result": "accepted"})

        def log_message(self, format, *args):
            LOGGER.debug("%s - %s", self.address_string(), format % args)

    return WebhookHandler

def _resolve_bot_person_id(client):
    response = client.session.get(
        f"{WEBEX_API_BASE}/people/me",
        headers=client.headers,
        timeout=10
    )
    response.raise_for_status()
    return response.json()["id"]

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    client = WebexClient()
    bot_person_id = _resolve_bot_person_id(client)
    handler = WebexEventHandler(client, bot_person_id)
    executor = ThreadPoolExecutor(max_workers=1)

    def run(event):
        try:
            handler.handle_event(event)
        except Exception:
            LOGGER.exception("event handling failed")

    def submit_event(event):
        executor.submit(run, event)

    host = os.environ.get("WEBHOOK_HOST", "0.0.0.0")
    port = int(os.environ.get("WEBHOOK_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), make_http_handler(submit_event))
    LOGGER.info("webhook listening on %s:%s (bot %s)", host, port, bot_person_id)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        executor.shutdown(wait=False)

if __name__ == "__main__":
    main()
