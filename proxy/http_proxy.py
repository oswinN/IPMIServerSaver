#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP Proxy Server for handling requests to the IPMI controlled server.

This module provides functionality to proxy HTTP requests to the target
server, handling server power state transitions transparently.
"""

import asyncio
import aiohttp
from aiohttp import web
import time
import sys
from urllib.parse import urlparse

from server.state_manager import ServerState
from .request_queue import RequestQueueManager


class HttpProxy:
    """
    HTTP proxy server that forwards requests to the target server.

    This class handles incoming HTTP requests, checks server state,
    queues requests when the server is not available, and forwards
    requests when the server is running.
    """

    def __init__(self, config, server_state_manager, inactivity_monitor=None, port_mapping=None):
        """
        Initialize the HTTP Proxy.

        Args:
            config (dict): Configuration dictionary
            server_state_manager (ServerStateManager): Server state manager instance
            inactivity_monitor (InactivityMonitor, optional): Inactivity monitor instance
            port_mapping (list, optional): A [proxy_port, target_port] pair. If None, uses first mapping from config.
        """
        self.config = config
        self.proxy_host = config.get('proxy_host', '0.0.0.0')

        # Use the specified port mapping and return error if not provided
        if port_mapping is None:
            raise ValueError("ERROR: in HttpProxy __init__ : Port mapping must be provided to HttpProxy")

        self.proxy_port = port_mapping[0]
        self.target_host = config['target_host']
        self.target_port = port_mapping[1]
        self.target_url = f"http://{self.target_host}:{self.target_port}"

        self.server_state_manager = server_state_manager
        self.inactivity_monitor = inactivity_monitor

        # Create request queue manager
        self.request_queue = RequestQueueManager(config)

        # Create HTTP client session for forwarding requests
        self.client_session = None

    async def start(self):
        """
        Start the HTTP proxy server.

        Returns:
            web.AppRunner: The running application
        """
        app = web.Application(middlewares=[self.middleware_handler])
        app.router.add_route('*', '/{path:.*}', self.handle_request)

        # Create a shared client session
        self.client_session = aiohttp.ClientSession()

        # Create runner
        runner = web.AppRunner(app)
        await runner.setup()

        # Create site
        site = web.TCPSite(runner, self.proxy_host, self.proxy_port)

        # Start site
        await site.start()
        print(f"HTTP proxy server running on http://{self.proxy_host}:{self.proxy_port} -> {self.target_host}:{self.target_port}")

        return runner

    async def stop(self):
        """Stop the HTTP proxy server and clean up resources."""
        if self.client_session:
            await self.client_session.close()

    @web.middleware
    async def middleware_handler(self, request, handler):
        """
        Middleware to handle all incoming requests.

        This middleware extracts common functionality for all routes.

        Args:
            request: The incoming HTTP request
            handler: The route handler function

        Returns:
            Response: The HTTP response
        """
        try:
            # Update activity timestamp if monitor is available
            if self.inactivity_monitor:
                self.inactivity_monitor.update_activity()

            # Handle the request
            return await handler(request)

        except web.HTTPException:
            # Let aiohttp HTTP exceptions pass through
            raise

        except Exception as e:
            print(f"Error in HTTP proxy middleware: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return web.Response(
                status=500,
                text=f"Internal Server Error: {str(e)}"
            )

    async def handle_request(self, request):
        """
        Handle an incoming HTTP request.

        This method:
        1. Checks the server state
        2. If the server is running, forwards the request directly
        3. If the server is not running, queues the request and starts the server
        4. If the server is in transition, queues the request

        Args:
            request: The incoming HTTP request

        Returns:
            Response: The HTTP response
        """
        # Get current server state
        server_state = await self.server_state_manager.get_server_state()

        if server_state == ServerState.RUNNING:
            # Server is running, forward request directly
            return await self.forward_request(request)

        elif server_state in [ServerState.STOPPED, ServerState.UNKNOWN]:
            # Server is not running, queue request and start server
            print(f"Server is {server_state.value}, queueing request and starting server...")

            # Create a future for this request
            future = asyncio.Future()

            # Add request to queue
            await self.request_queue.add_request(request, future)

            # Start the server (this is non-blocking)
            asyncio.create_task(self._handle_server_startup())

            # Wait for the request to be processed (this will block until the future is resolved)
            try:
                return await future
            except Exception as e:
                return web.Response(
                    status=500,
                    text=f"Error processing request: {str(e)}"
                )

        else:  # STARTING or STOPPING
            # Server is in transition, queue request
            print(f"Server is {server_state.value}, queueing request...")

            # Create a future for this request
            future = asyncio.Future()

            # Add request to queue
            await self.request_queue.add_request(request, future)

            # Wait for the request to be processed (this will block until the future is resolved)
            try:
                return await future
            except Exception as e:
                return web.Response(
                    status=500,
                    text=f"Error processing request: {str(e)}"
                )

    async def forward_request(self, request):
        """
        Forward an HTTP request to the target server.

        Args:
            request: The HTTP request to forward

        Returns:
            Response: The HTTP response from the target server
        """
        # Reconstruct the target URL
        path = request.path
        query_string = request.query_string
        url = f"{self.target_url}{path}"
        if query_string:
            url = f"{url}?{query_string}"

        # Get request method, headers, and body
        method = request.method
        headers = dict(request.headers)
        # Remove hop-by-hop headers
        hop_by_hop_headers = ['Connection', 'Keep-Alive', 'Proxy-Authenticate',
                              'Proxy-Authorization', 'TE', 'Trailers',
                              'Transfer-Encoding', 'Upgrade']
        for header in hop_by_hop_headers:
            if header in headers:
                del headers[header]

        # Set the Host header to the target host
        headers['Host'] = f"{self.target_host}:{self.target_port}"

        # Get client IP
        client_ip = request.remote
        headers['X-Forwarded-For'] = client_ip
        headers['X-Forwarded-Host'] = request.host
        headers['X-Forwarded-Proto'] = request.scheme

        try:
            # Read request body if it exists
            body = None
            if request.body_exists:
                body = await request.read()

            # Forward the request to the target server
            async with self.client_session.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                allow_redirects=False,
                timeout=60
            ) as response:
                # Read response
                response_body = await response.read()

                # Create response
                headers = dict(response.headers)

                # Return the response
                return web.Response(
                    status=response.status,
                    headers=headers,
                    body=response_body
                )

        except asyncio.TimeoutError:
            return web.Response(
                status=504,
                text="Gateway Timeout: Target server took too long to respond"
            )

        except aiohttp.ClientError as e:
            return web.Response(
                status=502,
                text=f"Bad Gateway: Error communicating with target server: {str(e)}"
            )

        except Exception as e:
            print(f"Error forwarding request: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return web.Response(
                status=500,
                text=f"Internal Server Error: {str(e)}"
            )

    async def _handle_server_startup(self):
        """
        Handle server startup and process queued requests when ready.

        This method is called when a request is received while the server is stopped.
        It starts the server and processes queued requests once the server is running.
        """
        try:
            # Start the server
            start_result = await self.server_state_manager.start_server()

            if start_result:
                # Server started successfully, process queued requests
                print("Server started successfully, processing queued requests...")
                await self.request_queue.process_queued_requests(self.forward_request)
            else:
                # Server failed to start, clear request queue with error
                print("Server failed to start, clearing request queue...")
                self.request_queue.clear_queue("Server failed to start")

        except Exception as e:
            # Server failed to start, clear request queue with error
            print(f"Error starting server: {e}", file=sys.stderr)
            self.request_queue.clear_queue(f"Error starting server: {str(e)}")


# Example usage
if __name__ == "__main__":
    import os
    from server.state_manager import ServerStateManager

    async def test_http_proxy():
        """Test the HTTP Proxy."""
        # Create a minimal config from environment variables
        proxy_port = int(os.environ.get('PROXY_PORT', 8080))
        target_port = int(os.environ.get('TARGET_PORT', 80))

        config = {
            'port_mappings': [[proxy_port, target_port]],
            'target_host': os.environ.get('TARGET_HOST', 'localhost'),
            'ipmi_host': os.environ.get('IPMI_HOST', ''),
            'ipmi_user': os.environ.get('IPMI_USER', ''),
            'ipmi_password': os.environ.get('IPMI_PASSWORD', '')
        }

        if not all([config['target_host'], config['ipmi_host'], config['ipmi_user'], config['ipmi_password']]):
            print("Missing required configuration. Please set TARGET_HOST, IPMI_HOST, IPMI_USER, and IPMI_PASSWORD environment variables.")
            sys.exit(1)

        # Create server state manager
        server_state_manager = ServerStateManager(config)

        # Create HTTP proxy with the port mapping
        http_proxy = HttpProxy(config, server_state_manager, port_mapping=config['port_mappings'][0])

        # Start the proxy server
        runner = await http_proxy.start()

        # Keep the server running
        try:
            print("HTTP proxy server started. Press Ctrl+C to stop...")
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
        finally:
            await http_proxy.stop()
            await runner.cleanup()

    # Run the test function
    asyncio.run(test_http_proxy())