#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test script for using the mock IPMI tool with smartproxy

This script demonstrates how to use the mock IPMI tool for testing the
smartproxy application without requiring actual IPMI hardware. It provides
examples of how to configure the application to use the mock tool.
"""

import os
import sys
import subprocess
import time
import asyncio
import argparse
import json
import shutil
import signal
import tempfile
from pathlib import Path

# Add parent directory to path to import from smartproxy
sys.path.insert(0, str(Path(__file__).parent.parent))

# Import smartproxy components for testing
from utils.config import load_config
from server.ipmi_controller import IpmiController
from server.state_manager import ServerStateManager


# Constants
MOCK_IPMI_PATH = Path(__file__).parent / "mock_ipmitool.py"
DEFAULT_TEST_HOST = "192.168.100.100"  # Fake test host
DEFAULT_TEST_USER = "admin"
DEFAULT_TEST_PASS = "password"


def run_mock_ipmi_command(command, host=DEFAULT_TEST_HOST, user=DEFAULT_TEST_USER, password=DEFAULT_TEST_PASS):
    """
    Run mock IPMI command and return the output.

    Args:
        command (str): The command to run (e.g., "chassis power status")
        host (str): The IPMI host
        user (str): The IPMI username
        password (str): The IPMI password

    Returns:
        tuple: (output_str, exit_code) - The command output and the exit code
    """
    cmd = [
        sys.executable,
        str(MOCK_IPMI_PATH),
        "-H", host,
        "-U", user,
        "-P", password,
        "-I", "lanplus"
    ] + command.split()

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Command: {' '.join(cmd)}")
    print(f"Exit code: {result.returncode}")
    print(f"Output: {result.stdout.strip()}")
    print(f"Error: {result.stderr.strip()}")
    print()

    return result.stdout.strip(), result.returncode


def run_basic_mock_ipmitool_tests():
    """Run basic tests of the mock IPMI tool with assertions."""
    print("Testing mock IPMI tool...")
    print("=========================")

    # Set initial test power off
    output, exit_code = run_mock_ipmi_command("chassis power off")
    assert exit_code == 0, "Power off command failed"
    assert ("Chassis Power Control: Down/Off" in output) or ("Chassis Power is already off" in output), "Power off message incorrect"

    # Test power status (should be off initially)
    output, exit_code = run_mock_ipmi_command("chassis power status")
    assert exit_code == 0, "Initial power status command failed"
    assert "Chassis Power is off" in output, "Initial power state should be off"
    # Test power on
    output, exit_code = run_mock_ipmi_command("chassis power on")
    assert exit_code == 0, "Power on command failed"
    assert "Chassis Power Control: Up/On" in output, "Power on message incorrect"

    # Verify power status changed
    output, exit_code = run_mock_ipmi_command("chassis power status")
    assert exit_code == 0, "Power status check failed"
    assert "Chassis Power is on" in output, "Power should be on after power on command"

    # Test soft power off
    output, exit_code = run_mock_ipmi_command("chassis power soft")
    assert exit_code == 0, "Soft power off command failed"
    assert "Chassis Power Control: Soft" in output, "Soft power off message incorrect"

    # Verify power status changed
    output, exit_code = run_mock_ipmi_command("chassis power status")
    assert exit_code == 0, "Power status check failed"
    assert "Chassis Power is off" in output, "Power should be off after soft power off command"

    # Test hard power off when already off
    output, exit_code = run_mock_ipmi_command("chassis power off")
    assert exit_code == 0, "Hard power off command failed"
    assert "Chassis Power is already off" in output, "Already-off message incorrect"

    # Test power cycle
    output, exit_code = run_mock_ipmi_command("chassis power cycle")
    assert exit_code == 0, "Power cycle command failed"
    assert "Chassis Power Control: Cycle" in output, "Power cycle message incorrect"

    # Verify power status (should be on after cycle)
    output, exit_code = run_mock_ipmi_command("chassis power status")
    assert exit_code == 0, "Power status check failed"
    assert "Chassis Power is on" in output, "Power should be on after power cycle command"

    print("Basic IPMI tests completed successfully.\n")


async def test_ipmi_controller_with_mock_ipmitool():
    """Test the IpmiController class with the mock IPMI tool with assertions."""
    print("Testing IpmiController class...")
    print("==============================")

    # Load test configuration
    test_config_path = Path(__file__).parent / "test_config.json"
    config = load_config(str(test_config_path))

    # Create IPMI controller with path to mock tool
    ipmi = IpmiController(
        config['ipmi_host'],
        config['ipmi_user'],
        config['ipmi_password'],
        ipmi_tool_path=str(MOCK_IPMI_PATH)
    )

    # Reset power state to off for testing
    run_mock_ipmi_command("chassis power off")

    # Test get power status
    status = await ipmi.get_power_status()
    print(f"Power status: {status}")
    assert status == "off", "Initial power status should be off"

    # Test power on
    print("Powering on...")
    result = await ipmi.power_on()
    print(f"Power on result: {result}")
    assert result == "Chassis Power Control: Up/On", "Power on should return True"

    # Test get power status again
    status = await ipmi.get_power_status()
    print(f"Power status: {status}")
    assert status == "on", "Power status should be on after powering on"

    # Test power off
    print("Powering off...")
    result = await ipmi.power_off()
    print(f"Power off result: {result}")
    assert result == "Chassis Power Control: Soft (Graceful shutdown)", "Power off should return True"

    # Test get power status again
    status = await ipmi.get_power_status()
    print(f"Power status: {status}")
    assert status == "off", "Power status should be off after powering off"

    print("IpmiController tests completed successfully.\n")


async def test_server_state_manager_with_mock_ipmitool():
    """Test the ServerStateManager class with the mock IPMI tool with assertions."""
    print("Testing ServerStateManager class...")
    print("=================================")

    # Load test configuration
    test_config_path = Path(__file__).parent / "test_config.json"
    config = load_config(str(test_config_path))

    # Create IPMI controller with path to mock tool
    ipmi_controller = IpmiController(
        config['ipmi_host'],
        config['ipmi_user'],
        config['ipmi_password'],
        ipmi_tool_path=str(MOCK_IPMI_PATH)
    )

    # Create server state manager with our IPMI controller
    server_state_manager = ServerStateManager(config, ipmi_controller)

    print(" ::Reset power state to off for testing")
    run_mock_ipmi_command("chassis power off")

    print(" ::Test get server state")
    state = await server_state_manager.get_server_state()
    print(f"Server state: {state}")
    assert state.value == "stopped", "Initial server state should be STOPPED"

    print(" ::Test start server (will time out since there's no real server)")
    print("Starting server (will time out)...")
    result = await server_state_manager.start_server()
    print(f"Start server result: {result}")
    # The start_server method returns False due to timeout since we don't have a real server
    assert result == False, "Server start should fail due to timeout"

    print(" ::Test get server state again")
    state = await server_state_manager.get_server_state()
    print(f"Server state: {state}")
    # Even though the IPMI power command succeeded, the server state should be STOPPED
    # because the server is not responding to port connection attempts
    assert state.value == "stopped", "Server state should be STOPPED after failed start attempt"

    print(" ::Test stop server")
    print("Stopping server...")
    result = await server_state_manager.stop_server()
    print(f"Stop server result: {result}")
    assert result == True, "Server stop should succeed"

    print(" ::Test get server state again")
    state = await server_state_manager.get_server_state()
    print(f"Server state: {state}")
    assert state.value == "stopped", "Server state should be STOPPED after stopping"

    print("ServerStateManager tests completed successfully.\n")


async def run_all_tests():
    """Run all tests."""
    run_basic_mock_ipmitool_tests()
    await test_ipmi_controller_with_mock_ipmitool()
    await test_server_state_manager_with_mock_ipmitool()
    print("All tests completed successfully with all assertions passing.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Test the mock IPMI tool with smartproxy')
    parser.add_argument('--basic', action='store_true', help='Run only basic IPMI tests')
    parser.add_argument('--controller', action='store_true', help='Run IPMI controller tests')
    parser.add_argument('--manager', action='store_true', help='Run server state manager tests')
    args = parser.parse_args()

    print("Mock IPMI Testing")
    print("================\n")

    # If no specific tests are requested, run all tests
    if not (args.basic or args.controller or args.manager):
        asyncio.run(run_all_tests())
        return

    # Run requested tests
    if args.basic:
        run_basic_mock_ipmitool_tests()

    if args.controller:
        asyncio.run(test_ipmi_controller_with_mock_ipmitool())

    if args.manager:
        asyncio.run(test_server_state_manager_with_mock_ipmitool())

    print("Requested tests completed successfully with all assertions passing.")


if __name__ == "__main__":
    main()