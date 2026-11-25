"""Test servers for the probe: the exam site on :8767 (any 127.0.0.x) with
/redirect -> http://localhost:8768/final.html, and a 'CDN' on :8768."""
import functools
import http.server
import os
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "http://localhost:8768/final.html")
            self.end_headers()
            return
        super().do_GET()


def serve(port):
    handler = functools.partial(Handler, directory=HERE)
    http.server.ThreadingHTTPServer(("0.0.0.0", port), handler).serve_forever()


if __name__ == "__main__":
    for port in (8767, 8768):
        threading.Thread(target=serve, args=(port,), daemon=True).start()
    threading.Event().wait(int(sys.argv[1]) if len(sys.argv) > 1 else 120)
