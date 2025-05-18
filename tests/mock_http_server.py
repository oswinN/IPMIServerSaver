#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock HTTP Server for testing the IPMI Server Saver

This script provides a simple HTTP server that can be used alongside the
mock IPMI tool to test the full functionality of the smartproxy application
without requiring real hardware.

It supports:
- Serving basic HTTP requests
- Logging received requests
- Configurable response behavior
- Starting and stopping via command line
"""

import os
import sys
import time
import json
import argparse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from functools import partial
import signal


# Store received requests for inspection
received_requests = []
server_instance = None


class MockHTTPRequestHandler(BaseHTTPRequestHandler):
    """
    Request handler for the mock HTTP server.

    This handler logs all incoming requests and returns configurable responses.
    """

    def __init__(self, response_code, response_delay, response_body, *args, **kwargs):
        self.response_code = response_code
        self.response_delay = response_delay
        self.response_body = response_body
        # Initialize the parent class (required for the handler)
        super().__init__(*args, **kwargs)

    def _handle_request(self, method):
        """Common handler for all request types."""
        global received_requests

        # Get request details
        request_path = self.path
        request_headers = {key: value for key, value in self.headers.items()}

        # Get request body if present
        content_length = int(self.headers.get('Content-Length', 0))
        request_body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""

        # Create request record and add to received requests
        request_record = {
            'method': method,
            'path': request_path,
            'headers': request_headers,
            'body': request_body,
            'time': time.time()
        }
        received_requests.append(request_record)

        # Log request
        print(f"Received {method} request for {request_path}")

        # Simulate processing delay if configured
        if self.response_delay > 0:
            time.sleep(self.response_delay)

        # Send response
        self.send_response(self.response_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Server', 'MockHTTPServer')
        self.end_headers()

        # Add request details to response if echo is enabled
        if "echo" in self.response_body:
            response_data = {
                "status": "success",
                "message": "Request received",
                "request": request_record
            }
            response = json.dumps(response_data).encode('utf-8')
        else:
            response = self.response_body.encode('utf-8')

        self.wfile.write(response)

    def do_GET(self):
        """Handle GET requests."""
        self._handle_request('GET')

    def do_POST(self):
        """Handle POST requests."""
        self._handle_request('POST')

    def do_PUT(self):
        """Handle PUT requests."""
        self._handle_request('PUT')

    def do_DELETE(self):
        """Handle DELETE requests."""
        self._handle_request('DELETE')

    def do_HEAD(self):
        """Handle HEAD requests."""
        self._handle_request('HEAD')

    def do_OPTIONS(self):
        """Handle OPTIONS requests."""
        self._handle_request('OPTIONS')

    def log_message(self, format, *args):
        """Override to control server logging."""
        if self.server.verbose:
            # Call standard logger if verbose is enabled
            super().log_message(format, *args)


def start_server(port=8000, response_code=200, response_delay=0,
                response_body='{"status":"ok"}', verbose=True):
    """
    Start the mock HTTP server.

    Args:
        port (int): The port to listen on
        response_code (int): HTTP response code to return
        response_delay (float): Delay in seconds before responding
        response_body (str): Response body to return
        verbose (bool): Whether to log detailed request info

    Returns:
        tuple: (server, thread) - The server instance and thread
    """
    global server_instance

    # Create handler with configured responses
    handler = partial(
        MockHTTPRequestHandler,
        response_code,
        response_delay,
        response_body
    )

    # Create server
    server = HTTPServer(('0.0.0.0', port), handler)
    server.verbose = verbose

    # Save server instance for shutdown
    server_instance = server

    # Create thread to run server
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True

    # Start server
    print(f"Starting mock HTTP server on port {port}")
    print(f"Response code: {response_code}")
    print(f"Response delay: {response_delay}s")
    print(f"Response body: {response_body}")
    server_thread.start()

    return server, server_thread


def stop_server(server=None):
    """
    Stop the mock HTTP server.

    Args:
        server (HTTPServer, optional): Server to stop. If None, uses global instance.
    """
    global server_instance

    server_to_stop = server or server_instance
    if server_to_stop:
        print("Stopping mock HTTP server")
        server_to_stop.shutdown()
        server_to_stop.server_close()
        print("Server stopped")
    else:
        print("No server to stop")


def print_received_requests():
    """Print a summary of all received requests."""
    global received_requests

    if not received_requests:
        print("No requests received")
        return

    print(f"\nReceived {len(received_requests)} requests:")
    for i, req in enumerate(received_requests):
        timestamp = time.strftime('%H:%M:%S', time.localtime(req['time']))
        print(f"{i+1}. [{timestamp}] {req['method']} {req['path']}")


def handle_signal(signum, frame):
    """Signal handler for graceful shutdown."""
    print(f"\nReceived signal {signum}, shutting down...")
    print_received_requests()
    stop_server()
    sys.exit(0)


def main():
    """Main entry point to run the server from command line."""
    parser = argparse.ArgumentParser(description='Mock HTTP Server for testing')

    parser.add_argument(
        '-p', '--port',
        type=int,
        default=8000,
        help='Port to listen on (default: 8000)'
    )

    parser.add_argument(
        '-c', '--code',
        type=int,
        default=200,
        help='HTTP response code (default: 200)'
    )

    parser.add_argument(
        '-d', '--delay',
        type=float,
        default=0,
        help='Response delay in seconds (default: 0)'
    )

    parser.add_argument(
        '-b', '--body',
        default='{"status":"ok"}',
        help='Response body (default: {"status":"ok"})'
    )

    parser.add_argument(
        '-e', '--echo',
        action='store_true',
        help='Echo request details in response'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress detailed request logging'
    )

    args = parser.parse_args()

    # If echo is enabled, override response body
    if args.echo:
        args.body = "echo"

    # Set up signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        # Start server
        server, thread = start_server(
            port=args.port,
            response_code=args.code,
            response_delay=args.delay,
            response_body=args.body,
            verbose=not args.quiet
        )

        # Print server info
        print(f"Mock HTTP server running on port {args.port}")
        print("Press Ctrl+C to stop the server and see request summary")

        # Keep main thread alive until interrupted
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nShutting down...")
        print_received_requests()
        stop_server()

    except Exception as e:
        print(f"Error: {e}")
        stop_server()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())