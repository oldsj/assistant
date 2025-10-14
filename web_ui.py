import os
import asyncio
import streamlit as st
from agents import Agent, HostedMCPTool, Runner
from dotenv import load_dotenv

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
ASSISTANT_INSTRUCTIONS = os.getenv('ASSISTANT_INSTRUCTIONS')
ZAPIER_MCP_URL = os.getenv('ZAPIER_MCP_URL')
ZAPIER_MCP_PASSWORD = os.getenv('ZAPIER_MCP_PASSWORD')

if not OPENAI_API_KEY:
    st.error('Missing OPENAI_API_KEY. Please set it in the .env file.')
    st.stop()

if not ASSISTANT_INSTRUCTIONS:
    st.error('Missing ASSISTANT_INSTRUCTIONS. Please set it in the .env file.')
    st.stop()

if not ZAPIER_MCP_URL or not ZAPIER_MCP_PASSWORD:
    st.warning('Zapier MCP not configured. Tools will be unavailable.')

st.set_page_config(
    page_title="Assistant Chat",
    page_icon="🤖",
    layout="wide"
)

st.title("🤖 Assistant Chat")
st.markdown("Text-based interface for your AI assistant with Zapier integration")

@st.cache_resource
def get_agent():
    tools = []

    if ZAPIER_MCP_URL and ZAPIER_MCP_PASSWORD:
        tools.append(
            HostedMCPTool(
                tool_config={
                    "type": "mcp",
                    "server_label": "zapier",
                    "server_url": ZAPIER_MCP_URL,
                    "headers": {
                        "Authorization": f"Bearer {ZAPIER_MCP_PASSWORD}"
                    },
                    "require_approval": "never"
                }
            )
        )

    return Agent(
        name="Assistant",
        instructions=ASSISTANT_INSTRUCTIONS,
        model="gpt-4o",
        tools=tools
    )

agent = get_agent()

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("Ask me anything..."):
    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        message_placeholder = st.empty()

        try:
            async def run_agent():
                return await Runner.run(
                    starting_agent=agent,
                    input=prompt
                )

            result = asyncio.run(run_agent())

            full_response = ""
            if result.final_output:
                full_response = result.final_output

            message_placeholder.markdown(full_response)

        except Exception as e:
            full_response = f"Error: {str(e)}"
            message_placeholder.error(full_response)
            import traceback
            st.error(traceback.format_exc())

    st.session_state.messages.append({"role": "assistant", "content": full_response})

with st.sidebar:
    has_tools = bool(ZAPIER_MCP_URL and ZAPIER_MCP_PASSWORD)
    status = "✅ Connected" if has_tools else "⚠️ Not configured"

    st.markdown(f"**Zapier MCP:** {status}")

    if st.button("Clear Chat History"):
        st.session_state.messages = []
        st.rerun()
