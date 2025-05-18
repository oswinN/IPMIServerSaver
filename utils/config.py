#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Configuration management for the IPMI Server Saver.

This module handles loading and validating configuration from a JSON file.
"""

import json
import sys
import os


def load_config(config_path):
    """
    Load configuration from a JSON file.

    Args:
        config_path (str): Path to the configuration file.

    Returns:
        dict: Configuration dictionary with all settings.

    Raises:
        FileNotFoundError: If the configuration file doesn't exist.
        json.JSONDecodeError: If the configuration file contains invalid JSON.
        SystemExit: If the configuration is invalid.
    """
    if not os.path.exists(config_path):
        print(f"Error: Configuration file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        # Load configuration from file
        with open(config_path, 'r') as f:
            config = json.load(f)

    except json.JSONDecodeError as e:
        print(f"Error parsing config file: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error loading config file: {e}", file=sys.stderr)
        sys.exit(1)

    # Set default values for optional parameters
    defaults = {
        # Proxy settings
        'proxy_host': '0.0.0.0',
        'port_mappings': [[8080, 80]],  # Default to one mapping

        # Power management settings
        'inactivity_timeout': 3600,  # 1 hour default
        'startup_timeout': 300,      # 5 minutes default
        'check_interval': 30,        # 30 seconds default

        # Request handling settings
        'max_queue_size': 1000,
        'request_timeout': 60,       # 60 seconds default
    }

    # Apply defaults for any missing parameters
    for key, value in defaults.items():
        if key not in config:
            config[key] = value

    # Validate the configuration
    validate_config(config)

    return config


def validate_config(config):
    """
    Validate that all required configuration parameters are provided.

    Args:
        config (dict): Configuration dictionary to validate.

    Raises:
        SystemExit: If any required configuration is missing.
    """
    required_params = ['target_host', 'ipmi_host', 'ipmi_user', 'ipmi_password', 'ipmi_path', 'port_mappings']
    missing_params = [param for param in required_params if not config.get(param)]

    if missing_params:
        print(f"Error: Missing required configuration: {', '.join(missing_params)}", file=sys.stderr)
        print("Please make sure these parameters are defined in your configuration file:", file=sys.stderr)
        for param in missing_params:
            print(f"  - {param}", file=sys.stderr)
        sys.exit(1)
    
    # Validate port_mappings
    if not isinstance(config['port_mappings'], list) or not config['port_mappings']:
        print("Error: port_mappings must be a non-empty list of [listen_port, target_port] pairs", file=sys.stderr)
        sys.exit(1)
        
    for mapping in config['port_mappings']:
        if not isinstance(mapping, list) or len(mapping) != 2 or not all(isinstance(p, int) for p in mapping):
            print("Error: Each port mapping must be a list of [listen_port, target_port]", file=sys.stderr)
            print("       Both ports must be integers", file=sys.stderr)
            sys.exit(1)
        if not all(p > 0 for p in mapping):
            print("Error: Port numbers must be positive integers", file=sys.stderr)
            sys.exit(1)

    # Validate numeric parameters
    numeric_params = ['inactivity_timeout', 'startup_timeout', 'check_interval',
                     'max_queue_size', 'request_timeout']

    for param in numeric_params:
        try:
            if config[param] <= 0:
                print(f"Error: {param} must be a positive number", file=sys.stderr)
                sys.exit(1)
        except (KeyError, TypeError):
            print(f"Error: {param} is missing or not a number", file=sys.stderr)
            sys.exit(1)


if __name__ == "__main__":
    # If run directly, expect a path to a config file as argument
    if len(sys.argv) != 2:
        print("Usage: python config.py <config_file_path>", file=sys.stderr)
        sys.exit(1)

    config_path = sys.argv[1]
    config = load_config(config_path)
    print(json.dumps(config, indent=4))