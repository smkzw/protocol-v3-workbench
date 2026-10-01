import http.server, functools, os

ROOT = os.path.dirname(os.path.abspath(__file__))

class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()

handler = functools.partial(H, directory=ROOT)
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 5397), handler)
srv.serve_forever()
