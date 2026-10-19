import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv
from fyers_apiv3 import fyersModel


# ============================================================
# KUNAL QUANT
# FYERS API V3 AUTHENTICATION
# ============================================================

load_dotenv()

CLIENT_ID = os.getenv("FYERS_CLIENT_ID")
SECRET_KEY = os.getenv("FYERS_SECRET_KEY")
REDIRECT_URI = os.getenv(
    "FYERS_REDIRECT_URI",
    "http://127.0.0.1:8000"
)

HOST = "127.0.0.1"
PORT = 8000
STATE = "kunal_quant"

auth_code_received = None
received_state = None
auth_error = None


class CallbackHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        global auth_code_received
        global received_state
        global auth_error

        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        auth_code_received = params.get("auth_code", [None])[0]
        received_state = params.get("state", [None])[0]

        auth_error = params.get("s", [None])[0]

        if auth_code_received:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            html = """
            <!DOCTYPE html>
            <html>
            <head>
                <title>Kunal Quant - FYERS</title>
            </head>
            <body>
                <h2>FYERS authentication received.</h2>
                <p>You can close this browser tab and return to VS Code.</p>
            </body>
            </html>
            """

            self.wfile.write(html.encode("utf-8"))

        else:
            self.send_response(400)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"""
                <h2>FYERS authentication failed.</h2>
                <p>No auth_code was received.</p>
                """
            )

    def log_message(self, format, *args):
        return


def main():

    if not CLIENT_ID or not SECRET_KEY:
        print("ERROR: FYERS credentials are missing from .env")
        return

    print("=" * 65)
    print("KUNAL QUANT - FYERS API V3 AUTHENTICATION")
    print("=" * 65)

    print("\nApp ID:", CLIENT_ID)
    print("Redirect URI:", REDIRECT_URI)

    session = fyersModel.SessionModel(
        client_id=CLIENT_ID,
        secret_key=SECRET_KEY,
        redirect_uri=REDIRECT_URI,
        response_type="code",
        grant_type="authorization_code",
        state=STATE
    )

    print("\nGenerating FYERS login URL...")

    auth_url = session.generate_authcode()

    print("Login URL generated.")
    print("Starting local callback server...")

    server = HTTPServer(
        (HOST, PORT),
        CallbackHandler
    )

    print(f"Listening on http://{HOST}:{PORT}")
    print("\nOpening FYERS login page...")

    webbrowser.open(auth_url, new=1)

    print("\nComplete FYERS login and 2FA in the browser.")
    print("Waiting for callback...")

    while auth_code_received is None:
        server.handle_request()

    server.server_close()

    if received_state and received_state != STATE:
        print("\nERROR: State validation failed.")
        print("Expected:", STATE)
        print("Received:", received_state)
        return

    print("\nAuth code received successfully.")

    session.set_token(auth_code_received)

    print("Generating access token...")

    response = session.generate_token()

    print("\nFYERS TOKEN RESPONSE:")
    print("Status :", response.get("s"))
    print("Code   :", response.get("code"))
    print("Message:", response.get("message"))

    access_token = response.get("access_token")

    if not access_token:
        print("\nACCESS TOKEN GENERATION FAILED.")
        print("Full response:")
        print(response)
        return

    with open(
        "fyers_access_token.txt",
        "w",
        encoding="utf-8"
    ) as file:
        file.write(access_token)

    print("\n" + "=" * 65)
    print("SUCCESS")
    print("=" * 65)
    print("FYERS access token generated successfully.")
    print("Saved locally as: fyers_access_token.txt")
    print("=" * 65)


if __name__ == "__main__":
    main()