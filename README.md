# IPMI Server Saver

A Python-based intelligent proxy for HTTP requests that optimizes energy consumption for servers that have IPMI by managing power states based on network activity.

This can be useful for sparsely used servers that need to serve a low number of not time-critical requests.

When no requests are incoming for a set amount of time, the server will be shut down. When requests are coming in, the request is queued, the server is powered up and when the service is available, the requests will sent from the queue. For the proxy client this looks like a long running request.

## Features

- Transparent HTTP proxy that forwards requests to an IPMI controlled server
- Multi-port support for listening on and forwarding multiple ports to the same server
- Automatic power management:
  - Detects when the server is powered off
  - Starts the server via IPMI when requests are received and the server is off
  - Gracefully shuts down the server after a configurable period of inactivity
- Robust configuration options for network settings, power management, and more
- Transparent request queuing during server startup
- High scalability with support for thousands of concurrent connections
- IPMI integration for server power control

## Prerequisites

- Python 3.8 or higher
- ipmitool installed on the system
- Network access to both the server and its IPMI interface

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/nomosServerSaver.git
   cd nomosServerSaver
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Create a configuration file (or use environment variables):
   ```
   cp config.sample.json config.json
   ```

4. Edit the configuration file to match your environment.

## Configuration

The application is configured using a JSON configuration file.

### Configuration File

The configuration file uses JSON format. See `config.sample.json` for an example. Copy this file to `config.json` and modify it for your environment:

```json
{
    "proxy_host": "0.0.0.0",
    "port_mappings": [
        [8080, 80],
        [8443, 443],
        [9000, 8080]
    ],

    "target_host": "192.168.1.100",

    "ipmi_host": "192.168.1.101",
    "ipmi_user": "ADMIN",
    "ipmi_password": "insertpasswordhere",
    "ipmi_path":".\\ipmitool\\bmc\\ipmitool.exe",

    "inactivity_timeout": 3600,
    "startup_timeout": 300,
    "check_interval": 30,

    "max_queue_size": 1000,
    "request_timeout": 60
}
```

#### Required Parameters

- `target_host` - Hostname/IP of the target server
- `ipmi_host` - Hostname/IP of the IPMI interface
- `ipmi_user` - IPMI username
- `ipmi_password` - IPMI password
- `ipmi_path` - Path to ipmitool executable 
Note on IPMI executable: The package is available on most linux distributions, or on windows you can use the Dell BMC utility which includes ipmitool.exe. [Dell BMC Utility](https://www.dell.com/support/home/en-us/drivers/driversdetails?driverid=96ph4)

#### Optional Parameters (with defaults)

- `proxy_host` - Interface to bind the proxy to (default: "0.0.0.0")
- `port_mappings` - List of [proxy_port, target_port] pairs (default: [[8080, 80]])
- `inactivity_timeout` - Seconds of inactivity before shutting down (default: 3600)
- `startup_timeout` - Maximum seconds to wait for server startup (default: 300)
- `check_interval` - Seconds between status checks (default: 30)
- `max_queue_size` - Maximum number of queued requests (default: 1000)
- `request_timeout` - Timeout for queued requests in seconds (default: 60)

### Command-line Arguments

```
usage: smartproxy.py [-h] -c CONFIG_FILE

IPMI Server Saver - Intelligent HTTP proxy with power management

required arguments:
  -c CONFIG_FILE, --config CONFIG_FILE
                        Path to configuration file (required)

optional arguments:
  -h, --help            show this help message and exit
```

## Usage

1. Create a configuration file:
   ```
   cp config.sample.json config.json
   ```

2. Edit the configuration file with your server details:
   ```
   nano config.json
   ```

3. Run the application:
   ```
   python smartproxy.py -c config.json
   ```

4. The proxy will now listen on all the configured ports for HTTP requests.

## How It Works

1. The proxy listens for incoming HTTP requests on all configured ports.
2. When a request arrives:
   - If the server is running, the request is forwarded immediately.
   - If the server is off, the request is queued and the server is started.
   - If the server is starting, the request is queued.
3. Once the server is running, all queued requests are processed.
4. Any new requests reset the inactivity timer.
5. After the configured inactivity period with no requests, the server is gracefully shut down.

## Testing with Mock IPMI Tool

For testing without requiring actual IPMI hardware, the application includes a mock IPMI tool that simulates the behavior of a real server's IPMI interface.

### Using the Mock IPMI Tool

The mock IPMI tool (`tests/mock_ipmitool.py`) is designed to be a drop-in replacement for the real `ipmitool` command. It simulates basic power control operations and maintains state between invocations.

To use the mock tool:

1. Direct the application to use the mock tool by setting the `IPMITOOL` environment variable:

   ```
   export IPMITOOL=/path/to/nomosServerSaver/tests/mock_ipmitool.py
   ```

2. Run the application normally:

   ```
   python smartproxy.py
   ```

### Running Mock IPMI Tests

A test script (`tests/test_mock_ipmi.py`) is provided to demonstrate and validate the mock IPMI tool:

```
python tests/test_mock_ipmi.py
```

This runs a series of tests that demonstrate:
- Basic IPMI commands (power status, on, off)
- Integration with the IpmiController class
- Integration with the ServerStateManager class

You can also run specific test groups:

```
python tests/test_mock_ipmi.py --basic      # Run only basic IPMI tests
python tests/test_mock_ipmi.py --controller # Run IPMI controller tests
python tests/test_mock_ipmi.py --manager    # Run server state manager tests
```

### How the Mock IPMI Tool Works

The mock IPMI tool:
1. Simulates the command-line interface of the real ipmitool
2. Stores power state in a `.state` directory within the tests directory
3. Produces outputs matching the format of the real ipmitool
4. Can be used to simulate power control without affecting real hardware

This is particularly useful for development, automated testing, and environments where real IPMI hardware is not available.

### Mock HTTP Server

A mock HTTP server (`tests/mock_http_server.py`) is also provided to simulate the target server for complete end-to-end testing. The mock server:

- Listens for HTTP requests and logs their details
- Can be configured to return specific responses and status codes
- Supports simulated response delays
- Can be run as a standalone tool during development

To start the mock HTTP server:

```
python tests/mock_http_server.py --port 8000
```

Additional options:
```
python tests/mock_http_server.py -h
usage: mock_http_server.py [-h] [-p PORT] [-c CODE] [-d DELAY] [-b BODY] [-e] [-q]

Mock HTTP Server for testing

optional arguments:
  -h, --help            show this help message and exit
  -p PORT, --port PORT  Port to listen on (default: 8000)
  -c CODE, --code CODE  HTTP response code (default: 200)
  -d DELAY, --delay DELAY
                        Response delay in seconds (default: 0)
  -b BODY, --body BODY  Response body (default: {"status":"ok"})
  -e, --echo            Echo request details in response
  -q, --quiet           Suppress detailed request logging
```

### Integration Testing

The project includes comprehensive integration tests that use both the mock IPMI tool and mock HTTP server to test the full functionality of the application without requiring actual hardware.

To run all integration tests:

```
python tests/test_integration.py
```

You can also run specific test scenarios:

```
python tests/test_integration.py --startup   # Test server startup on request
python tests/test_integration.py --shutdown  # Test inactivity shutdown
python tests/test_integration.py --queueing  # Test request queuing during startup
```

These integration tests simulate the full application workflow including:
- Server startup when requests are received while the server is off
- Transparent request handling during server startup
- Automatic server shutdown after the inactivity period
- Multi-port functionality for handling requests on different ports

## Multi-Port Proxying

The Smart Proxy supports proxying multiple ports to different target ports on the same server. This is useful for:

- Proxying both HTTP (80) and HTTPS (443) traffic
- Accessing different applications running on different ports on the same server
- Mapping internal server ports to different external ports

### Configuration

To set up multi-port proxying, configure the `port_mappings` parameter in your configuration file:

```json
"port_mappings": [
    [8080, 80],   // Maps local port 8080 to server port 80
    [8443, 443],  // Maps local port 8443 to server port 443
    [9000, 8080]  // Maps local port 9000 to server port 8080
]
```

Each entry in the `port_mappings` array is a tuple of `[proxy_port, target_port]`:
- `proxy_port`: The port that the proxy will listen on
- `target_port`: The port on the target server to forward requests to

All requests across all ports share the same power management logic - any request on any port will start the server when it's off, and the inactivity timer is reset by activity on any port.

## Ideas for further development

- Allow for runtime reloading of the configuration, turning the shutdown functionality on and off.
- Provide a webui for status information and configuration editing
- More / general IPMI functionality.
- Notifications.

## License

This project is licensed under the Apache-2.0 License - see the LICENSE file for details.