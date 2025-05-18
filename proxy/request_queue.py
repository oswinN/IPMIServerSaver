#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Request Queue Manager for handling requests during server transitions.

This module provides functionality to queue HTTP requests while the
server is starting up or in transition, then process them once the
server becomes available.
"""

import asyncio
import time
import sys


class RequestQueueManager:
    """
    Manage queued requests while the server is starting up.

    This class stores pending requests in an async queue and processes
    them when the server becomes available.
    """

    def __init__(self, config, max_queue_size=None):
        """
        Initialize the Request Queue Manager.

        Args:
            config (dict): Configuration dictionary
            max_queue_size (int, optional): Maximum number of requests to queue.
                If None, uses the value from config or defaults to 1000.
        """
        self.config = config
        self.max_queue_size = max_queue_size or config.get('max_queue_size', 1000)
        self.request_queue = asyncio.Queue(maxsize=self.max_queue_size)
        self.request_timeout = config.get('request_timeout', 60)  # 60 seconds default

    async def add_request(self, request, future):
        """
        Add a request to the queue.

        Args:
            request: The HTTP request to queue
            future: An asyncio.Future that will be completed when the request is processed

        Returns:
            bool: True if the request was added to the queue, False otherwise

        Raises:
            asyncio.QueueFull: If the queue is full and cannot accept more requests
        """
        try:
            # Create a request entry with timestamp and future
            request_entry = {
                'request': request,
                'future': future,
                'timestamp': time.time()
            }

            # Add to queue with a timeout
            await asyncio.wait_for(
                self.request_queue.put(request_entry),
                timeout=5
            )

            print(f"Request queued. Queue size: {self.request_queue.qsize()}/{self.max_queue_size}")
            return True

        except asyncio.QueueFull:
            print("Request queue is full, rejecting request", file=sys.stderr)
            future.set_exception(Exception("Server is busy, request queue is full"))
            return False

        except asyncio.TimeoutError:
            print("Timeout adding request to queue", file=sys.stderr)
            future.set_exception(Exception("Server is busy, timed out adding request to queue"))
            return False

        except Exception as e:
            print(f"Error adding request to queue: {e}", file=sys.stderr)
            future.set_exception(Exception(f"Failed to queue request: {e}"))
            return False

    async def process_queued_requests(self, processor_func):
        """
        Process all queued requests.

        Args:
            processor_func: A callable that processes a request and returns a response
                This function should accept a request object as its argument.

        Returns:
            int: Number of requests processed
        """
        processed_count = 0
        failed_count = 0
        expired_count = 0

        # Get current queue size (may change during processing)
        initial_queue_size = self.request_queue.qsize()
        if initial_queue_size == 0:
            return 0

        print(f"Processing {initial_queue_size} queued requests...")

        # Process all requests currently in the queue
        while not self.request_queue.empty():
            try:
                # Get the next request from the queue
                entry = await self.request_queue.get()
                request = entry['request']
                future = entry['future']
                timestamp = entry['timestamp']

                # Check if the request has expired
                if time.time() - timestamp > self.request_timeout:
                    print(f"Request expired after {self.request_timeout} seconds, not processing")
                    future.set_exception(Exception("Request expired while waiting for server to start"))
                    self.request_queue.task_done()
                    expired_count += 1
                    continue

                # Process the request
                try:
                    response = await processor_func(request)
                    future.set_result(response)
                    processed_count += 1
                except Exception as e:
                    print(f"Error processing queued request: {e}", file=sys.stderr)
                    future.set_exception(e)
                    failed_count += 1

                # Mark the task as done
                self.request_queue.task_done()

            except Exception as e:
                print(f"Unexpected error processing queue: {e}", file=sys.stderr)
                failed_count += 1

        print(f"Queue processing complete. Processed: {processed_count}, Failed: {failed_count}, Expired: {expired_count}")
        return processed_count

    def get_queue_length(self):
        """
        Get the current number of requests in the queue.

        Returns:
            int: Number of requests currently in the queue
        """
        return self.request_queue.qsize()

    def is_queue_empty(self):
        """
        Check if the request queue is empty.

        Returns:
            bool: True if the queue is empty, False otherwise
        """
        return self.request_queue.empty()

    def clear_queue(self, error_message="Request cancelled due to server shutdown"):
        """
        Clear the request queue and fail all pending requests.

        Args:
            error_message (str, optional): Error message to set for all pending requests.
                Defaults to "Request cancelled due to server shutdown".

        Returns:
            int: Number of requests cleared from the queue
        """
        cleared_count = 0

        # Process all requests currently in the queue
        while not self.request_queue.empty():
            try:
                # Get the next request from the queue without waiting
                entry = self.request_queue.get_nowait()
                future = entry['future']

                # Fail the request with the provided error message
                future.set_exception(Exception(error_message))
                self.request_queue.task_done()
                cleared_count += 1

            except asyncio.QueueEmpty:
                # Queue emptied while we were processing
                break

            except Exception as e:
                print(f"Error clearing queue: {e}", file=sys.stderr)

        print(f"Queue cleared. {cleared_count} requests cancelled.")
        return cleared_count


# Example usage
if __name__ == "__main__":
    import aiohttp

    async def test_queue_manager():
        """Test the Request Queue Manager."""
        # Create a minimal config
        config = {'max_queue_size': 10, 'request_timeout': 30}

        # Create request queue manager
        queue_manager = RequestQueueManager(config)

        # Create some test requests
        async def create_test_request(index):
            """Create a test request and add it to the queue."""
            # Create a dummy request
            request = {'path': f"/test/{index}", 'method': 'GET'}

            # Create a future for this request
            future = asyncio.Future()

            # Add to queue
            await queue_manager.add_request(request, future)

            return future

        # Create and queue 5 test requests
        futures = []
        for i in range(5):
            future = await create_test_request(i)
            futures.append(future)

        # Define a processor function for testing
        async def process_request(request):
            """Example processor that just echoes the request."""
            print(f"Processing request to {request['path']}")
            await asyncio.sleep(0.1)  # Simulate processing time
            return {'status': 200, 'body': f"Response to {request['path']}"}

        # Process the queued requests
        await queue_manager.process_queued_requests(process_request)

        # Wait for all futures to complete and print results
        for i, future in enumerate(futures):
            try:
                result = await future
                print(f"Request {i} result: {result}")
            except Exception as e:
                print(f"Request {i} error: {e}")

    # Run the test function
    asyncio.run(test_queue_manager())