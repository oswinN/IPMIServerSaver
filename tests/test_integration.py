#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Integration test for the IPMI Server Saver

This script tests the full functionality of the smartproxy application
using both the mock IPMI tool and mock HTTP server. It simulates
different scenarios like server startup on first request, inactivity
shutdown, etc. and validates the expected behavior.
"""

import os
import sys
import time
import asyncio
import subprocess
import argparse
import signal
import json
import requests
import threading
from pathlib import Path
from contextlib import contextmanager

# Add parent directory to path to import from smartproxy
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import mock HTTP server
from tests.mock_http_server import start_server, stop_server

# Constants
PRIMARY_TCP_PORT = 8080  # Primary port for smartproxy
SECONDARY_TCP_PORT = 8081  # Secondary port for smartproxy
PRIMARY_TARGET_PORT = 8000  # Primary target port for mock HTTP server
SECONDARY_TARGET_PORT = 8001  # Secondary target port for mock HTTP server
PROXY_HOST = '127.0.0.1'
TARGET_HOST = '127.0.0.1'
MOCK_IPMI_HOST = '192.168.100.100'  # Fake IPMI host for testing
MOCK_IPMI_USER = 'admin'
MOCK_IPMI_PASS = 'password'
MOCK_IPMI_PATH = str(Path(__file__).parent / "mock_ipmitool.py")
STATE_DIR = Path(__file__).parent / '.state'


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

def clear_ipmi_state():
    """Clear any existing IPMI state files."""
    log_step("Clearing IPMI state files")
    if STATE_DIR.exists():
        found_files = list(STATE_DIR.glob('*'))
        if not found_files:
            log_info("No state files found to clean up", indent=1)

        for state_file in found_files:
            try:
                state_file.unlink()
                log_info(f"Removed state file: {state_file}", indent=1)
            except Exception as e:
                log_error(f"Failed to remove state file {state_file}: {e}", indent=1)


def set_ipmi_state(host, state):
    """
    Set IPMI state for a host directly.

    Args:
        host (str): IPMI host
        state (str): Power state ('on' or 'off')
    """
    host_file = MOCK_IPMI_HOST.replace('.', '_') + '.json'
    state_file = STATE_DIR / host_file

    # Create state directory if it doesn't exist
    STATE_DIR.mkdir(exist_ok=True)

    # Create state object
    state_obj = {
        'power': state,
        'last_updated': time.time()
    }

    # Write state file
    with open(state_file, 'w') as f:
        json.dump(state_obj, f)

    log_success(f"Set IPMI state for {host} to {state}")


def get_ipmi_state(host):
    """
    Get IPMI state for a host.

    Args:
        host (str): IPMI host

    Returns:
        str: Power state ('on', 'off', or 'unknown')
    """
    host_file = host.replace('.', '_') + '.json'
    state_file = STATE_DIR / host_file

    if not state_file.exists():
        return 'unknown'

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            return state.get('power', 'unknown')
    except Exception:
        return 'unknown'


@contextmanager
def run_mock_http_server(port=PRIMARY_TARGET_PORT):
    """Start mock HTTP server, yield, then stop it."""
    log_info("Starting Test: Start mock HTTP server, yield, then stop it.")
    server, thread = start_server(
        port=port,
        response_code=200,
        response_delay=0.1,
        response_body='{"status":"ok", "server":"mock"}',
        verbose=True
    )

    try:
        # Small delay to ensure server is started
        time.sleep(1)
        yield server
    finally:
        stop_server(server)


def create_test_config(config_path, **kwargs):
    """
    Create a test configuration file with the given parameters.

    Args:
        config_path (str): Path to write the config file
        **kwargs: Configuration parameters to override defaults

    Returns:
        str: Path to the created config file
    """
    # Default test configuration
    config = {
        "proxy_host": "0.0.0.0",
        "port_mappings": [
            [PRIMARY_TCP_PORT, PRIMARY_TARGET_PORT],
            [SECONDARY_TCP_PORT, SECONDARY_TARGET_PORT]
        ],

        "target_host": TARGET_HOST,

        "ipmi_host": MOCK_IPMI_HOST,
        "ipmi_user": MOCK_IPMI_USER,
        "ipmi_password": MOCK_IPMI_PASS,
        "ipmi_path": MOCK_IPMI_PATH,

        "inactivity_timeout": 60,   # 1 minute for testing
        "startup_timeout": 30,
        "check_interval": 5,

        "max_queue_size": 1000,
        "request_timeout": 60
    }

    # Override with provided parameters
    for key, value in kwargs.items():
        config[key] = value

    # Write to file
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=4)

    return config_path

@contextmanager
def run_smartproxy(config_path):
    """Start smartproxy, yield, then stop it."""
    # Prepare command with the config file
    cmd = [sys.executable, 'smartproxy.py', '--config', config_path]

    # Create environment with IPMITOOL set to mock path
    env = os.environ.copy()

    # Start process
    log_step(f"Starting smartproxy process:")
    log_info(f"Command: {' '.join(cmd)}", indent=1)
    process = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    # Create reader threads
    def print_output(stream, prefix):
        for line in iter(stream.readline, ''):
            # Add timestamp to proxy logs
            timestamp = log_timestamp()
            print(f"[{timestamp}] {prefix} {line.rstrip()}")

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


def send_test_request(path="/test", method="GET", expected_code=200, retry_count=5, retry_delay=1):
    """
    Send a test request to the proxy server.

    Args:
        path (str): Request path
        method (str): HTTP method
        expected_code (int): Expected HTTP status code
        retry_count (int): Number of retry attempts
        retry_delay (int): Delay between retries in seconds

    Returns:
        requests.Response: Response object or None if failed
    """
    url = f"http://{PROXY_HOST}:{PRIMARY_TCP_PORT}{path}"
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


def test_server_startup_on_request():
    """Test that server starts up on first request."""
    log_info("Starting Test that server starts up on first request.")
    log_separator("=")
    print(f"TEST: SERVER STARTUP ON REQUEST ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies that the server automatically powers on when it receives a request")

    # Clear IPMI state and set initial state to off
    clear_ipmi_state()
    set_ipmi_state(MOCK_IPMI_HOST, 'off')

    # Create test config file
    config_path = str(Path(__file__).parent / "startup_test_config.json")
    log_step("Creating test configuration")
    create_test_config(config_path)
    log_info(f"Test configuration saved to: {config_path}", indent=1)

    with run_mock_http_server(port=PRIMARY_TARGET_PORT) as http_server:
        with run_smartproxy(config_path) as proxy:
            # Verify initial state is off
            log_step("Verifying initial backend server power state")
            initial_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"Initial IPMI state: {initial_state}", indent=1)

            if initial_state != 'off':
                log_warning("Initial state is not 'off' as expected!", indent=1)

            # Send a request - this should trigger server startup
            log_step("Sending HTTP request to smart proxy - this should trigger server startup in the backend")
            response = send_test_request(retry_count=10, retry_delay=2)

            # Check that response was received
            log_step("Verifying response was received")
            if response is not None:
                log_success("Response received successfully", indent=1)
            else:
                log_error("No response received", indent=1)
                assert response is not None, "Failed to receive response"

            # Check if server was powered on
            log_step("Verifying server was powered on")
            log_info("Waiting for state to update...", indent=1)
            time.sleep(2)  # Wait for state to update
            new_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"IPMI state after request: {new_state}", indent=1)

            if new_state == 'on':
                log_success("Server was successfully powered on automatically", indent=1)
            else:
                log_error(f"Server power state is '{new_state}', expected 'on'", indent=1)
                assert new_state == 'on', f"Server should be on, but state is {new_state}"

            log_separator()
            log_success("SERVER STARTUP ON REQUEST TEST PASSED")
            log_separator()


def test_server_inactivity_shutdown():
    """Test that server shuts down after inactivity period."""
    log_info("Test that server shuts down after inactivity period.")
    log_separator("=")
    print(f"TEST: SERVER INACTIVITY SHUTDOWN ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies that the server automatically powers off after a period of inactivity")

    # Clear IPMI state and set initial state to off
    clear_ipmi_state()
    set_ipmi_state(MOCK_IPMI_HOST, 'off')

    # Create test config file with short inactivity timeout
    config_path = str(Path(__file__).parent / "shutdown_test_config.json")
    log_step("Creating test configuration with short inactivity timeout (30 seconds)")
    create_test_config(config_path, inactivity_timeout=30)  # 30 seconds for testing
    log_info(f"Test configuration saved to: {config_path}", indent=1)

    with run_mock_http_server(port=PRIMARY_TARGET_PORT) as http_server:
        with run_smartproxy(config_path) as proxy:
            # Send a request - this should trigger server startup
            log_step("Sending HTTP request - this should trigger server startup")
            response = send_test_request(retry_count=10, retry_delay=2)

            # Check that response was received
            log_step("Verifying response was received")
            if response is not None:
                log_success("Response received successfully", indent=1)
            else:
                log_error("No response received", indent=1)
                assert response is not None, "Failed to receive response"

            # Check if server was powered on
            log_step("Verifying server was powered on")
            log_info("Waiting for state to update...", indent=1)
            time.sleep(2)  # Wait for state to update
            new_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"IPMI state after request: {new_state}", indent=1)

            if new_state == 'on':
                log_success("Server was successfully powered on", indent=1)
            else:
                log_error(f"Server power state is '{new_state}', expected 'on'", indent=1)
                assert new_state == 'on', f"Server should be on, but state is {new_state}"

            # Wait for inactivity timeout to occur
            log_step("Waiting for inactivity timeout to trigger automatic shutdown")
            log_info(f"Configured timeout: 30 seconds - leaving server idle...", indent=1)

            # Wait a bit longer than the timeout to ensure shutdown
            wait_time = 60  # seconds
            for i in range(wait_time):
                time.sleep(1)
                if (i + 1) % 10 == 0:
                    log_info(f"Waited {i + 1} seconds...", indent=1)

                # Check current state
                current_state = get_ipmi_state(MOCK_IPMI_HOST)
                if current_state == 'off':
                    shutdown_time = i + 1
                    log_success(f"Server shutdown detected after {shutdown_time} seconds of inactivity!", indent=1)
                    break

            # Final check of power state
            log_step("Performing final verification of server power state")
            final_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"Final IPMI state after waiting: {final_state}", indent=1)

            if final_state == 'off':
                log_success("Server was automatically shut down as expected", indent=1)
            else:
                log_error(f"Server power state is '{final_state}', expected 'off'", indent=1)
                assert final_state == 'off', f"Server should be off, but state is {final_state}"

            log_separator()
            log_success("SERVER INACTIVITY SHUTDOWN TEST PASSED")
            log_separator()


def test_request_queueing():
    """Test that requests are queued during server startup."""
    log_info("Test that requests are queued during server startup.")
    log_separator("=")
    print(f"TEST: REQUEST QUEUEING DURING SERVER STARTUP ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies that requests are properly queued while the server is starting up")

    # Clear IPMI state and set initial state to off
    clear_ipmi_state()
    set_ipmi_state(MOCK_IPMI_HOST, 'off')

    # Create test config file for queuing test
    config_path = str(Path(__file__).parent / "queueing_test_config.json")
    log_step("Creating test configuration")
    create_test_config(config_path)
    log_info(f"Test configuration saved to: {config_path}", indent=1)

    with run_mock_http_server(port=PRIMARY_TARGET_PORT) as http_server:
        with run_smartproxy(config_path) as proxy:
            # Send an initial request to trigger startup
            log_step("Sending initial request to trigger server startup")
            first_thread = threading.Thread(
                target=send_test_request,
                kwargs={'path': '/first', 'retry_count': 12, 'retry_delay': 5}
            )
            first_thread.start()

            # Wait a short time for the startup process to begin
            log_info("Waiting for startup process to begin...", indent=1)
            time.sleep(2)
            log_step("Checking if server startup was initiated")
            startup_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"Current IPMI state: {startup_state}", indent=1)

            # Send additional requests that should be queued
            log_step("Sending additional requests that should be queued while server is starting")
            second_thread = threading.Thread(
                target=send_test_request,
                kwargs={'path': '/second', 'retry_count': 10, 'retry_delay': 3}
            )
            third_thread = threading.Thread(
                target=send_test_request,
                kwargs={'path': '/third', 'retry_count': 10, 'retry_delay': 3}
            )

            second_thread.start()
            time.sleep(1)
            third_thread.start()

            # Wait for all requests to complete
            log_step("Waiting for all queued requests to complete processing")
            log_info("Waiting for first request to complete...", indent=1)
            first_thread.join(timeout=60)
            log_info("Waiting for second request to complete...", indent=1)
            second_thread.join(timeout=60)
            log_info("Waiting for third request to complete...", indent=1)
            third_thread.join(timeout=60)
            log_success("All requests have completed", indent=1)

            # Verify final state
            log_step("Verifying final server state")
            final_state = get_ipmi_state(MOCK_IPMI_HOST)
            log_info(f"Final IPMI state: {final_state}", indent=1)

            if final_state == 'on':
                log_success("Server is powered on as expected after processing all requests", indent=1)
            else:
                log_error(f"Server power state is '{final_state}', expected 'on'", indent=1)
                assert final_state == 'on', f"Server should be on, but state is {final_state}"

            log_separator()
            log_success("REQUEST QUEUEING TEST PASSED")
            log_separator()


def test_multi_port_proxy():
    """Test that multiple ports can be used to access the same server."""
    log_info("Test that multiple ports can be used to access the same server.")
    log_separator("=")
    print(f"TEST: MULTI-PORT PROXY FUNCTIONALITY ({log_timestamp()})")
    log_separator("=")
    log_info("This test verifies that the proxy can handle requests on multiple ports")

    # Clear IPMI state and set initial state to off
    clear_ipmi_state()
    set_ipmi_state(MOCK_IPMI_HOST, 'off')

    # Create test config file
    config_path = str(Path(__file__).parent / "startup_test_config.json")
    log_step("Creating test configuration with multiple port mappings")
    create_test_config(config_path)
    log_info(f"Test configuration saved to: {config_path}", indent=1)

    # We need two mock servers, one for each target port
    with run_mock_http_server(port=PRIMARY_TARGET_PORT) as primary_server:
        with run_mock_http_server(port=SECONDARY_TARGET_PORT) as secondary_server:
            with run_smartproxy(config_path) as proxy:
                # Send a request to the first port
                log_step("Sending HTTP request to primary port")
                primary_response = send_test_request(
                    path="/primary",
                    retry_count=10,
                    retry_delay=2
                )

                # Check that response was received
                log_step("Verifying primary port response was received")
                if primary_response is not None:
                    log_success("Primary port response received successfully", indent=1)
                else:
                    log_error("No response received from primary port", indent=1)
                    assert primary_response is not None, "Failed to receive response from primary port"

                # Check if server was powered on
                log_step("Verifying server was powered on")
                server_state = get_ipmi_state(MOCK_IPMI_HOST)
                log_info(f"IPMI state after primary request: {server_state}", indent=1)
                assert server_state == 'on', f"Server should be on, but state is {server_state}"

                # Now send a request to the second port
                log_step("Sending HTTP request to secondary port")
                secondary_url = f"http://{PROXY_HOST}:{SECONDARY_TCP_PORT}/secondary"
                log_info(f"Sending GET request to {secondary_url}", indent=1)

                try:
                    secondary_response = requests.get(secondary_url, timeout=10)
                    log_info(f"Secondary port response: {secondary_response.status_code} {secondary_response.reason}", indent=1)

                    if secondary_response.status_code == 200:
                        log_success("Secondary port response received successfully", indent=1)
                    else:
                        log_error(f"Unexpected status code from secondary port: {secondary_response.status_code}", indent=1)
                        assert secondary_response.status_code == 200, "Secondary port returned non-200 status"

                except requests.exceptions.RequestException as e:
                    log_error(f"Secondary port request failed: {e}", indent=1)
                    raise AssertionError(f"Failed to connect to secondary port: {e}")

                log_separator()
                log_success("MULTI-PORT PROXY TEST PASSED")
                log_separator()


def main():
    """Main entry point for integration tests."""
    parser = argparse.ArgumentParser(description='Run smartproxy integration tests')

    parser.add_argument(
        '--startup',
        action='store_true',
        help='Run server startup test'
    )

    parser.add_argument(
        '--shutdown',
        action='store_true',
        help='Run server shutdown test'
    )

    parser.add_argument(
        '--queueing',
        action='store_true',
        help='Run request queueing test'
    )

    args = parser.parse_args()

    # If no specific tests are requested, run all tests
    run_all = not (args.startup or args.shutdown or args.queueing)

    # Print test execution plan
    log_separator()
    print(f"INTEGRATION TEST EXECUTION PLAN ({log_timestamp()})")
    log_separator()

    tests_to_run = []
    if run_all or args.startup:
        tests_to_run.append("Server Startup on Request")
    if run_all or args.shutdown:
        tests_to_run.append("Server Inactivity Shutdown")
    if run_all or args.queueing:
        tests_to_run.append("Request Queueing")

    # Always add the multi-port test
    tests_to_run.append("Multi-Port Proxy")

    log_info(f"Running {len(tests_to_run)} tests:")
    for i, test in enumerate(tests_to_run, 1):
        log_info(f"  {i}. {test}")

    log_separator()

    try:
        if run_all or args.startup:
            test_server_startup_on_request()

        if run_all or args.shutdown:
            test_server_inactivity_shutdown()

        if run_all or args.queueing:
            test_request_queueing()

        # Always run the multi-port test
        test_multi_port_proxy()

        log_separator("=")
        log_success("ALL TESTS COMPLETED SUCCESSFULLY!")
        log_separator("=")
        return 0

    except AssertionError as e:
        log_separator("=")
        log_error(f"TEST FAILED: {e}")
        log_separator("=")
        return 1

    except Exception as e:
        log_separator("=")
        log_error(f"UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 2


if __name__ == "__main__":
    sys.exit(main())