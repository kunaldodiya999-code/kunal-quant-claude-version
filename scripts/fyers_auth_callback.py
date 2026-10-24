from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUTH_CODE_FILE = PROJECT_ROOT / "fyers_auth_code.txt"


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlparse(self.path).query)
        auth_code = query.get("auth_code", [None])[0]

        if auth_code:
            AUTH_CODE_FILE.write_text(auth_code, encoding="utf-8")

            print("\n" + "=" * 70)
            print("FYERS AUTH CODE RECEIVED")
            print("=" * 70)
            print(f"Saved to: {AUTH_CODE_FILE}")
            print("=" * 70)

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<h2>FYERS authentication successful.</h2>"
                b"<p>You can close this browser window.</p>"
            )
            return

        self.send_response(400)
        self.end_headers()
        self.wfile.write(b"Missing auth_code.")

    def log_message(self, format, *args):
        return


server = HTTPServer(("127.0.0.1", 8000), CallbackHandler)

print("=" * 70)
print("KUNAL QUANT — FYERS AUTH CALLBACK")
print("=" * 70)
print(f"Saving auth code to: {AUTH_CODE_FILE}")
print("Listening on http://127.0.0.1:8000")
print("Waiting for FYERS callback...")
print()

server.handle_request()
server.server_close()
