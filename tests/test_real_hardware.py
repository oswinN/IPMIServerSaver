#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Real Hardware Test for the IPMI Server Saver

This script tests the SmartProxy application with real server hardware as
configured in test_config_metal.json. Unlike the other tests, this does not
use any mock components but interfaces with the actual IPMI controller and
server hardware.

Test goals:
1. Getting server status
2. Starting up the server
3. Shutting down on no requests received
"""

import os
import sys
import time
import asyncio
import subprocess
import argparse
import json
import signal
import requests
from pathlib import Path
from contextlib import contextmanager

# Add parent directory to path to import from smartproxy
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import smartproxy components
from utils.config import load_config
from server.ipmi_controller import IpmiController
from server.state_manager import ServerStateManager, ServerState
from server.inactivity_monitor import InactivityMonitor
from smartproxy import SmartProxy

# Constants
CONFIG_PATH = Path(__file__).parent / "test_config_metal.json"
TEST_TIMEOUT = 1200  # 20 minutes for complete test in case of slow server boot

# Configure more readable timestamp format for logs
def log_timestamp():
    """Return current timestamp formatted for logs."""
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

def log_step(message, indent=0):
    """Log a test step with timestamp."""
    indent_str = "  " * indent
    print(f"\n{indent_str}[{log_timestamp()}] [STEP]  {message}")

def log_success(message, indent=0):
    """Log a successful operation with timestamp."""
    indent_str = "  " * indent
    print(f"{indent_str}[{log_timestamp()}] [SUCCESS]  {message}")

def log_warning(message, indent=0):
    """Log a warning with timestamp."""
    indent_str = "  " * indent
    print(f"{indent_str}[{log_timestamp()}] [WARNING]  {message}")

def log_error(message, indent=0):
    """Log an error with timestamp."""
    indent_str = "  " * indent
    print(f"{indent_str}[{log_timestamp()}] [ERROR]  {message}")

def log_info(message, indent=0):
    """Log informational message with timestamp."""
    indent_str = "  " * indent
    print(f"{indent_str}[{log_timestamp()}] [INFO]  {message}")

def log_separator(char="-", length=80):
    """Print a separator line."""
    print("\n" + char * length)

@contextmanager
def run_smartproxy(config_path):
    """Start smartproxy, yield, then stop it."""
    # Prepare command with the config file
    cmd = [sys.executable, 'smartproxy.py', '--config', config_path]

    # Start process
    log_step(f"Starting smartproxy process")
    log_info(f"Command: {' '.join(cmd)}", indent=1)
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Create reader threads for stdout and stderr
    def print_output(stream, prefix):
        for line in iter(stream.readline, ''):
            # Add timestamp to proxy logs
            timestamp = log_timestamp()
            print(f"[{timestamp}] {prefix} {line.rstrip()}")

    import threading
    stdout_thread = threading.Thread(
        target=print_output,
        args=(process.stdout, "[PROXY STDOUT]"),
        daemon=True
    )
    stderr_thread = threading.Thread(
        target=print_output,
        args=(process.stderr, "[PROXY STDERR]"),
        daemon=True
    )
    stdout_thread.start()
    stderr_thread.start()

    try:
        # Small delay to ensure proxy is started
        time.sleep(5)
        yield process
    finally:
        # Try graceful shutdown first
        try:
            if process.poll() is None:
                log_info("Sending SIGTERM to smartproxy")
                process.terminate()
                process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            log_warning("SIGTERM timeout, sending SIGKILL")
            process.kill()

        log_success("Smartproxy stopped")


def send_test_request(host, port, path="/test", method="GET", expected_code=200, retry_count=5, retry_delay=1):
    """
    Send a test request to the proxy server.

    Args:
        host (str): Proxy host
        port (int): Proxy port
        path (str): Request path
        method (str): HTTP method
        expected_code (int): Expected HTTP status code
        retry_count (int): Number of retry attempts
        retry_delay (int): Delay between retries in seconds

    Returns:
        requests.Response: Response object or None if failed
    """
    url = f"http://{host}:{port}{path}"
    log_step(f"Sending {method} request to {url}")

    for attempt in range(retry_count):
        try:
            response = requests.request(method, url, timeout=10)
            log_info(f"Response: {response.status_code} {response.reason}", indent=1)

            if response.status_code == expected_code:
                return response

            log_warning(f"Unexpected status code: {response.status_code}, expected: {expected_code}", indent=1)

        except requests.exceptions.RequestException as e:
            log_error(f"Request failed: {e}", indent=1)

        if attempt < retry_count - 1:
            log_info(f"Retrying in {retry_delay} seconds... (Attempt {attempt+1}/{retry_count})", indent=1)
            time.sleep(retry_delay)

    log_error(f"Failed to get expected response after {retry_count} attempts")
    return None


async def test_ipmi_controller_status():
    """Test basic connection to the IPMI controller and get server status."""
    log_separator("=")
    print(f"TEST: IPMI CONTROLLER STATUS CHECK ({log_timestamp()})")
    log_separator("=")
    log_info("This test checks basic connectivity with the IPMI controller and gets the server's power status")

    # Load the real hardware configuration
    log_step("Loading hardware configuration from test_config_metal.json")
    config = load_config(str(CONFIG_PATH))
    log_info(f"Loaded configuration with IPMI host: {config['ipmi_host']}", indent=1)

    # Create IPMI controller
    log_step("Creating IPMI controller")
    ipmi = IpmiController(
        config['ipmi_host'],
        config['ipmi_user'],
        config['ipmi_password'],
        ipmi_tool_path=config['ipmi_path']
    )

    # Get current power status
    log_step("Checking current power status")
    try:
        status = await ipmi.get_power_status()
        log_info(f"Current power status: {status}", indent=1)
        log_success("Successfully retrieved power status from real hardware")
    except Exception as e:
        log_error(f"Failed to get power status: {e}")
        raise  # Re-raise to fail the test

    log_separator()
    log_success("IPMI CONTROLLER STATUS CHECK TEST PASSED")
    log_separator()

    return status


async def test_server_startup():
    """Test server startup via the state manager."""
    log_separator("=")
    print(f"TEST: SERVER STARTUP ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies the proxy can start up the real server when needed")

    # Load the real hardware configuration
    config = load_config(str(CONFIG_PATH))

    # Create IPMI controller
    ipmi = IpmiController(
        config['ipmi_host'],
        config['ipmi_user'],
        config['ipmi_password'],
        ipmi_tool_path=config['ipmi_path']
    )

    # Create server state manager
    log_step("Creating server state manager")
    server_state_manager = ServerStateManager(config, ipmi)

    # Get initial server state
    log_step("Getting initial server state")
    state = await server_state_manager.get_server_state()
    log_info(f"Initial server state: {state}", indent=1)

    # If server is already running, stop it first for a clean test
    if state == ServerState.RUNNING:
        log_step("Server is already running, stopping it for clean test")
        stop_result = await server_state_manager.stop_server(force=False)
        if stop_result:
            log_success("Successfully stopped server", indent=1)
            # Wait a bit for server to fully stop
            log_info("Waiting 30 seconds for server to fully stop...", indent=1)
            await asyncio.sleep(30)
        else:
            log_error("Failed to stop server", indent=1)
            raise Exception("Failed to prepare server for startup test")

    # Verify server is stopped
    state = await server_state_manager.get_server_state()
    log_info(f"Server state before startup test: {state}", indent=1)
    if state != ServerState.STOPPED:
        log_error(f"Server should be in STOPPED state before startup test, but is in {state} state")
        raise Exception("Failed to prepare server for startup test")

    # Start server
    log_step("Starting server")
    start_result = await server_state_manager.start_server()

    # Verify server started successfully
    if start_result:
        log_success("Server started successfully", indent=1)
    else:
        log_error("Failed to start server", indent=1)
        raise Exception("Server startup test failed")

    # Verify server is running
    state = await server_state_manager.get_server_state()
    log_info(f"Server state after startup: {state}", indent=1)
    if state != ServerState.RUNNING:
        log_error(f"Server should be in RUNNING state after startup, but is in {state} state")
        raise Exception("Server state inconsistent after startup")

    log_separator()
    log_success("SERVER STARTUP TEST PASSED")
    log_separator()


async def test_smartproxy_inactivity_shutdown():
    """Test the full SmartProxy application with real hardware, focusing on inactivity shutdown."""
    log_separator("=")
    print(f"TEST: SMARTPROXY INACTIVITY SHUTDOWN ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies that the SmartProxy can automatically shut down the server after a period of inactivity")

    # Load the real hardware configuration
    config = load_config(str(CONFIG_PATH))

    # For testing, we'll use a shorter inactivity timeout
    test_config = config.copy()
    test_config['inactivity_timeout'] = 120  # 2 minutes for testing

    # Save the modified config to a temporary file
    temp_config_path = Path(__file__).parent / "temp_real_hardware_test_config.json"
    with open(temp_config_path, 'w') as f:
        json.dump(test_config, f, indent=4)

    try:
        # Start the SmartProxy with our test configuration
        with run_smartproxy(str(temp_config_path)) as proxy_process:
            # Get the first port mapping for our test
            proxy_port = test_config['port_mappings'][0][0]  # 11434 from the metal config

            # First ensure server is in a known state (we'll send a request to trigger startup if needed)
            log_step("Sending initial request to ensure server is running")
            response = send_test_request(
                "127.0.0.1",
                proxy_port,
                path="/",
                retry_count=30,  # More retries because real hardware server might take longer to start up
                retry_delay=10   # Longer delay between retries for real hardware
            )

            if response is None:
                log_error("Failed to get response from proxy, test cannot continue")
                raise Exception("Failed to get response from proxy")

            log_success("Got response from proxy, server should now be running")

            # Now we'll wait for the inactivity timeout to trigger shutdown
            inactivity_seconds = test_config['inactivity_timeout']
            extra_time = 60  # Extra time to account for polling intervals

            log_step(f"Waiting for inactivity shutdown to occur (approx. {inactivity_seconds} seconds)")
            log_info(f"No further requests will be sent. Waiting {inactivity_seconds + extra_time} seconds to verify shutdown...", indent=1)

            # Wait for the timeout period plus some extra time
            # Show a countdown to keep the user informed during the long wait
            total_wait = inactivity_seconds + extra_time
            log_info(f"Waiting for {total_wait} seconds to allow inactivity shutdown...", indent=1)

            for remaining in range(total_wait, 0, -30):
                await asyncio.sleep(min(30, remaining))
                if remaining > 30:
                    log_info(f"{remaining - 30} seconds remaining until check...", indent=1)

            # After waiting, we need to verify the server was shut down
            # Create an IPMI controller to check status directly
            log_step("Checking server power status after inactivity period")
            ipmi = IpmiController(
                config['ipmi_host'],
                config['ipmi_user'],
                config['ipmi_password'],
                ipmi_tool_path=config['ipmi_path']
            )

            status = await ipmi.get_power_status()
            log_info(f"Server power status after inactivity period: {status}", indent=1)

            if status == "off":
                log_success("Server was automatically shut down after inactivity period")
            else:
                log_error("Server is still running after inactivity period")
                raise Exception("Inactivity shutdown test failed: server was not shut down")

    finally:
        # Clean up the temporary config file
        if temp_config_path.exists():
            temp_config_path.unlink()
            log_info(f"Deleted temporary test config file: {temp_config_path}")

    log_separator()
    log_success("SMARTPROXY INACTIVITY SHUTDOWN TEST PASSED")
    log_separator()


async def run_all_tests():
    """Run all real hardware tests in sequence."""
    start_time = time.time()

    log_separator("#")
    print(f"STARTING REAL HARDWARE TESTS ({log_timestamp()})")
    log_separator("#")

    log_info("This test suite uses REAL HARDWARE as configured in test_config_metal.json")
    config = load_config(str(CONFIG_PATH))
    log_info(f"IPMI Host: {config['ipmi_host']}")
    log_info(f"Target Host: {config['target_host']}")
    log_info("The complete test may take 15+ minutes to run due to real hardware startup/shutdown times")
    log_separator()

    try:
        # Run tests in sequence
        await test_ipmi_controller_status()
        await test_server_startup()
        await test_smartproxy_inactivity_shutdown()

        # All tests passed
        elapsed_time = time.time() - start_time
        log_separator("#")
        log_success(f"ALL REAL HARDWARE TESTS PASSED ({elapsed_time/60:.1f} minutes)")
        log_separator("#")
        return True

    except Exception as e:
        # Test failed
        elapsed_time = time.time() - start_time
        log_separator("#")
        log_error(f"REAL HARDWARE TESTS FAILED: {e} ({elapsed_time/60:.1f} minutes)")
        log_separator("#")
        return False


def main():
    """Main entry point for the test script."""
    parser = argparse.ArgumentParser(
        description='Test the SmartProxy with real server hardware'
    )
    parser.add_argument(
        '--test',
        choices=['status', 'startup', 'shutdown', 'all'],
        default='all',
        help='Specific test to run (default: all)'
    )

    args = parser.parse_args()

    print(f"\nTesting smartproxy with REAL HARDWARE configured in {CONFIG_PATH}")
    print(f"This test interacts with real server hardware and may take significant time to complete.")

    # Set a global timeout for the entire test run
    try:
        if args.test == 'status':
            print("\nRunning IPMI status test only")
            asyncio.run(asyncio.wait_for(test_ipmi_controller_status(), TEST_TIMEOUT))
        elif args.test == 'startup':
            print("\nRunning server startup test only")
            asyncio.run(asyncio.wait_for(test_server_startup(), TEST_TIMEOUT))
        elif args.test == 'shutdown':
            print("\nRunning server shutdown test only")
            asyncio.run(asyncio.wait_for(test_smartproxy_inactivity_shutdown(), TEST_TIMEOUT))
        else:  # all
            print("\nRunning ALL tests in sequence")
            asyncio.run(asyncio.wait_for(run_all_tests(), TEST_TIMEOUT))

    except asyncio.TimeoutError:
        log_error(f"Test execution timed out after {TEST_TIMEOUT} seconds")
        sys.exit(1)
    except KeyboardInterrupt:
        log_warning("Test interrupted by user")
        sys.exit(1)
    except Exception as e:
        log_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()