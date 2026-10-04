import http.server, socketserver, os
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()
    def log_message(self, fmt, *args):
        print("SERVED:", fmt % args, flush=True)
with socketserver.TCPServer(("127.0.0.1", 5397), H) as httpd:
    httpd.serve_forever()
