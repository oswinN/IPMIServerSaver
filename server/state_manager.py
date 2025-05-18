#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Server State Manager for tracking and controlling IPMI server state.

This module provides functionality to track the current state of the server,
coordinate power operations, and handle state transitions.
"""

import asyncio
import enum
import socket
import time
import sys
from .ipmi_controller import IpmiController


class ServerState(enum.Enum):
    """Enumeration of possible server states."""
    UNKNOWN = "unknown"
    RUNNING = "running"
    STOPPED = "stopped"
    STARTING = "starting"
    STOPPING = "stopping"


class ServerStateManager:
    """
    Manages the state of the target server and coordinates power operations.

    This class tracks the current server state, initiates state transitions,
    and provides methods to start and stop the server as needed.
    """

    def __init__(self, config, ipmi_controller=None):
        """
        Initialize the Server State Manager.

        Args:
            config (dict): Configuration dictionary with server settings
            ipmi_controller (IpmiController, optional): An existing IPMI controller instance.
                If not provided, one will be created using the config.
        """
        self.config = config
        self.target_host = config['target_host']

        # Get the first target port from port mappings for compatibility
        # or use default port 80 if no port mappings are provided
        if 'port_mappings' in config and config['port_mappings']:
            self.primary_target_port = config['port_mappings'][0][1]  # Use the first mapping's target port
        else:
            self.primary_target_port = 80  # Default if no mapping exists
        self.startup_timeout = config.get('startup_timeout', 300)  # 5 minutes default
        self.check_interval = config.get('check_interval', 5)  # 5 seconds default

        # Create IPMI controller if not provided
        if ipmi_controller is None:
            self.ipmi = IpmiController(
                config['ipmi_host'],
                config['ipmi_user'],
                config['ipmi_password']
            )
        else:
            self.ipmi = ipmi_controller

        # Initialize state
        self.current_state = ServerState.UNKNOWN
        self._startup_in_progress = False
        self._shutdown_in_progress = False
        self._state_lock = asyncio.Lock()

    async def get_server_state(self):
        """
        Get the current state of the server.

        If the current state is UNKNOWN, this will check the actual server
        status and update the internal state accordingly.

        Returns:
            ServerState: The current state of the server
        """
        async with self._state_lock:
            # If state is unknown, check the actual state
            if self.current_state == ServerState.UNKNOWN:
                # First check IPMI power status
                ipmi_status = await self.ipmi.get_power_status()

                if ipmi_status == "off":
                    self.current_state = ServerState.STOPPED
                else:
                    # If powered on according to IPMI, check if actually responding
                    is_running = await self._check_server_responding()
                    self.current_state = ServerState.RUNNING if is_running else ServerState.STOPPED

            return self.current_state

    async def start_server(self):
        """
        Start the server if it's not already running.

        This method will:
        1. Check if the server is already running
        2. If not, send the power on command via IPMI
        3. Wait for the server to become responsive
        4. Update the server state

        Returns:
            bool: True if the server was successfully started or was already running,
                  False otherwise
        """
        # Check if startup is already in progress
        # First get the server state without the lock
        current_state = await self.get_server_state()

        # Now acquire the lock to check and update state
        async with self._state_lock:
            # Re-check conditions that might have changed while waiting for the lock
            if self._startup_in_progress:
                print("Server startup already in progress")
                return True

            # We already have current_state from outside the lock
            if self.current_state == ServerState.RUNNING:
                print("Server is already running")
                return True

            if self.current_state == ServerState.STARTING:
                print("Server is already starting")
                return True

            # Set flags and state
            self._startup_in_progress = True
            self.current_state = ServerState.STARTING

        # Start the server
        try:
            print(f"Starting server at {self.target_host}...")
            power_on_result = await self.ipmi.power_on()

            if not power_on_result:
                print("Failed to send power on command", file=sys.stderr)
                async with self._state_lock:
                    self.current_state = ServerState.STOPPED
                    self._startup_in_progress = False
                return False

            # Wait for the server to become responsive with timeout
            server_ready = await self._wait_for_server_ready()

            async with self._state_lock:
                if server_ready:
                    self.current_state = ServerState.RUNNING
                    print("Server is now running")
                else:
                    self.current_state = ServerState.STOPPED
                    print("Server failed to start within timeout period", file=sys.stderr)

                self._startup_in_progress = False
                return server_ready

        except Exception as e:
            print(f"Error starting server: {e}", file=sys.stderr)
            async with self._state_lock:
                self.current_state = ServerState.STOPPED
                self._startup_in_progress = False
            return False

    async def stop_server(self, force=False):
        """
        Stop the server if it's currently running.

        Args:
            force (bool, optional): If True, force power off immediately.
                                    If False, request soft shutdown. Defaults to False.

        Returns:
            bool: True if the server was successfully stopped or was already stopped,
                  False otherwise
        """
        # Check if shutdown is already in progress
        # First get the server state without the lock
        current_state = await self.get_server_state()

        # Now acquire the lock to check and update state
        async with self._state_lock:
            # Re-check conditions that might have changed while waiting for the lock
            if self._shutdown_in_progress:
                print("Server shutdown already in progress")
                return True

            # We already have current_state from outside the lock
            if self.current_state == ServerState.STOPPED:
                print("Server is already stopped")
                return True

            if self.current_state == ServerState.STOPPING:
                print("Server is already stopping")
                return True

            # Set flags and state
            self._shutdown_in_progress = True
            self.current_state = ServerState.STOPPING

        # Stop the server
        try:
            print(f"Stopping server at {self.target_host} (force={force})...")
            power_off_result = await self.ipmi.power_off(force)

            if not power_off_result:
                print("Failed to send power off command", file=sys.stderr)
                async with self._state_lock:
                    self.current_state = ServerState.RUNNING  # Assume still running
                    self._shutdown_in_progress = False
                return False

            # Wait for the server to become unresponsive
            server_stopped = await self._wait_for_server_stopped()

            # Get power status before acquiring the lock
            ipmi_status = None
            if not server_stopped:
                ipmi_status = await self.ipmi.get_power_status()

            async with self._state_lock:
                if server_stopped:
                    self.current_state = ServerState.STOPPED
                    print("Server is now stopped")
                else:
                    # Use the power status we already got
                    if ipmi_status == "off":
                        self.current_state = ServerState.STOPPED
                        print("Server is now stopped (confirmed via IPMI)")
                        server_stopped = True
                    else:
                        self.current_state = ServerState.RUNNING
                        print("Server failed to stop within timeout period", file=sys.stderr)

                self._shutdown_in_progress = False
                return server_stopped

        except Exception as e:
            print(f"Error stopping server: {e}", file=sys.stderr)
            async with self._state_lock:
                # Release lock before making external call
                self._shutdown_in_progress = False

            # Check power status outside the lock
            ipmi_status = None
            try:
                ipmi_status = await self.ipmi.get_power_status()
            except Exception:
                pass

            # Reacquire lock to update state based on power status
            if ipmi_status == "off":
                async with self._state_lock:
                    self.current_state = ServerState.STOPPED
                return True

            # Server is still running
            async with self._state_lock:
                self.current_state = ServerState.RUNNING  # Assume still running
            return False

    async def _check_server_responding(self):
        """
        Check if the target server is responding to connection attempts.

        Tests the primary target port first, then tries other ports in port_mappings if defined.

        Returns:
            bool: True if the server is responding on any configured port, False otherwise
        """
        # Try the primary target port first
        if await self._check_port_responding(self.primary_target_port):
            return True

        # If primary port is not responding, try other ports in mappings if they exist
        if 'port_mappings' in self.config:
            for mapping in self.config['port_mappings']:
                target_port = mapping[1]  # The target port is the second element
                # Skip checking the primary port again
                if target_port != self.primary_target_port:
                    if await self._check_port_responding(target_port):
                        return True

        # No ports are responding
        return False

    async def _check_port_responding(self, port):
        """
        Check if the target server is responding on a specific port.

        Args:
            port (int): The port to check

        Returns:
            bool: True if the server is responding on the port, False otherwise
        """
        try:
            # Try connecting to the server on the specified port
            future = asyncio.open_connection(self.target_host, port)
            reader, writer = await asyncio.wait_for(future, timeout=5)

            # Close the connection
            writer.close()
            await writer.wait_closed()

            return True

        except (asyncio.TimeoutError, ConnectionRefusedError, socket.gaierror):
            return False
        except Exception as e:
            print(f"Error checking server status: {e}", file=sys.stderr)
            return False

    async def _wait_for_server_ready(self):
        """
        Wait for the server to become responsive within the timeout period.

        Returns:
            bool: True if the server becomes responsive, False if timeout is reached
        """
        print(f"Waiting for server to become ready (timeout: {self.startup_timeout}s)...")
        start_time = time.time()

        while time.time() - start_time < self.startup_timeout:
            if await self._check_server_responding():
                elapsed = time.time() - start_time
                print(f"Server is responsive after {elapsed:.1f} seconds")
                return True

            # Wait before checking again
            await asyncio.sleep(self.check_interval)

        print(f"Timeout reached ({self.startup_timeout}s) waiting for server to become ready", file=sys.stderr)
        return False

    async def _wait_for_server_stopped(self):
        """
        Wait for the server to become unresponsive within the timeout period.

        Returns:
            bool: True if the server becomes unresponsive, False if timeout is reached
        """
        print(f"Waiting for server to stop (timeout: {self.startup_timeout}s)...")
        start_time = time.time()

        while time.time() - start_time < self.startup_timeout:
            if not await self._check_server_responding():
                elapsed = time.time() - start_time
                print(f"Server is unresponsive after {elapsed:.1f} seconds")
                return True

            # Wait before checking again
            await asyncio.sleep(self.check_interval)

        print(f"Timeout reached ({self.startup_timeout}s) waiting for server to stop", file=sys.stderr)
        return False


# Example usage
if __name__ == "__main__":
    import os

    async def test_server_state():
        """Test the Server State Manager with credentials from environment variables."""
        # Create a minimal config from environment variables
        target_port = int(os.environ.get('TARGET_PORT', 80))
        config = {
            'target_host': os.environ.get('TARGET_HOST', ''),
            'port_mappings': [[8080, target_port]],
            'ipmi_host': os.environ.get('IPMI_HOST', ''),
            'ipmi_user': os.environ.get('IPMI_USER', ''),
            'ipmi_password': os.environ.get('IPMI_PASSWORD', '')
        }

        if not all([config['target_host'], config['ipmi_host'], config['ipmi_user'], config['ipmi_password']]):
            print("Missing required configuration. Please set TARGET_HOST, IPMI_HOST, IPMI_USER, and IPMI_PASSWORD environment variables.")
            sys.exit(1)

        # Create server state manager
        manager = ServerStateManager(config)

        # Get current state
        state = await manager.get_server_state()
        print(f"Current server state: {state}")

        # Example of starting/stopping - uncomment to test
        # if state == ServerState.STOPPED:
        #     result = await manager.start_server()
        #     print(f"Start server result: {result}")
        # elif state == ServerState.RUNNING:
        #     result = await manager.stop_server()
        #     print(f"Stop server result: {result}")

        # Check state again
        state = await manager.get_server_state()
        print(f"New server state: {state}")

    # Run the test function
    asyncio.run(test_server_state())