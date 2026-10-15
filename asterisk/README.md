# MedMind — Voice Call Setup Guide

## Overview

MedMind is a multi-tenant healthcare AI platform supporting
Arabic and English voice conversations.

Voice Architecture:

MicroSIP
    |
    v
Asterisk 22 (WSL2)
    |
    v
FastAPI Voice Gateway (8010)
    |
    +--> VAD
    +--> Hamsa STT / Deepgram Fallback
    |
    v
MedMind AI Backend (8001)
    |
    v
MCP Server (9000)
    |
    v
Backend APIs + SQL Server
    |
    v
Hamsa TTS
    |
    v
Asterisk --> MicroSIP

## 1. System Requirements

- Windows 10/11 with WSL2
- Ubuntu 24.04
- Asterisk 22.10.1
- Python 3.11 and Conda
- SQL Server
- MicroSIP
- Internet access for cloud AI services
- Valid AI, STT and TTS credentials

## 2. Clone and Prepare MedMind

Clone the repository and open the Backend directory.

In PowerShell:

    conda env create -f environment.yml
    conda activate healthcare-booking311

Review environment.yml before installation, especially
machine-specific paths or Conda prefixes.

Configure local environment variables and service credentials.
Never commit API keys, passwords or real patient information.

## 3. Install Asterisk

Open Ubuntu 24.04 through WSL2.

Navigate to the cloned Backend directory.

Run:

    bash asterisk/install.sh

Important:
The installer has passed Bash syntax validation but has not
yet been tested on a clean Ubuntu installation.

The installation includes an interactive menuselect step.

Required Asterisk modules:

- chan_websocket
- res_websocket_client
- res_http_websocket
- res_pjsip_transport_websocket
- res_pjsip

After installation, check:

    asterisk -V

Target version:

    Asterisk 22.10.1

## 4. Configure Asterisk

Configuration templates:

    asterisk/configs/

Asterisk configuration directory:

    /etc/asterisk/

Back up existing configurations before replacing them.

Files to configure:

- extensions.conf
- modules.conf
- chan_websocket.conf
- pjsip.conf
- websocket_client.conf

Copy pjsip.conf.example to pjsip.conf.

Replace:

    CHANGE_ME_STRONG_PASSWORD

with a unique SIP password.

Copy websocket_client.conf.example to websocket_client.conf.

Replace:

    WINDOWS_HOST_IP

with the Windows host IP address reachable from WSL2.

WebSocket URI:

    ws://WINDOWS_HOST_IP:8010/asterisk/media

In the tested WSL2 NAT setup, the Windows gateway can be
identified from Ubuntu with:

    ip route show default

Verify network reachability before configuring the URI.

The complete Asterisk configuration, including installation
paths, must be validated on a clean machine.

## 5. Start SQL Server

Start SQL Server and verify that the MedMind Backend
can connect to the configured database.

Database schema, migrations, provider data and credentials
must be prepared separately.

## 6. Start MCP Server

Open PowerShell inside Backend.

Activate the environment:

    conda activate healthcare-booking311

Configure MCP:

    $env:MCP_TENANT_ID = "clinic-001"
    $env:MCP_REQUEST_TIMEOUT = "30"
    $env:MCP_HOST = "127.0.0.1"
    $env:MCP_PORT = "9000"

Start MCP:

    python -u -m mcp_server.http_server

Expected server:

    http://127.0.0.1:9000

Keep this terminal running.

The clinic tenant is the currently tested configuration.
Other tenants require valid provider configuration.

## 7. Start MedMind Backend

Open another PowerShell terminal inside Backend.

    conda activate healthcare-booking311

Start:

    python -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --log-level info

Wait for:

    Application startup complete.

Expected backend:

    http://127.0.0.1:8001

Important:
Start MCP before Backend to avoid connection failures.

## 8. Start Voice Gateway

Open another PowerShell terminal inside Backend.

    conda activate healthcare-booking311

Start:

    python -m uvicorn voice_gateway.main:app --host 0.0.0.0 --port 8010

Verify from PowerShell:

    Invoke-RestMethod http://127.0.0.1:8010/health

Expected:

    status: ok
    service: medmind-voice-gateway

Binding to 0.0.0.0 is intended for trusted local development.
Restrict network access using appropriate firewall settings.

## 9. Start Asterisk

Inside Ubuntu:

    sudo asterisk -cvvvvv

If Asterisk is already running:

    sudo asterisk -rvvvvv

Verify installed modules:

    sudo asterisk -rx "module show like websocket"

Verify SIP endpoints:

    sudo asterisk -rx "pjsip show endpoints"

Verify dialplan:

    sudo asterisk -rx "dialplan show medmind-softphone"

## 10. Configure MicroSIP

Create a SIP account:

    Username: 1001
    Password: Your configured SIP password
    SIP Server: Reachable WSL2 Asterisk IP
    SIP Port: 5060
    Transport: UDP

The SIP server address depends on the local WSL2
networking configuration.

Allow the required SIP and RTP traffic on the local network.

## 11. Test Voice Extensions

7000 — Echo Audio Test

7001 — Clinic AI Receptionist
       Tenant: clinic-001

7002 — Hospital AI Receptionist
       Tenant: hospital-001

7003 — Laboratory AI Receptionist
       Tenant: lab-001

The clinic voice flow has been tested.

Hospital and laboratory extensions require their
corresponding providers and integrations to be configured
and tested independently.

## 12. Recommended Startup Order

1. SQL Server
2. MCP Server — 9000
3. MedMind Backend — 8001
4. Voice Gateway — 8010
5. Asterisk on Ubuntu
6. MicroSIP

## 13. Troubleshooting

### MCP Session Terminated

Possible cause:
Backend holds an MCP session that is no longer valid.

Actions:
- Verify MCP Server is running.
- Check MCP logs.
- Restart Backend after MCP if necessary.
- Confirm MCP tool calls succeed.

### WebSocket Connection Failure

Check:
- Voice Gateway is running on port 8010.
- Windows host address is correct.
- WSL2 can reach the Windows gateway.
- Asterisk WebSocket modules are available.

### SIP Registration Failure

Check:
- Username and password.
- PJSIP configuration.
- SIP server address.
- UDP port 5060 and firewall rules.

### Voice Agent Does Not Respond

Check:
- STT provider connectivity.
- MedMind Backend status.
- MCP tool execution.
- TTS provider connectivity.
- Voice Gateway logs.

### High Latency

Review:
- STT processing time.
- Semantic Router latency.
- Qwen Planner latency.
- Backend API latency.
- MCP tool execution.
- TTS first-audio latency.

## 14. Security Notes

- Never commit .env files or API keys.
- Never commit real SIP passwords.
- Do not expose local HTTP or WebSocket services publicly.
- Use appropriate firewall restrictions.
- Use tenant-aware authentication and authorization.
- Protect patient data and logs.
- Validate security and deployment settings before production.

## 15. Current Validation Status

Confirmed in the development environment:

- Asterisk 22.10.1 running
- SIP and WebSocket connectivity working
- Voice Gateway running
- MCP tools loading successfully
- Backend handling voice requests
- Arabic STT fallback working
- TTS playback working
- Clinic appointment workflow reached time selection

Not yet confirmed:

- Complete installation on a clean Ubuntu machine
- Full successful booking through the shared setup
- All hospital and laboratory tenant configurations
- Production readiness

This guide describes the development setup and should
be validated on each teammate's machine.
