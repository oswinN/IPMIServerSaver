#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPMI Server Saver - Main Application

This is the main entry point for the IPMI Server Saver application,
which functions as an intelligent HTTP proxy that can automatically power on/off
a IPMI server based on incoming requests and inactivity periods.

Created by: User
Created on: 2023-05-15
"""

import asyncio
import sys
import signal
import argparse

# Import application components
from utils.config import load_config
from server.ipmi_controller import IpmiController
from server.state_manager import ServerStateManager
from server.inactivity_monitor import InactivityMonitor
from proxy.http_proxy import HttpProxy


class SmartProxy:
    """
    Main application class that ties together all components.

    This class initializes and manages all the components of the
    application, including the IPMI controller, server state manager,
    inactivity monitor, and HTTP proxy.
    """

    def __init__(self, config):
        """
        Initialize the Smart Proxy application.

        Args:
            config (dict): Configuration dictionary
        """
        self.config = config

        # Create components
        self.ipmi = IpmiController(
            config['ipmi_host'],
            config['ipmi_user'],
            config['ipmi_password'],
            3,
            config['ipmi_path']
        )

        self.server_state_manager = ServerStateManager(
            config,
            self.ipmi
        )

        self.inactivity_monitor = InactivityMonitor(
            config,
            self.server_state_manager
        )

        # Create a proxy instance for each port mapping
        self.http_proxies = []
        for port_mapping in config['port_mappings']:
            proxy = HttpProxy(
                config,
                self.server_state_manager,
                self.inactivity_monitor,
                port_mapping=port_mapping
            )
            self.http_proxies.append(proxy)

        # Shutdown flag
        self._shutdown = False

    async def run(self):
        """
        Run the Smart Proxy application.

        This method initializes all components and starts the proxy server.
        It will run until a shutdown signal is received.
        """
        # Print configuration (excluding sensitive info)
        safe_config = {k: v for k, v in self.config.items() if k not in ['ipmi_user', 'ipmi_password']}
        print("Starting Smart Proxy with configuration:")
        for key, value in safe_config.items():
            print(f"  {key}: {value}")

        # Start all HTTP proxy servers
        proxy_runners = []
        for proxy in self.http_proxies:
            runner = await proxy.start()
            proxy_runners.append(runner)

        # Start inactivity monitoring
        await self.inactivity_monitor.start_monitoring()

        # Wait for shutdown signal
        try:
            while not self._shutdown:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("Application task cancelled, shutting down...")

        finally:
            # Stop inactivity monitoring
            await self.inactivity_monitor.stop_monitoring()

            # Stop all HTTP proxy servers
            for i, proxy in enumerate(self.http_proxies):
                await proxy.stop()
                if i < len(proxy_runners):
                    await proxy_runners[i].cleanup()

            print("Smart Proxy shutdown complete")

    def signal_shutdown(self):
        """Signal the application to shut down gracefully."""
        print("Shutdown signal received, preparing to shut down...")
        self._shutdown = True


def parse_arguments():
    """
    Parse command line arguments for the application.

    Returns:
        argparse.Namespace: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="IPMI Server Saver - Intelligent HTTP proxy with power management"
    )

    parser.add_argument(
        "-c", "--config",
        help="Path to configuration file (required)",
        dest="config_file",
        required=True
    )

    return parser.parse_args()


async def main():
    """Main entry point for the Smart Proxy application."""
    # Parse command line arguments
    args = parse_arguments()

    # Load configuration from the specified file
    try:
        config = load_config(args.config_file)
    except Exception as e:
        print(f"Error loading configuration: {e}", file=sys.stderr)
        sys.exit(1)

    # Create and run the application
    app = SmartProxy(config)

    # Set up signal handlers for graceful shutdown
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda sig, frame: app.signal_shutdown())

    # Run the application
    await app.run()


if __name__ == "__main__":
    # Run the main function
    asyncio.run(main())