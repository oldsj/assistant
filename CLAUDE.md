## Important

**This is a PUBLIC repository.** Never include PII (personally identifiable information) in any files:
- No real IP addresses, phone numbers, or domain names in examples
- No API keys, tokens, or credentials
- Use example/placeholder values only (e.g., `+15551234567`, `your-domain.com`, → reference to command output)

## Project Overview

This is a personal voice assistant that bridges Twilio Voice and OpenAI's Realtime API for phone-based AI conversations. The architecture uses a FastAPI server as a WebSocket relay between Twilio's Media Streams and OpenAI's Realtime API.

## Development Commands

**Run the application:**
```bash
make dev
# or directly: uv run python main.py
```

**Start cloudflared tunnel:**
```bash
make tunnel-quick    # Quick temporary tunnel with random URL
make tunnel          # Named tunnel with stable domain (requires setup)
```

**Docker:**
```bash
docker compose up                  # Run without tunnel
docker compose --profile dev up    # Run with cloudflared tunnel
```

**Fly.io deployment:**
```bash
fly deploy           # Deploy to Fly.io
fly logs             # View logs
fly status           # Get app URL and status
```

## Architecture

### Three-Layer Security Model

1. **Layer 1: Twilio Function Allowlist** (`twilio/allowlist-function.js`)
   - Runs on Twilio's serverless infrastructure
   - Filters calls by phone number before they reach your server
   - Configured via Twilio Console with `ALLOWED_NUMBERS` and `WEBHOOK_URL` environment variables
   - Only allowed numbers are redirected to the FastAPI server

2. **Layer 2: Twilio Signature Validation** (`main.py:67-79`)
   - Validates webhook requests using HMAC-SHA1 with `TWILIO_AUTH_TOKEN`
   - Ensures requests are authentic and untampered

3. **Layer 3: WebSocket Token Authentication** (`main.py:50-157`)
   - Single-use tokens with 60-second expiration
   - Generated in `/incoming-call` endpoint, validated in `/media-stream` WebSocket
   - Prevents unauthorized WebSocket connections

### Request Flow

1. Caller dials Twilio number
2. Twilio sends webhook to Twilio Function (Layer 1)
3. Function checks allowlist, redirects to FastAPI `/incoming-call` if approved
4. FastAPI validates signature (Layer 2), generates WebSocket token
5. Returns TwiML with WebSocket URL + token
6. Twilio connects to `/media-stream` WebSocket with token
7. FastAPI validates token (Layer 3), removes it (single-use)
8. Establishes OpenAI WebSocket connection
9. Bidirectional audio streaming begins

### Key WebSocket Patterns

**Interruption Handling** (`main.py:239-268`):
- Listens for `input_audio_buffer.speech_started` events
- Calculates elapsed audio time using Twilio's media timestamps
- Sends `conversation.item.truncate` to OpenAI to cut off AI mid-sentence
- Sends `clear` event to Twilio to stop playback
- Enables natural conversation interruptions

**Audio Relay** (`main.py:174-238`):
- `receive_from_twilio()`: Forwards Twilio audio chunks to OpenAI as `input_audio_buffer.append`
- `send_to_twilio()`: Forwards OpenAI `response.output_audio.delta` events to Twilio
- Both run concurrently using `asyncio.gather()`

**Mark Queue** (`main.py:171, 269-277`):
- Tracks audio chunks sent to Twilio for synchronization
- Used to calculate precise truncation points during interruptions

## Configuration

Environment variables are loaded from `.env` (not committed):
- `OPENAI_API_KEY` - Required for Realtime API access
- `TWILIO_AUTH_TOKEN` - Required for signature validation
- `ASSISTANT_INSTRUCTIONS` - Assistant personality, behavior, and tool usage instructions
- `ZAPIER_MCP_URL` - URL of the Zapier MCP server (e.g., `https://mcp.zapier.com/api/mcp/mcp`)
- `ZAPIER_MCP_PASSWORD` - API key for Zapier MCP authentication (base64 encoded)
- `VOICE` - OpenAI voice (alloy, shimmer, nova, etc.)
- `PORT` - Server port (default: 5050)
- `TEMPERATURE` - AI temperature (default: 0.8)

Note: `WEBHOOK_URL` and `ALLOWED_NUMBERS` are **only** used in the Twilio Function, not in the FastAPI application.

## AI-First Greeting

To enable AI speaking first when a call connects, uncomment line 325 in `main.py`:
```python
await send_initial_conversation_item(openai_ws)
```

This sends an initial user message prompting the AI to greet the caller.

## Audio Format

Both Twilio and OpenAI use μ-law (PCMU) encoding at 8kHz for compatibility without transcoding.

## Fly.io Deployment & MCP Integration

### Main Application Deployment

The main FastAPI application is deployed to Fly.io with a blue-green deployment strategy for zero-downtime updates:

```bash
make deploy          # Deploys both MCP and main app
fly logs             # View application logs
fly status           # Check deployment status
```

**Important Fly.io Configuration:**
- Uses `blue-green` deployment strategy (`fly.toml:12`)
- Health checks ensure new machines are ready before traffic switches (`fly.toml:22-27`)
- Secrets are managed via `fly secrets set` (never committed to git)

### MCP Server Integration (Zapier)

The assistant integrates with Zapier via an MCP (Model Context Protocol) server. Zapier connects to multiple services including:
- **Todoist**: Task management and reminders
- **Gmail**: Email search and management

**Zapier MCP Setup:**
1. Get your API key from: https://zapier.com/app/developer/mcp
2. Set `ZAPIER_MCP_URL=https://mcp.zapier.com/api/mcp/mcp` in `.env`
3. Set `ZAPIER_MCP_PASSWORD=your_zapier_api_key_base64` in `.env`

**Connection Flow:**
1. OpenAI Realtime API session initializes with MCP tools configured (`main.py:342-351`)
2. Main app connects to Zapier MCP server via HTTPS
3. API key authentication is handled by MCP protocol
4. Zapier routes tool calls to configured integrations (Todoist, Gmail, etc.)

**Common Issues:**
- **401 Unauthorized:** Missing or invalid API key in `ZAPIER_MCP_PASSWORD`
- **Tools not being called:** Check logs for `allowed_tools` field in session.updated event. If `None`, the MCP server may not be exposing tools properly to the Realtime API.

### Debugging MCP Tool Calls

The application includes enhanced logging to debug MCP tool discovery:

1. **Check session configuration:** After deployment, check logs for:
   ```
   Registered tools count: X
   Tool: mcp - zapier - allowed_tools: [...]
   ```

2. **Look for tool call events:** The logs will show if OpenAI is attempting to call tools:
   - `response.function_call_arguments.delta` - Function call in progress
   - `response.function_call_arguments.done` - Function call completed
   - If you see `output_text` with JSON instead, the AI is simulating tool calls rather than making real ones

**Known Limitation:** OpenAI's Realtime API MCP support may be experimental. If tools aren't being called properly, consider using explicit function definitions instead of MCP (see Alternative Approaches below).

### Makefile Targets

```bash
make dev             # Run locally
make deploy          # Deploy main app to Fly.io
make tunnel-quick    # Start development tunnel
```

## Alternative Approaches

### Using Explicit Function Definitions Instead of MCP

If MCP integration isn't working with the Realtime API, you can define functions explicitly and implement handlers to forward calls to Zapier or directly to service APIs. This gives you full control over the integration and ensures the AI can actually invoke the tools.
