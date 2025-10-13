import os
import json
import base64
import asyncio
import websockets
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, WebSocket, Request, HTTPException, WebSocketException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from twilio.request_validator import RequestValidator
from dotenv import load_dotenv

load_dotenv()

# Configuration
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
ZAPIER_MCP_URL = os.getenv('ZAPIER_MCP_URL')
ZAPIER_MCP_PASSWORD = os.getenv('ZAPIER_MCP_PASSWORD')
WEBHOOK_URL = os.getenv('WEBHOOK_URL')
ALLOWED_NUMBERS = os.getenv('ALLOWED_NUMBERS', '').split(',') if os.getenv('ALLOWED_NUMBERS') else []
PORT = int(os.getenv('PORT', 5050))
TEMPERATURE = float(os.getenv('TEMPERATURE', 0.8))
ASSISTANT_INSTRUCTIONS = os.getenv('ASSISTANT_INSTRUCTIONS')
VOICE = os.getenv('VOICE')
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created', 'session.updated', 'response.function_call_arguments.delta',
    'response.function_call_arguments.done'
]
SHOW_TIMING_MATH = False

app = FastAPI()

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok"}

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

if not TWILIO_AUTH_TOKEN:
    raise ValueError('Missing the Twilio Auth Token. Please set it in the .env file.')

if not ZAPIER_MCP_URL:
    raise ValueError('Missing ZAPIER_MCP_URL. Please set it in the .env file.')

if not ZAPIER_MCP_PASSWORD:
    raise ValueError('Missing ZAPIER_MCP_PASSWORD. Please set it in the .env file.')

if not ASSISTANT_INSTRUCTIONS:
    raise ValueError('Missing ASSISTANT_INSTRUCTIONS. Please set it in the .env file.')

if not VOICE:
    raise ValueError('Missing VOICE. Please set it in the .env file.')

validator = RequestValidator(TWILIO_AUTH_TOKEN)

# WebSocket token storage (token -> expiration timestamp)
websocket_tokens = {}

def generate_websocket_token():
    """Generate a secure token for WebSocket authentication."""
    token = secrets.token_urlsafe(32)
    expiration = datetime.now() + timedelta(seconds=60)
    websocket_tokens[token] = expiration
    return token

def cleanup_expired_tokens():
    """Remove expired tokens from storage."""
    now = datetime.now()
    expired = [token for token, exp in websocket_tokens.items() if exp < now]
    for token in expired:
        del websocket_tokens[token]

@app.post("/incoming-call")
async def handle_incoming_call(request: Request):
    """Handle incoming call and return TwiML response to connect to Media Stream."""
    # Verify Twilio signature
    # Use X-Forwarded-Proto and Host headers to construct the correct URL for validation
    # This handles both direct requests (local dev) and proxied requests (Fly.io)
    scheme = request.headers.get('X-Forwarded-Proto', request.url.scheme)
    host = request.headers.get('Host', request.url.netloc)
    path = str(request.url.path)
    query = str(request.url.query)
    url = f"{scheme}://{host}{path}"
    if query:
        url += f"?{query}"

    signature = request.headers.get('X-Twilio-Signature', '')

    # Get form data for validation
    form_data = await request.form()
    params = dict(form_data)

    if not validator.validate(url, params, signature):
        print(f"Signature validation failed. URL: {url}")
        print(f"Signature: {signature}")
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")

    # Clean up expired tokens periodically
    cleanup_expired_tokens()

    # Generate WebSocket token
    ws_token = generate_websocket_token()

    response = VoiceResponse()
    # response.pause(length=1)

    host = request.url.hostname
    connect = Connect()
    stream_url = f'wss://{host}/media-stream'
    print(f"Generated WebSocket URL: {stream_url}")
    print(f"Token: {ws_token}")
    stream = connect.stream(url=stream_url)
    stream.parameter(name='token', value=ws_token)
    response.append(connect)
    twiml_response = str(response)
    print(f"TwiML Response: {twiml_response}")
    return HTMLResponse(content=twiml_response, media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handle WebSocket connections between Twilio and OpenAI."""
    print(f"WebSocket connection attempt - Query params: {dict(websocket.query_params)}")

    # Twilio sends custom parameters in the 'start' event, not query params
    # We'll need to accept first, then validate from the start event
    await websocket.accept()

    # Wait for the start message to get custom parameters
    try:
        # Twilio sends 'connected' first, then 'start'
        token = None
        initial_stream_sid = None
        while True:
            message = await websocket.receive_text()
            data = json.loads(message)
            print(f"Received event: {data.get('event')}")

            if data.get('event') == 'start':
                # Get token from custom parameters
                custom_params = data.get('start', {}).get('customParameters', {})
                token = custom_params.get('token')
                # Save the streamSid for later use
                initial_stream_sid = data.get('start', {}).get('streamSid')
                print(f"Token from start event: {token}, StreamSid: {initial_stream_sid}")
                break
            elif data.get('event') == 'connected':
                # Skip the connected event
                continue
            else:
                # Unexpected event
                print(f"WebSocket rejected: Unexpected event {data.get('event')}")
                await websocket.close(code=1008, reason="Unexpected event")
                return

        if not token or token not in websocket_tokens:
            print(f"WebSocket rejected: Invalid or missing token. Token: {token}, Valid tokens: {list(websocket_tokens.keys())}")
            await websocket.close(code=1008, reason="Invalid or missing token")
            return

        # Check token expiration
        if datetime.now() > websocket_tokens[token]:
            del websocket_tokens[token]
            print(f"WebSocket rejected: Token expired")
            await websocket.close(code=1008, reason="Token expired")
            return

        # Remove token (single-use)
        del websocket_tokens[token]
        print(f"Client connected with valid token: {token}")

    except Exception as e:
        print(f"Error during WebSocket auth: {e}")
        await websocket.close(code=1011, reason="Authentication error")
        return

    async with websockets.connect(
        f"wss://api.openai.com/v1/realtime?model=gpt-realtime&temperature={TEMPERATURE}",
        additional_headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }
    ) as openai_ws:
        await initialize_session(openai_ws)

        # Connection specific state
        stream_sid = initial_stream_sid
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        
        async def receive_from_twilio():
            """Receive audio data from Twilio and send it to the OpenAI Realtime API."""
            nonlocal stream_sid, latest_media_timestamp
            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data['event'] == 'media' and openai_ws.state.name == 'OPEN':
                        latest_media_timestamp = int(data['media']['timestamp'])
                        audio_append = {
                            "type": "input_audio_buffer.append",
                            "audio": data['media']['payload']
                        }
                        await openai_ws.send(json.dumps(audio_append))
                    elif data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
            except WebSocketDisconnect:
                print("Client disconnected.")
                if openai_ws.state.name == 'OPEN':
                    await openai_ws.close()

        async def send_to_twilio():
            """Receive events from the OpenAI Realtime API, send audio back to Twilio."""
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio
            try:
                async for openai_message in openai_ws:
                    response = json.loads(openai_message)
                    if response['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response['type']}", response)

                    if response.get('type') == 'response.output_audio.delta' and 'delta' in response:
                        audio_payload = base64.b64encode(base64.b64decode(response['delta'])).decode('utf-8')
                        audio_delta = {
                            "event": "media",
                            "streamSid": stream_sid,
                            "media": {
                                "payload": audio_payload
                            }
                        }
                        await websocket.send_json(audio_delta)


                        if response.get("item_id") and response["item_id"] != last_assistant_item:
                            response_start_timestamp_twilio = latest_media_timestamp
                            last_assistant_item = response["item_id"]
                            if SHOW_TIMING_MATH:
                                print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")

                        await send_mark(websocket, stream_sid)

                    # Trigger an interruption. Your use case might work better using `input_audio_buffer.speech_stopped`, or combining the two.
                    if response.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")

        async def handle_speech_started_event():
            """Handle interruption when the caller's speech starts."""
            nonlocal response_start_timestamp_twilio, last_assistant_item
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                if SHOW_TIMING_MATH:
                    print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")

                if last_assistant_item:
                    if SHOW_TIMING_MATH:
                        print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")

                    truncate_event = {
                        "type": "conversation.item.truncate",
                        "item_id": last_assistant_item,
                        "content_index": 0,
                        "audio_end_ms": elapsed_time
                    }
                    await openai_ws.send(json.dumps(truncate_event))

                await websocket.send_json({
                    "event": "clear",
                    "streamSid": stream_sid
                })

                mark_queue.clear()
                last_assistant_item = None
                response_start_timestamp_twilio = None

        async def send_mark(connection, stream_sid):
            if stream_sid:
                mark_event = {
                    "event": "mark",
                    "streamSid": stream_sid,
                    "mark": {"name": "responsePart"}
                }
                await connection.send_json(mark_event)
                mark_queue.append('responsePart')

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

async def send_initial_conversation_item(openai_ws):
    """Send initial conversation item if AI talks first."""
    initial_conversation_item = {
        "type": "conversation.item.create",
        "item": {
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": "Greet the user with 'Hey, what's up?'"
                }
            ]
        }
    }
    await openai_ws.send(json.dumps(initial_conversation_item))
    await openai_ws.send(json.dumps({"type": "response.create"}))


async def initialize_session(openai_ws):
    """Control initial session with OpenAI."""
    session_config = {
        "type": "realtime",
        "model": "gpt-realtime",
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "format": {"type": "audio/pcmu"},
                "turn_detection": {"type": "server_vad"}
            },
            "output": {
                "format": {"type": "audio/pcmu"},
                "voice": VOICE
            }
        },
        "instructions": ASSISTANT_INSTRUCTIONS,
        "tools": [
            {
                "type": "mcp",
                "server_label": "zapier",
                "server_url": ZAPIER_MCP_URL,
                "headers": {
                    "Authorization": f"Bearer {ZAPIER_MCP_PASSWORD}"
                },
                "require_approval": "never"
            }
        ]
    }

    session_update = {
        "type": "session.update",
        "session": session_config
    }
    print('Sending session update:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))

    # Wait for and log the session.updated response to see what tools are registered
    response = await openai_ws.recv()
    response_data = json.loads(response)
    print(f"Session update response: {json.dumps(response_data, indent=2)}")

    if response_data.get('type') == 'session.updated':
        tools = response_data.get('session', {}).get('tools', [])
        print(f"Registered tools count: {len(tools)}")
        for tool in tools:
            print(f"Tool: {tool.get('type')} - {tool.get('server_label')} - allowed_tools: {tool.get('allowed_tools')}")

    # Have the AI speak first
    await send_initial_conversation_item(openai_ws)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
