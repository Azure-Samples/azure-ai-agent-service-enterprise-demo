import os
import re
import signal
import sys
from datetime import datetime as pydatetime
from typing import Any, List, Dict
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import uvicorn
import threading
import time
from azure.core.exceptions import ResourceExistsError
from azure.core.pipeline.policies import RetryPolicy
from azure.core.pipeline.transport import RequestsTransport


# (Optional) Gradio app for UI
import gradio as gr
from gradio import ChatMessage

# Azure AI Projects
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    AgentEventHandler,
    RunStep,
    RunStepDeltaChunk,
    ThreadMessage,
    ThreadRun,
    MessageDeltaChunk,
    BingGroundingTool,
    FilePurpose,
    FileSearchTool,
    FunctionTool,
    ToolSet
)

# Your custom Python functions (for "fetch_weather","fetch_stock_price","send_email","fetch_datetime", etc.)
from enterprise_functions import enterprise_fns

load_dotenv(override=True)

# Create Client and Load Azure AI Foundry with increased timeout and retry policy
credential = DefaultAzureCredential()
retry_policy = RetryPolicy()
transport = RequestsTransport(connection_timeout=600, read_timeout=600)
project_client = AIProjectClient.from_connection_string(
    credential=credential,
    conn_str=os.environ["PROJECT_CONNECTION_STRING"],
    retry_policy=retry_policy,
    transport=transport
)

# Get the agent name from the environment variables
AGENT_NAME = os.environ["AGENT_NAME"]

# Find the agent by name
found_agent = None
all_agents_list = project_client.agents.list_agents().data
for a in all_agents_list:
    if a.name == AGENT_NAME:
        found_agent = a
        break

if not found_agent:
    raise ValueError(f"Agent with name '{AGENT_NAME}' not found.")

agent_id = found_agent.id
print(f"Using agent > {found_agent.name} (id: {agent_id})")

# Print the value of BING_CONNECTION_NAME for debugging
print(f"BING_CONNECTION_NAME: {os.environ['BING_CONNECTION_NAME']}")

# Set Up Tools (BingGroundingTool, FileSearchTool)
try:
    bing_connection = project_client.connections.get(connection_name=os.environ["BING_CONNECTION_NAME"])
    conn_id = bing_connection.id
    bing_tool = BingGroundingTool(connection_id=conn_id)
    print("bing > connected")
except Exception as e:
    bing_tool = None
    print(f"bing failed > no connection found or permission issue: {e}")

VECTOR_STORE_NAME = os.environ["VECTOR_STORE_NAME"]
all_vector_stores = project_client.agents.list_vector_stores().data
existing_vector_store = next(
    (store for store in all_vector_stores if store.name == VECTOR_STORE_NAME),
    None
)

vector_store_id = None
if existing_vector_store:
    vector_store_id = existing_vector_store.id
    print(f"reusing vector store > {existing_vector_store.name} (id: {existing_vector_store.id})")

file_search_tool = None
if vector_store_id:
    file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])
    print("file search > connected")

# Combine All Tools into a ToolSet
class LoggingToolSet(ToolSet):
    def add(self, tool):
        super().add(tool)
        tool_name = getattr(tool, 'name', type(tool).__name__)
        print(f"tool > added {tool_name}")

toolset = LoggingToolSet()
if bing_tool:
    toolset.add(bing_tool)
if file_search_tool:
    toolset.add(file_search_tool)

custom_functions = FunctionTool(enterprise_fns)
toolset.add(custom_functions)

for tool in toolset._tools:
    tool_name = getattr(tool, 'name', type(tool).__name__)
    print(f"tool > {tool_name}")

# Update the existing agent to use new tools
def update_agent_with_retry(agent_id, model, instructions, toolset, retries=3, delay=5):
    for attempt in range(retries):
        try:
            return project_client.agents.update_agent(
                assistant_id=agent_id,
                model=model,
                instructions=instructions,
                toolset=toolset,
            )
        except ResourceExistsError:
            if attempt < retries - 1:
                print(f"Retrying update_agent... attempt {attempt + 1}")
                time.sleep(delay)
            else:
                raise

agent = update_agent_with_retry(
    agent_id=found_agent.id,
    model=found_agent.model,
    instructions=found_agent.instructions,
    toolset=toolset,
)
print(f"reusing agent > {agent.name} (id: {agent.id})")

# Create a Conversation Thread
thread = project_client.agents.create_thread()
print(f"thread > created (id: {thread.id})")

# Define a Custom Event Handler
class MyEventHandler(AgentEventHandler):
    def __init__(self):
        super().__init__()
        self._current_message_id = None
        self._accumulated_text = ""

    def on_message_delta(self, delta: MessageDeltaChunk) -> None:
        # If a new message id, start fresh
        if delta.id != self._current_message_id:
            # First, if we had an old message that wasn't completed, finish that line
            if self._current_message_id is not None:
                print()  # move to a new line
            
            self._current_message_id = delta.id
            self._accumulated_text = ""
            print("\nassistant > ", end="")  # prefix for new message

        # Accumulate partial text
        partial_text = ""
        if delta.delta.content:
            for chunk in delta.delta.content:
                partial_text += chunk.text.get("value", "")
        self._accumulated_text += partial_text

        # Print partial text with no newline
        print(partial_text, end="", flush=True)

    def on_thread_message(self, message: ThreadMessage) -> None:
        # When the assistant's entire message is "completed", print a final newline
        if message.status == "completed" and message.role == "assistant":
            print()  # done with this line
            self._current_message_id = None
            self._accumulated_text = ""
        else:
            # For other roles or statuses, you can log if you like:
            print(f"{message.status.name.lower()} (id: {message.id})")

    def on_thread_run(self, run: ThreadRun) -> None:
        print(f"status > {run.status.name.lower()}")
        if run.status == "failed":
            print(f"error > {run.last_error}")

    def on_run_step(self, step: RunStep) -> None:
        print(f"{step.type.name.lower()} > {step.status.name.lower()}")

    def on_run_step_delta(self, delta: RunStepDeltaChunk) -> None:
        # If partial tool calls come in, we log them
        if delta.delta.step_details and delta.delta.step_details.tool_calls:
            for tcall in delta.delta.step_details.tool_calls:
                if getattr(tcall, "function", None):
                    if tcall.function.name is not None:
                        print(f"tool call > {tcall.function.name}")

    def on_unhandled_event(self, event_type: str, event_data):
        print(f"unhandled > {event_type} > {event_data}")

    def on_error(self, data: str) -> None:
        print(f"error > {data}")

    def on_done(self) -> None:
        print("done")

# Implement the Main Chat Functions
def extract_bing_query(request_url: str) -> str:
    """
    Extract the query string from something like:
      https://api.bing.microsoft.com/v7.0/search?q="latest news about Microsoft January 2025"
    Returns: latest news about Microsoft January 2025
    """
    match = re.search(r'q="([^"]+)"', request_url)
    if match:
        return match.group(1)
    # If no match, fall back to entire request_url
    return request_url

def convert_dict_to_chatmessage(msg: dict) -> ChatMessage:
    """
    Convert a legacy dict-based message to a gr.ChatMessage.
    Uses the 'metadata' sub-dict if present.
    """
    return ChatMessage(
        role=msg["role"],
        content=msg["content"],
        metadata=msg.get("metadata", None)
    )

def azure_enterprise_chat(user_message: str, history: List[dict]):
    """
    Accumulates partial function arguments into ChatMessage['content'], sets the
    corresponding tool bubble status from "pending" to "done" on completion,
    and also handles non-function calls like bing_grounding or file_search by appending a
    "pending" bubble. Then it moves them to "done" once tool calls complete.

    This function returns a list of ChatMessage objects directly (no dict conversion).
    Your Gradio Chatbot should be type="messages" to handle them properly.
    """
    # Convert existing history from dict to ChatMessage
    conversation = []
    for msg_dict in history:
        conversation.append(convert_dict_to_chatmessage(msg_dict))

    # Append the user's new message
    conversation.append(ChatMessage(role="user", content=user_message))

    # Immediately yield two outputs to clear the textbox
    yield conversation, ""

    # Post user message to the thread (for your back-end logic)
    project_client.agents.create_message(
        thread_id=thread.id,
        role="user",
        content=user_message
    )

    # Mappings for partial function calls
    call_id_for_index: Dict[int, str] = {}
    partial_calls_by_index: Dict[int, dict] = {}
    partial_calls_by_id: Dict[str, dict] = {}
    in_progress_tools: Dict[str, ChatMessage] = {}

    # Titles for tool bubbles
    function_titles = {
        "fetch_weather": "☁️ fetching weather",
        "fetch_datetime": "🕒 fetching datetime",
        "fetch_stock_price": "📈 fetching financial info",
        "send_email": "✉️ sending mail",
        "file_search": "📄 searching docs",
        "bing_grounding": "🔍 searching bing",
    }

    def get_function_title(fn_name: str) -> str:
        return function_titles.get(fn_name, f"🛠 calling {fn_name}")

    def accumulate_args(storage: dict, name_chunk: str, arg_chunk: str):
        """Accumulates partial JSON data for a function call."""
        if name_chunk:
            storage["name"] += name_chunk
        if arg_chunk:
            storage["args"] += arg_chunk

    def finalize_tool_call(call_id: str):
        """Creates or updates the ChatMessage bubble for a function call."""
        if call_id not in partial_calls_by_id:
            return
        data = partial_calls_by_id[call_id]
        fn_name = data["name"].strip()
        fn_args = data["args"].strip()
        if not fn_name:
            return

        if call_id not in in_progress_tools:
            # Create a new bubble with status="pending"
            msg_obj = ChatMessage(
                role="assistant",
                content=fn_args or "",
                metadata={
                    "title": get_function_title(fn_name),
                    "status": "pending",
                    "id": f"tool-{call_id}"
                }
            )
            conversation.append(msg_obj)
            in_progress_tools[call_id] = msg_obj
        else:
            # Update existing bubble
            msg_obj = in_progress_tools[call_id]
            msg_obj.content = fn_args or ""
            msg_obj.metadata["title"] = get_function_title(fn_name)

    def upsert_tool_call(tcall: dict):
        """
        1) Check the call type
        2) If "function", gather partial name/args
        3) If "bing_grounding" or "file_search", show a pending bubble
        """
        t_type = tcall.get("type", "")
        call_id = tcall.get("id")

        # --- BING GROUNDING ---
        if t_type == "bing_grounding":
            request_url = tcall.get("bing_grounding", {}).get("requesturl", "")
            if not request_url.strip():
                return

            query_str = extract_bing_query(request_url)
            if not query_str.strip():
                return

            msg_obj = ChatMessage(
                role="assistant",
                content=query_str,
                metadata={
                    "title": get_function_title("bing_grounding"),
                    "status": "pending",
                    "id": f"tool-{call_id}" if call_id else "tool-noid"
                }
            )
            conversation.append(msg_obj)
            if call_id:
                in_progress_tools[call_id] = msg_obj
            return

        # --- FILE SEARCH ---
        elif t_type == "file_search":
            msg_obj = ChatMessage(
                role="assistant",
                content="searching docs...",
                metadata={
                    "title": get_function_title("file_search"),
                    "status": "pending",
                    "id": f"tool-{call_id}" if call_id else "tool-noid"
                }
            )
            conversation.append(msg_obj)
            if call_id:
                in_progress_tools[call_id] = msg_obj
            return

        # --- NON-FUNCTION CALLS ---
        elif t_type != "function":
            return

        # --- FUNCTION CALL PARTIAL-ARGS ---
        index = tcall.get("index")
        new_call_id = call_id
        fn_data = tcall.get("function", {})
        name_chunk = fn_data.get("name", "")
        arg_chunk = fn_data.get("arguments", "")

        if new_call_id:
            call_id_for_index[index] = new_call_id

        call_id = call_id_for_index.get(index)
        if not call_id:
            # Accumulate partial
            if index not in partial_calls_by_index:
                partial_calls_by_index[index] = {"name": "", "args": ""}
            accumulate_args(partial_calls_by_index[index], name_chunk, arg_chunk)
            return

        if call_id not in partial_calls_by_id:
            partial_calls_by_id[call_id] = {"name": "", "args": ""}

        if index in partial_calls_by_index:
            old_data = partial_calls_by_index.pop(index)
            partial_calls_by_id[call_id]["name"] += old_data.get("name", "")
            partial_calls_by_id[call_id]["args"] += old_data.get("args", "")

        # Accumulate partial
        accumulate_args(partial_calls_by_id[call_id], name_chunk, arg_chunk)

        # Create/update the function bubble
        finalize_tool_call(call_id)

    # -- EVENT STREAMING --
    with project_client.agents.create_stream(
        thread_id=thread.id,
        assistant_id=agent_id,
        event_handler=MyEventHandler()  # the event handler handles console output
    ) as stream:
        for item in stream:
            event_type, event_data, *_ = item

            # Remove any None items that might have been appended
            conversation = [m for m in conversation if m is not None]

            # 1) Partial tool calls
            if event_type == "thread.run.step.delta":
                step_delta = event_data.get("delta", {}).get("step_details", {})
                if step_delta.get("type") == "tool_calls":
                    for tcall in step_delta.get("tool_calls", []):
                        upsert_tool_call(tcall)
                    yield conversation, ""

            # 2) run_step
            elif event_type == "run_step":
                step_type = event_data["type"]
                step_status = event_data["status"]

                # If tool calls are in progress, new or partial
                if step_type == "tool_calls" and step_status == "in_progress":
                    for tcall in event_data["step_details"].get("tool_calls", []):
                        upsert_tool_call(tcall)
                    yield conversation, ""

                elif step_type == "tool_calls" and step_status == "completed":
                    for cid, msg_obj in in_progress_tools.items():
                        msg_obj.metadata["status"] = "done"
                    in_progress_tools.clear()
                    partial_calls_by_id.clear()
                    partial_calls_by_index.clear()
                    call_id_for_index.clear()
                    yield conversation, ""

                elif step_type == "message_creation" and step_status == "in_progress":
                    msg_id = event_data["step_details"]["message_creation"].get("message_id")
                    if msg_id:
                        conversation.append(ChatMessage(role="assistant", content=""))
                    yield conversation, ""

                elif step_type == "message_creation" and step_status == "completed":
                    yield conversation, ""

            # 3) partial text from the assistant
            elif event_type == "thread.message.delta":
                agent_msg = ""
                for chunk in event_data["delta"]["content"]:
                    agent_msg += chunk["text"].get("value", "")

                message_id = event_data["id"]

                # Try to find a matching assistant bubble
                matching_msg = None
                for msg in reversed(conversation):
                    if msg.metadata and msg.metadata.get("id") == message_id and msg.role == "assistant":
                        matching_msg = msg
                        break

                if matching_msg:
                    # Append newly streamed text
                    matching_msg.content += agent_msg
                else:
                    # Append to last assistant or create new
                    if (
                        not conversation
                        or conversation[-1].role != "assistant"
                        or (
                            conversation[-1].metadata
                            and str(conversation[-1].metadata.get("id", "")).startswith("tool-")
                        )
                    ):
                        conversation.append(ChatMessage(role="assistant", content=agent_msg))
                    else:
                        conversation[-1].content += agent_msg

                yield conversation, ""

            # 4) If entire assistant message is completed
            elif event_type == "thread.message":
                if event_data["role"] == "assistant" and event_data["status"] == "completed":
                    for cid, msg_obj in in_progress_tools.items():
                        msg_obj.metadata["status"] = "done"
                    in_progress_tools.clear()
                    partial_calls_by_id.clear()
                    partial_calls_by_index.clear()
                    call_id_for_index.clear()
                    yield conversation, ""

            # 5) Final done
            elif event_type == "thread.message.completed":
                for cid, msg_obj in in_progress_tools.items():
                    msg_obj.metadata["status"] = "done"
                in_progress_tools.clear()
                partial_calls_by_id.clear()
                partial_calls_by_index.clear()
                call_id_for_index.clear()
                yield conversation, ""
                break

    return conversation, ""

# Initialize FastAPI app
import sys
import threading
import signal
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import gradio as gr
import uvicorn

# Initialize FastAPI app
app = FastAPI()

# Allow CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define the Gradio interface
brand_theme = gr.themes.Default(
    primary_hue="blue",
    secondary_hue="blue",
    neutral_hue="gray",
    font=["Segoe UI", "Arial", "sans-serif"],
    font_mono=["Courier New", "monospace"],
    text_size="lg",
).set(
    button_primary_background_fill="#0f6cbd",
    button_primary_background_fill_hover="#115ea3",
    button_primary_background_fill_hover_dark="#4f52b2",
    button_primary_background_fill_dark="#5b5fc7",
    button_primary_text_color="#ffffff",
    button_secondary_background_fill="#e0e0e0",
    button_secondary_background_fill_hover="#c0c0c0",
    button_secondary_background_fill_hover_dark="#a0a0a0",
    button_secondary_text_color="#000000",
    body_background_fill="#f5f5f5",
    block_background_fill="#ffffff",
    body_text_color="#242424",
    body_text_color_subdued="#616161",
    block_border_color="#d1d1d1",
    block_border_color_dark="#333333",
    input_background_fill="#ffffff",
    input_border_color="#d1d1d1",
    input_border_color_focus="#0f6cbd",
)

with gr.Blocks(theme=brand_theme, css="footer {visibility: hidden;}", fill_height=True) as demo:

    def clear_thread():
        global thread
        thread = project_client.agents.create_thread()
        return []

    def on_example_clicked(evt: gr.SelectData):
        return evt.value["text"]  # Fill the textbox with that example text

    gr.HTML("<h1 style='text-align: center;'>Azure AI Agent Service</h1>")

    chatbot = gr.Chatbot(
        type="messages",
        examples=[
            {"text": "What's my company's remote work policy?"},
            {"text": "Check if it will rain tomorrow?"},
            {"text": "How is Contoso's stock doing today?"},
            {"text": "Send my direct report a summary of the HR policy."},
        ],
        show_label=False,
        scale=1,
    )

    textbox = gr.Textbox(
        show_label=False,
        lines=1,
        submit_btn=True,
    )

    # Populate textbox when an example is clicked
    chatbot.example_select(fn=on_example_clicked, inputs=None, outputs=textbox)

    # On submit: call azure_enterprise_chat, then clear the textbox
    (textbox
     .submit(
         fn=azure_enterprise_chat,
         inputs=[textbox, chatbot],
         outputs=[chatbot, textbox],
     )
     .then(
         fn=lambda: "",
         outputs=textbox,
     )
    )

    # A "Clear" button that resets the thread and the Chatbot
    chatbot.clear(fn=clear_thread, outputs=chatbot)

# ✅ Correctly mount Gradio inside FastAPI
app = gr.mount_gradio_app(app, demo, path="/")

# ✅ Signal handler for graceful shutdown (without sys.exit)
def signal_handler(sig, frame):
    print("Shutting down gracefully...")
    raise SystemExit(0)

signal.signal(signal.SIGINT, signal_handler)
