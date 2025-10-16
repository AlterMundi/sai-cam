#!/usr/bin/env python3
"""
Development server for SAI-Cam portal
Serves portal files locally and proxies API calls to remote server
Safe for testing without modifying production
"""

import http.server
import socketserver
import urllib.request
import urllib.error
import json
from urllib.parse import urlparse, parse_qs

# Configuration
PORTAL_DIR = 'src/portal'
REMOTE_API = 'http://saicam1.local:8090'  # Remote backend
LOCAL_PORT = 8080

class PortalProxyHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP handler that serves portal files and proxies API calls"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=PORTAL_DIR, **kwargs)

    def do_GET(self):
        """Handle GET requests"""
        if self.path.startswith('/api/'):
            self.proxy_request('GET')
        else:
            # Serve static files from portal directory
            super().do_GET()

    def do_POST(self):
        """Handle POST requests"""
        if self.path.startswith('/api/'):
            self.proxy_request('POST')
        else:
            self.send_error(405, "Method Not Allowed")

    def proxy_request(self, method):
        """Proxy API requests to remote server"""
        try:
            # Build remote URL
            remote_url = f"{REMOTE_API}{self.path}"

            print(f"[PROXY] {method} {self.path} -> {remote_url}")

            # Prepare request
            req = urllib.request.Request(remote_url, method=method)

            # Copy headers (except Host)
            for header, value in self.headers.items():
                if header.lower() not in ['host', 'connection']:
                    req.add_header(header, value)

            # For POST requests, read and forward body
            if method == 'POST':
                content_length = int(self.headers.get('Content-Length', 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)
                    req.data = body

            # Make request to remote server
            try:
                with urllib.request.urlopen(req, timeout=10) as response:
                    # Send response
                    self.send_response(response.status)

                    # Copy response headers
                    for header, value in response.headers.items():
                        if header.lower() not in ['connection', 'transfer-encoding']:
                            self.send_header(header, value)
                    self.end_headers()

                    # Copy response body
                    self.wfile.write(response.read())

                    print(f"[PROXY] ✓ {response.status} {self.path}")

            except urllib.error.HTTPError as e:
                # Forward HTTP errors
                self.send_response(e.code)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                error_body = e.read()
                self.wfile.write(error_body)
                print(f"[PROXY] ✗ {e.code} {self.path}")

        except Exception as e:
            print(f"[PROXY] ERROR: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            error_msg = json.dumps({'error': str(e)}).encode()
            self.wfile.write(error_msg)

    def log_message(self, format, *args):
        """Custom log format"""
        if not self.path.startswith('/api/'):
            print(f"[STATIC] {args[0]} {args[1]}")

def main():
    """Start development server"""
    print("=" * 60)
    print("SAI-Cam Portal Development Server")
    print("=" * 60)
    print(f"Local server:  http://localhost:{LOCAL_PORT}/")
    print(f"Remote API:    {REMOTE_API}")
    print(f"Portal files:  {PORTAL_DIR}/")
    print()
    print("SAFE MODE: Changes only affect your local browser")
    print("           No modifications to saicam1.local")
    print("=" * 60)
    print()
    print("Press Ctrl+C to stop")
    print()

    try:
        with socketserver.TCPServer(("", LOCAL_PORT), PortalProxyHandler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\nServer stopped")

if __name__ == '__main__':
    main()
