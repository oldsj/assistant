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
- `ASSISTANT_INSTRUCTIONS` - General assistant personality and behavior
- `TODOIST_INSTRUCTIONS` - Todoist-specific tool usage instructions (combined with assistant instructions)
- `TODOIST_MCP_URL` - URL of the Todoist MCP server (e.g., `https://todoist-mcp.fly.dev`)
- `TODOIST_MCP_PASSWORD` - Password for MCP server authentication
- `VOICE` - OpenAI voice (alloy, shimmer, nova, etc.)
- `PORT` - Server port (default: 5050)
- `TEMPERATURE` - AI temperature (default: 0.8)

Note: `WEBHOOK_URL` and `ALLOWED_NUMBERS` are **only** used in the Twilio Function, not in the FastAPI application.

### Instruction Separation

The assistant uses two separate instruction sets that are combined at runtime:
1. **`ASSISTANT_INSTRUCTIONS`**: General personality, tone, and behavior
2. **`TODOIST_INSTRUCTIONS`**: Specific instructions for when and how to use Todoist tools

This separation allows you to:
- Update the assistant's personality without affecting tool behavior
- Modify tool instructions without changing the general behavior
- Easily add more tool-specific instructions in the future

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

### MCP Server Integration (Todoist)

The assistant integrates with Todoist via an MCP (Model Context Protocol) server running on Fly.io as a **public HTTPS endpoint** with password authentication.

**Setup:**
```bash
make launch-mcp      # Deploy MCP server with password auth & Claude Desktop config
make logs-mcp        # View MCP server logs
```

**Password Authentication:**
- Uses password-based authentication for MCP server access
- Password is set via `TODOIST_MCP_PASSWORD` environment variable in `.env`
- Automatically added to Claude Desktop configuration with `--claude` flag
- Provides secure access to the public endpoint

**MCP Server Configuration:**
- Command: `npx -y @doist/todoist-ai`
- Memory: 256MB (minimal footprint)
- Auto-suspend when idle to reduce costs
- Requires `TODOIST_API_KEY` secret (set from `.env` during launch)
- Public HTTPS endpoint: `https://todoist-mcp.fly.dev`

**Connection Flow:**
1. OpenAI Realtime API session initializes with MCP tools configured (`main.py:337-344`)
2. Main app connects to MCP server via HTTPS: `https://todoist-mcp.fly.dev`
3. Password authentication is handled by MCP protocol
4. MCP server auto-starts on first request if suspended

**Testing MCP Connectivity:**
- Cannot test with simple HTTP requests (MCP expects specific protocol)
- Connection validated when OpenAI makes MCP tool calls during conversations
- Check logs: `make logs-mcp` to see MCP server activity

**Common Issues:**
- **401 Unauthorized:** Missing or invalid password in `TODOIST_MCP_PASSWORD`
- **Timeout:** MCP server may be starting (first request after suspend takes 2-5 seconds)
- **Not in Claude Desktop:** Verify `~/Library/Application Support/Claude/claude_desktop_config.json` has the MCP server entry
- **Tools not being called:** Check logs for `allowed_tools` field in session.updated event. If `None`, the MCP server may not be exposing tools properly to the Realtime API.

### Debugging MCP Tool Calls

The application includes enhanced logging to debug MCP tool discovery:

1. **Check session configuration:** After deployment, check logs for:
   ```
   Registered tools count: X
   Tool: mcp - todoist - allowed_tools: [...]
   ```

2. **Look for tool call events:** The logs will show if OpenAI is attempting to call tools:
   - `response.function_call_arguments.delta` - Function call in progress
   - `response.function_call_arguments.done` - Function call completed
   - If you see `output_text` with JSON instead, the AI is simulating tool calls rather than making real ones

3. **Verify MCP server health:**
   ```bash
   make logs-mcp  # Check if MCP server is receiving requests
   ```

**Known Limitation:** OpenAI's Realtime API MCP support may be experimental. If tools aren't being called properly, consider using explicit function definitions instead of MCP (see Alternative Approaches below).

### Makefile Targets

```bash
make dev             # Run locally
make deploy          # Deploy main app to Fly.io
make launch-mcp      # Launch MCP server using fly mcp launch
make inspect-mcp     # Open MCP inspector to test the server
make logs            # View logs for both apps
make logs-mcp        # View MCP server logs only
make tunnel-quick    # Start development tunnel
```

## Alternative Approaches

### Using Explicit Function Definitions Instead of MCP

If MCP integration isn't working with the Realtime API, you can define Todoist functions explicitly:

```python
"tools": [
    {
        "type": "function",
        "name": "create_task",
        "description": "Create a new task in Todoist",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Task content"},
                "due_string": {"type": "string", "description": "Due date in natural language (e.g., 'today', 'tomorrow')"},
                "project_id": {"type": "string", "description": "Project ID (optional)"}
            },
            "required": ["content"]
        }
    },
    {
        "type": "function",
        "name": "get_tasks",
        "description": "Get tasks from Todoist",
        "parameters": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Filter by project ID (optional)"}
            }
        }
    }
]
```

Then implement a handler to forward function calls to the MCP server manually. This gives you full control over the integration and ensures the AI can actually invoke the tools.
