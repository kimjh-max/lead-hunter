"""데모 사이트 서버."""
import http.server
import os
import sys

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8601
directory = sys.argv[2] if len(sys.argv) > 2 else "demo-sites/meetup-matcher"

os.chdir(directory)
handler = http.server.SimpleHTTPRequestHandler
with http.server.HTTPServer(("", port), handler) as httpd:
    print(f"Serving {directory} on port {port}")
    httpd.serve_forever()
