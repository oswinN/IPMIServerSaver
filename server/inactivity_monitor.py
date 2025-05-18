#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Inactivity Monitor for tracking server activity and managing automatic shutdown.

This module provides functionality to track when the server was last active
and automatically shut it down after a configurable period of inactivity.
"""

import asyncio
import time
import sys


class InactivityMonitor:
    """
    Monitor server activity and shut down the server after inactivity.

    This class tracks the timestamp of the last server activity and
    periodically checks if the inactivity threshold has been exceeded.
    When the threshold is reached, it triggers a server shutdown.
    """

    def __init__(self, config, server_state_manager):
        """
        Initialize the Inactivity Monitor.

        Args:
            config (dict): Configuration dictionary
            server_state_manager (ServerStateManager): Server state manager instance
        """
        self.config = config
        self.server_state_manager = server_state_manager
        self.inactivity_timeout = config.get('inactivity_timeout', 3600)  # 1 hour default
        self.check_interval = config.get('check_interval', 60)  # 1 minute default

        # Initialize activity timestamp
        self.last_activity_time = time.time()

        # Monitoring task
        self._monitoring_task = None
        self._running = False
        self._lock = asyncio.Lock()

    def update_activity(self):
        """Update the last activity timestamp to the current time."""
        self.last_activity_time = time.time()

    async def start_monitoring(self):
        """
        Start the inactivity monitoring task.

        Returns:
            bool: True if monitoring was started, False if already running
        """
        async with self._lock:
            if self._running:
                print("Inactivity monitoring already running")
                return False

            self._running = True

        # Start the monitoring task
        self._monitoring_task = asyncio.create_task(self._monitor_activity())
        print(f"Inactivity monitoring started (timeout: {self.inactivity_timeout}s, check interval: {self.check_interval}s)")
        return True

    async def stop_monitoring(self):
        """
        Stop the inactivity monitoring task.

        Returns:
            bool: True if monitoring was stopped, False if not running
        """
        async with self._lock:
            if not self._running:
                print("Inactivity monitoring not running")
                return False

            self._running = False

            # Cancel the monitoring task if it exists
            if self._monitoring_task and not self._monitoring_task.done():
                self._monitoring_task.cancel()
                try:
                    await self._monitoring_task
                except asyncio.CancelledError:
                    pass

            self._monitoring_task = None

        print("Inactivity monitoring stopped")
        return True

    async def _monitor_activity(self):
        """
        Monitor server activity and shut down when inactive.

        This method runs in a loop, periodically checking if the
        server has been inactive for longer than the inactivity threshold.
        When the threshold is exceeded, it triggers a server shutdown.
        """
        try:
            while self._running:
                # Check inactivity
                await self._check_inactivity()

                # Wait before checking again
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            # Task was cancelled, clean up
            print("Inactivity monitoring task cancelled")

        except Exception as e:
            print(f"Error in inactivity monitoring: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()

    async def _check_inactivity(self):
        """
        Check if the server has been inactive for longer than the threshold.

        If the inactivity threshold has been exceeded, this method
        will trigger a server shutdown.
        """
        current_time = time.time()
        inactive_time = current_time - self.last_activity_time

        # Log every 10 minutes for debugging
        if inactive_time > 0 and int(inactive_time) % 600 == 0:
            print(f"Server has been inactive for {inactive_time:.1f} seconds")

        # If inactive for longer than the threshold, shut down the server
        if inactive_time > self.inactivity_timeout:
            print(f"Server has been inactive for {inactive_time:.1f} seconds, exceeding threshold of {self.inactivity_timeout} seconds")
            print("Shutting down server due to inactivity...")

            # Update timestamp to prevent multiple shutdown attempts
            self.update_activity()

            try:
                # Trigger server shutdown
                await self.server_state_manager.stop_server(force=False)
                print("Server shut down successfully due to inactivity")

            except Exception as e:
                print(f"Error shutting down server: {e}", file=sys.stderr)
                # Reset the timestamp to try again later if shutdown failed
                self.last_activity_time = current_time - self.inactivity_timeout + 300  # Try again in 5 minutes


# Example usage
if __name__ == "__main__":
    import os
    from server.state_manager import ServerStateManager

    async def test_inactivity_monitor():
        """Test the Inactivity Monitor."""
        # Create a minimal config from environment variables
        config = {
            'target_host': os.environ.get('TARGET_HOST', 'localhost'),
            'ipmi_host': os.environ.get('IPMI_HOST', ''),
            'ipmi_user': os.environ.get('IPMI_USER', ''),
            'ipmi_password': os.environ.get('IPMI_PASSWORD', ''),
            'inactivity_timeout': 10,  # 10 seconds for testing
            'check_interval': 2  # 2 seconds for testing
        }

        if not all([config['target_host'], config['ipmi_host'], config['ipmi_user'], config['ipmi_password']]):
            print("Missing required configuration. Please set TARGET_HOST, IPMI_HOST, IPMI_USER, and IPMI_PASSWORD environment variables.")
            sys.exit(1)

        # Create server state manager
        server_state_manager = ServerStateManager(config)

        # Create inactivity monitor
        monitor = InactivityMonitor(config, server_state_manager)

        # Start monitoring
        await monitor.start_monitoring()

        # Simulate some activity and inactivity
        print("Simulating activity...")
        monitor.update_activity()

        try:
            # Keep running for a while to observe inactivity detection
            print("Waiting for inactivity timeout...")
            # Wait a bit longer than the timeout to make sure it triggers
            await asyncio.sleep(config['inactivity_timeout'] + 5)

            # This should have triggered a shutdown attempt

            # Update activity again to prevent another shutdown
            print("Updating activity timestamp...")
            monitor.update_activity()

            # Wait a bit more
            await asyncio.sleep(5)

        finally:
            # Stop monitoring
            await monitor.stop_monitoring()

    # Run the test function
    asyncio.run(test_inactivity_monitor())