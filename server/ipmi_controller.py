#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
IPMI Controller for managing IPMI controlled server power states.

This module provides a wrapper around ipmitool to control the power state
of a IPMI server via IPMI commands.
"""

import asyncio
import os
import subprocess
import time
import sys


class IpmiController:
    """
    Controller for executing IPMI commands to manage server power state.

    This class provides methods to power on, power off, and check the power status
    of a IPMI server using ipmitool.
    """

    def __init__(self, ipmi_host, ipmi_user, ipmi_password, max_retries=3, ipmi_tool_path=None):
        """
        Initialize the IPMI Controller with server credentials.

        Args:
            ipmi_host (str): Hostname or IP address of the IPMI interface
            ipmi_user (str): IPMI username
            ipmi_password (str): IPMI password
            max_retries (int, optional): Maximum number of retries for IPMI commands. Defaults to 3.
            ipmi_tool_path (str, optional): Path to the ipmitool executable. If None, uses the
                                           IPMITOOL environment variable or "ipmitool" if not set.
        """
        self.ipmi_host = ipmi_host
        self.ipmi_user = ipmi_user
        self.ipmi_password = ipmi_password
        self.max_retries = max_retries

        # Use specified path, or get from environment, or use default
        self.ipmi_tool_path = ipmi_tool_path or os.environ.get('IPMITOOL', 'ipmitool')

    async def power_on(self):
        """
        Power on the server using IPMI.

        Returns:
            bool: True if the command succeeded, False otherwise.
        """
        print(f"Powering on server at {self.ipmi_host}...")
        return await self._execute_ipmi_command("chassis power on")

    async def power_off(self, force=False):
        """
        Power off the server using IPMI.

        Args:
            force (bool, optional): If True, force power off. If False, request soft shutdown.
                                    Defaults to False.

        Returns:
            bool: True if the command succeeded, False otherwise.
        """
        command = "chassis power off" if force else "chassis power soft"
        print(f"Powering off server at {self.ipmi_host} (force={force})...")
        return await self._execute_ipmi_command(command)

    async def get_power_status(self):
        """
        Check the current power status of the server.

        Returns:
            str: Power status string ("on", "off", or "unknown")
        """
        result = await self._execute_ipmi_command("chassis power status")
        if not result:
            return "unknown"

        for line in result.splitlines():
            if "Chassis Power is on" in line:
                return "on"
            elif "Chassis Power is off" in line:
                return "off"

        return "unknown"

    async def _execute_ipmi_command(self, command, retries=0):
        """
        Execute an IPMI command using ipmitool.

        Args:
            command (str): The IPMI command to execute
            retries (int, optional): Current retry count. Defaults to 0.

        Returns:
            str or None: Command output if successful, None otherwise.
        """
        # Check if the ipmi_tool_path is a Python script
        is_python_script = self.ipmi_tool_path.endswith('.py')

        if is_python_script:
            # use the Python interpreter to run Python scripts
            ipmi_cmd = [
                sys.executable,
                self.ipmi_tool_path,
                "-I", "lanplus",
                "-H", self.ipmi_host,
                "-U", self.ipmi_user,
                "-P", self.ipmi_password,
            ] + command.split()
        else:
            # if not python use the real ipmitool binary
            ipmi_cmd = [
                self.ipmi_tool_path,
                "-I", "lanplus",
                "-H", self.ipmi_host,
                "-U", self.ipmi_user,
                "-P", self.ipmi_password,
            ] + command.split()

        try:
            # Use asyncio.create_subprocess_exec to run the command asynchronously
            process = await asyncio.create_subprocess_exec(
                *ipmi_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # Wait for the process to complete with a timeout
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)

            if process.returncode != 0:
                error_message = stderr.decode('utf-8', errors='ignore').strip()
                print(f"IPMI command failed: {error_message}", file=sys.stderr)

                # Retry on failure if we haven't exceeded max_retries
                if retries < self.max_retries:
                    # Exponential backoff
                    wait_time = 2 ** retries
                    print(f"Retrying in {wait_time} seconds... (Attempt {retries+1}/{self.max_retries})")
                    await asyncio.sleep(wait_time)
                    return await self._execute_ipmi_command(command, retries + 1)
                return None

            return stdout.decode('utf-8', errors='ignore').strip()

        except asyncio.TimeoutError:
            print(f"IPMI command timed out after 30 seconds", file=sys.stderr)
            if retries < self.max_retries:
                wait_time = 2 ** retries
                print(f"Retrying in {wait_time} seconds... (Attempt {retries+1}/{self.max_retries})")
                await asyncio.sleep(wait_time)
                return await self._execute_ipmi_command(command, retries + 1)
            return None

        except Exception as e:
            print(f"Error executing IPMI command: {e}", file=sys.stderr)
            if retries < self.max_retries:
                wait_time = 2 ** retries
                print(f"Retrying in {wait_time} seconds... (Attempt {retries+1}/{self.max_retries})")
                await asyncio.sleep(wait_time)
                return await self._execute_ipmi_command(command, retries + 1)
            return None


# Example usage
if __name__ == "__main__":
    import os

    async def test_ipmi():
        """Test the IPMI Controller with credentials from environment variables."""
        # Get IPMI credentials from environment
        ipmi_host = os.environ.get('IPMI_HOST', '')
        ipmi_user = os.environ.get('IPMI_USER', '')
        ipmi_password = os.environ.get('IPMI_PASSWORD', '')

        if not all([ipmi_host, ipmi_user, ipmi_password]):
            print("Missing IPMI credentials. Please set IPMI_HOST, IPMI_USER, and IPMI_PASSWORD environment variables.")
            sys.exit(1)

        # Create IPMI controller
        ipmi = IpmiController(ipmi_host, ipmi_user, ipmi_password)

        # Get current status
        status = await ipmi.get_power_status()
        print(f"Current power status: {status}")

        # Example of powering on/off - uncomment to test
        # if status == "off":
        #     result = await ipmi.power_on()
        #     print(f"Power on result: {result}")
        # else:
        #     result = await ipmi.power_off()
        #     print(f"Power off result: {result}")

        # Check status again
        status = await ipmi.get_power_status()
        print(f"New power status: {status}")

    # Run the test function
    asyncio.run(test_ipmi())

"""
Testing with the mock IPMI tool:

To use the mock IPMI tool for testing, set the IPMITOOL environment variable:

    import os
    os.environ['IPMITOOL'] = '/path/to/mock_ipmitool.py'

    # Then create the IPMI controller normally
    ipmi = IpmiController(ipmi_host, ipmi_user, ipmi_password)

Or pass the path directly:

    ipmi = IpmiController(
        ipmi_host,
        ipmi_user,
        ipmi_password,
        ipmi_tool_path='/path/to/mock_ipmitool.py'
    )

This allows for testing the IPMI controller without requiring actual IPMI hardware.
"""