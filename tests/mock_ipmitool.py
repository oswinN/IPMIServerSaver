#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Mock IPMI Tool - Simulates the ipmitool command-line interface for testing

This script mimics the behavior of the ipmitool CLI command, allowing the
smartproxy to be tested without requiring actual IPMI hardware. It simulates
basic power control operations and maintains state between invocations.

Usage: Same as the real ipmitool command:
    mock_ipmitool -H <host> -U <user> -P <pass> <command>

Example:
    mock_ipmitool -H 192.168.1.100 -U admin -P password chassis power status
    mock_ipmitool -H 192.168.1.100 -U admin -P password chassis power on
    mock_ipmitool -H 192.168.1.100 -U admin -P password chassis power off
"""

import sys
import os
import argparse
import json
import time


# State file to store power status across invocations
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.state')
os.makedirs(STATE_DIR, exist_ok=True)


def get_state_file(host):
    """Get the state file path for a specific host."""
    return os.path.join(STATE_DIR, f"{host.replace('.', '_')}.json")


def get_power_state(host):
    """Get the current power state for a host."""
    state_file = get_state_file(host)
    if not os.path.exists(state_file):
        # Default state is off
        return "off"

    try:
        with open(state_file, 'r') as f:
            state = json.load(f)
            return state.get('power', 'off')
    except (json.JSONDecodeError, FileNotFoundError):
        return "off"


def set_power_state(host, state):
    """Set the power state for a host."""
    state_file = get_state_file(host)

    # Create state object
    state_obj = {
        'power': state,
        'last_updated': time.time()
    }

    with open(state_file, 'w') as f:
        json.dump(state_obj, f)


def handle_power_status(args):
    """Handle the 'chassis power status' command."""
    state = get_power_state(args.H)
    if state == "on":
        print("Chassis Power is on")
    else:
        print("Chassis Power is off")
    return 0


def handle_power_on(args):
    """Handle the 'chassis power on' command."""
    current_state = get_power_state(args.H)
    if current_state == "on":
        print("Chassis Power is already on")
    else:
        set_power_state(args.H, "on")
        print("Chassis Power Control: Up/On")
    return 0


def handle_power_off(args):
    """Handle the 'chassis power off' command."""
    current_state = get_power_state(args.H)
    if current_state == "off":
        print("Chassis Power is already off")
    else:
        set_power_state(args.H, "off")
        print("Chassis Power Control: Down/Off")
    return 0


def handle_power_soft(args):
    """Handle the 'chassis power soft' command."""
    current_state = get_power_state(args.H)
    if current_state == "off":
        print("Chassis Power is already off")
    else:
        # Simulate a delay for soft shutdown
        time.sleep(1)
        set_power_state(args.H, "off")
        print("Chassis Power Control: Soft (Graceful shutdown)")
    return 0


def handle_power_cycle(args):
    """Handle the 'chassis power cycle' command."""
    set_power_state(args.H, "off")
    time.sleep(1)
    set_power_state(args.H, "on")
    print("Chassis Power Control: Cycle")
    return 0


def handle_power_reset(args):
    """Handle the 'chassis power reset' command."""
    set_power_state(args.H, "on")
    print("Chassis Power Control: Reset")
    return 0


def handle_auth_error(args):
    """Simulate an authentication error."""
    print("Error: Unable to establish LAN session", file=sys.stderr)
    print("Authentication failed", file=sys.stderr)
    return 1


def handle_connection_error(args):
    """Simulate a connection error."""
    print("Error: Unable to establish IPMI v2 / RMCP+ session", file=sys.stderr)
    print("Error: Connection timed out", file=sys.stderr)
    return 1


def main():
    """Parse arguments and handle commands."""
    parser = argparse.ArgumentParser(description='Mock IPMI Tool')

    # Add common ipmitool arguments
    parser.add_argument('-H', help='Remote host (required)', required=True)
    parser.add_argument('-U', help='Username (required)', required=True)
    parser.add_argument('-P', help='Password (required)', required=True)
    parser.add_argument('-I', help='Interface type', default='lanplus')

    # Store all remaining arguments
    parser.add_argument('command', nargs='*', help='Command to execute')

    # Parse known args (ignore unknown)
    args, _ = parser.parse_known_args()

    # Simulate random failures (uncomment to enable)
    # if random.random() < 0.1:  # 10% chance of auth error
    #     return handle_auth_error(args)
    # if random.random() < 0.1:  # 10% chance of connection error
    #     return handle_connection_error(args)

    # Extract command
    if not args.command:
        print("Error: No command specified", file=sys.stderr)
        return 1

    # Handle 'chassis power' commands
    if len(args.command) >= 3 and args.command[0] == 'chassis' and args.command[1] == 'power':
        action = args.command[2]

        if action == 'status':
            return handle_power_status(args)
        elif action == 'on':
            return handle_power_on(args)
        elif action == 'off':
            return handle_power_off(args)
        elif action == 'soft':
            return handle_power_soft(args)
        elif action == 'cycle':
            return handle_power_cycle(args)
        elif action == 'reset':
            return handle_power_reset(args)
        else:
            print(f"Error: Unknown power action '{action}'", file=sys.stderr)
            return 1

    # Handle other commands or report unsupported
    print(f"Error: Unsupported command: {' '.join(args.command)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())