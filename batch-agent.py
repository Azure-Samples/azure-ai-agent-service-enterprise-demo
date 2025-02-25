import os
import re
import time
import json
from datetime import datetime  # Add this import
from typing import Any, List, Dict
from dotenv import load_dotenv
import random  # For jitter in exponential backoff

# Azure AI Projects
from azure.identity import DefaultAzureCredential
from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    FilePurpose,
    BingGroundingTool,
    FileSearchTool,
    FunctionTool,
    ToolSet,
    RunStatus,
    ConnectionType
)

# Your custom Python functions
from enterprise_functions import (
    enterprise_fns,
    fetch_weather,
    fetch_datetime,
    fetch_stock_price,
    send_email
)

# converter
from ai_agent_converter import AIAgentConverter
print("AIAgentConverter loaded", AIAgentConverter)

load_dotenv(override=True)


# Initialize Azure client
credential = DefaultAzureCredential()
project_client = AIProjectClient.from_connection_string(
    credential=credential,
    conn_str=os.environ["PROJECT_CONNECTION_STRING"]
)

# Function titles for tool bubbles
function_titles = {
    "fetch_weather": "☁️ fetching weather",
    "fetch_datetime": "🕒 fetching datetime",
    "fetch_stock_price": "📈 fetching financial info",
    "send_email": "✉️ sending mail",
    "file_search": "📄 searching docs",
    "bing_grounding": "🔍 searching bing",
}

def extract_bing_query(request_url: str) -> str:
    """Extract the query string from a Bing search URL."""
    match = re.search(r'q="([^"]+)"', request_url)
    if match:
        return match.group(1)
    return request_url

def setup_tools():
    """Set up and configure all necessary tools."""
    # Set up Bing tool
    try:

        bing_connection = project_client.connections.get(
            connection_name=os.environ["BING_CONNECTION_NAME"]
        )
        # print(bing_connection)
        bing_tool = BingGroundingTool(connection_id=bing_connection.id)
        print("bing > connected")
    except Exception:
        bing_tool = None
        print("bing failed > no connection found or permission issue")

    # Set up file search tool
    FOLDER_NAME = "enterprise-data"
    VECTOR_STORE_NAME = "hr-policy-vector-store"
    
    vector_store_id = None
    file_search_tool = None
    
    all_vector_stores = project_client.agents.list_vector_stores().data
    existing_vector_store = next(
        (store for store in all_vector_stores if store.name == VECTOR_STORE_NAME),
        None
    )

    if existing_vector_store:
        vector_store_id = existing_vector_store.id
        print(f"reusing vector store > {existing_vector_store.name}")
    elif os.path.isdir(FOLDER_NAME):
        # Upload and process files
        file_ids = []
        for file_name in os.listdir(FOLDER_NAME):
            file_path = os.path.join(FOLDER_NAME, file_name)
            if os.path.isfile(file_path):
                uploaded_file = project_client.agents.upload_file_and_poll(
                    file_path=file_path,
                    purpose=FilePurpose.AGENTS
                )
                file_ids.append(uploaded_file.id)
        
        if file_ids:
            vector_store = project_client.agents.create_vector_store_and_poll(
                file_ids=file_ids,
                name=VECTOR_STORE_NAME
            )
            vector_store_id = vector_store.id

    if vector_store_id:
        file_search_tool = FileSearchTool(vector_store_ids=[vector_store_id])

    # Create function tool using the enterprise_fns set
    function_tool = FunctionTool(list(enterprise_fns))  # Convert set to list for FunctionTool

    # Create toolset
    toolset = ToolSet()
    if bing_tool:
        toolset.add(bing_tool)
    if file_search_tool:
        toolset.add(file_search_tool)
    toolset.add(function_tool)

    return toolset

    
def process_batch_messages(user_messages: List[str]) -> List[Dict]:
    """
    Process a list of user messages in batch mode, returning all conversations.
    Each conversation includes the full dialogue with tool calls and responses.
    """
    print("\n=== Starting Batch Processing ===")
    print(f"Processing {len(user_messages)} messages")
    
    try:
        # Set up tools and agent
        print("\nSetting up tools...")
        toolset = setup_tools()
        print("Tools setup complete")
        
        # Create or get agent
        print("\nInitializing agent...")
        print(os.environ.get('MODEL_DEPLOYMENT_NAME'))
        AGENT_NAME = f"my-enterprise-agent-v1"
        found_agent = None
        print("Listing existing agents...")
        agents_list = project_client.agents.list_agents().data
        print(f"Found {len(agents_list)} existing agents")
        
        for agent in agents_list:
            if agent.name == AGENT_NAME:
                found_agent = agent
                print(f"Found existing agent: {agent.name} (id: {agent.id})")
                break

        model_name = os.environ.get("MODEL_DEPLOYMENT_NAME", "gpt-4o")
        print(f"Using model: {model_name}")
        
        instructions = (
            "You are a helpful enterprise assistant at Contoso. "
            f"Today's date is {datetime.now().strftime('%A, %b %d, %Y, %I:%M %p')}. "
            "You have access to hr documents in file_search, the grounding engine from bing "
            "and custom python functions such as  fetch_datetime, fetch_weather, fetch_stock_price, send_email"
            " For weather queries, use user-provided location; otherwise, always set to location to 'Seattle'."
            "Provide well-structured, concise, and professional answers."
        )

        if found_agent:
            print("Updating existing agent...")
            try:
                agent = project_client.agents.update_agent(
                    assistant_id=found_agent.id,
                    model=found_agent.model,
                    instructions=found_agent.instructions,
                    toolset=toolset,
                )
                print("Agent updated successfully")
            except Exception as e:
                print(f"Error updating agent: {str(e)}")
                raise
        else:
            print("Creating new agent...")
            try:
                agent = project_client.agents.create_agent(
                    model=model_name,
                    name=AGENT_NAME,
                    instructions=instructions,
                    toolset=toolset
                )
                print(f"New agent created with id: {agent.id}")
            except Exception as e:
                print(f"Error creating agent: {str(e)}")
                raise

        all_conversations = []
        all_evaluation_data = []
        for idx, user_message in enumerate(user_messages, 1):
            print(f"\n=== Processing Message {idx}/{len(user_messages)} ===")
            print(f"Message: {user_message}")
            
            conversation = []
            # Add user message
            conversation.append({
                'role': 'user',
                'content': user_message
            })
            
            try:
                # Create new thread
                print("\nCreating new thread...")
                thread = project_client.agents.create_thread()
                print(f"Thread created with id: {thread.id}")
                
                # Post user message
                print("Creating message in thread...")
                project_client.agents.create_message(
                    thread_id=thread.id,
                    role="user",
                    content=user_message
                )
                print("Message created successfully")
                
                # Create run
                print("Creating run...")
                run = project_client.agents.create_run(
                    thread_id=thread.id,
                    assistant_id=agent.id
                )
                print(f"Run created with id: {run.id}")
                
                # Track tool calls that have been processed
                processed_tool_calls = set()
                
                # Process run and handle tool calls
                print("\nMonitoring run status...")
                start_time = time.time()
                retry_count = 0
                max_retries = 10  # Add maximum retry limit
                
                while True:
                    try:
                        run_status = project_client.agents.get_run(
                            thread_id=thread.id,
                            run_id=run.id
                        )
                        print(f"Current run status: {run_status.status}")
                        
                        # Add more detailed status logging
                        if run_status.status == RunStatus.QUEUED:
                            print("Run is queued, waiting...")
                            time.sleep(1)  # Short sleep for queued state
                        elif run_status.status == RunStatus.IN_PROGRESS:
                            print("Run is in progress...")
                            time.sleep(1)  # Short sleep for in-progress state
                        elif run_status.status == RunStatus.REQUIRES_ACTION:
                            print("Run requires action...")
                            # Don't increment retry count or sleep when action is required
                            if not run_status.required_action:
                                print("No action found, continuing...")
                                time.sleep(1)
                                continue
                        elif run_status.status == RunStatus.COMPLETED:
                            print("Run completed successfully")
                            break
                        elif run_status.status == RunStatus.FAILED:
                            print(f"Run failed: {run_status.last_error}")
                            break
                        else:
                            print(f"Unknown status: {run_status.status}")
                            time.sleep(1)
                            continue
                        
                        # Handle tool calls
                        if run_status.required_action and run_status.required_action.submit_tool_outputs:
                            tool_calls = run_status.required_action.submit_tool_outputs.tool_calls
                            print(f"\nFound {len(tool_calls)} tool calls to process")
                            tool_outputs = []
                            
                            for tool_call in tool_calls:
                                # Skip if we've already processed this tool call
                                if tool_call.id in processed_tool_calls:
                                    print(f"Skipping already processed tool call: {tool_call.id}")
                                    continue
                                processed_tool_calls.add(tool_call.id)
                                
                                print(f"\nProcessing tool call: {tool_call.type} (id: {tool_call.id})")
                                if tool_call.type == "function":
                                    # Add tool call to conversation
                                    fn_name = tool_call.function.name
                                    fn_args = tool_call.function.arguments
                                    print(f"Function name: {fn_name}")
                                    print(f"Arguments: {fn_args}")
                                    
                                    # Pre-process weather location
                                    if fn_name == "fetch_weather":
                                        try:
                                            args_dict = json.loads(fn_args)
                                            if not args_dict.get("location") or args_dict.get("location").lower() in [
                                                "your location", "my location", "here", "current location", 
                                                "this location", "", "there"
                                            ]:
                                                print("Using default location: Seattle")
                                                args_dict["location"] = "Seattle"
                                                fn_args = json.dumps(args_dict)
                                        except json.JSONDecodeError:
                                            print("Error parsing weather arguments, using default location")
                                            args_dict = {"location": "Seattle", "timeframe": "current"}
                                            fn_args = json.dumps(args_dict)
                                    
                                    conversation.append({
                                        'role': 'assistant',
                                        'content': fn_args,
                                        'metadata': {
                                            'title': function_titles.get(fn_name, f"🛠 {fn_name}"),
                                            'status': 'pending',
                                            'id': f"tool-{tool_call.id}"
                                        }
                                    })
                                    
                                    # Execute function
                                    print("Executing function...")
                                    try:
                                        fn_args_dict = json.loads(fn_args)
                                        # Get the function from the enterprise_fns set
                                        fn = next((f for f in enterprise_fns if f.__name__ == fn_name), None)
                                        
                                        if fn is not None:
                                            # Add additional error handling for email
                                            if fn_name == 'send_email':
                                                if not all(k in fn_args_dict for k in ['recipient', 'subject', 'body']):
                                                    raise ValueError("Missing required email parameters")
                                                
                                            result = fn(**fn_args_dict)
                                            output = str(result)
                                            tool_outputs.append({
                                                "tool_call_id": tool_call.id,
                                                "output": output
                                            })
                                            print(f"Function executed successfully: {output}")
                                        else:
                                            error_msg = f"Function {fn_name} not found in available functions"
                                            tool_outputs.append({
                                                "tool_call_id": tool_call.id,
                                                "output": error_msg
                                            })
                                            print(f"Function execution failed: {error_msg}")
                                    except json.JSONDecodeError as e:
                                        error_msg = f"Invalid JSON in function arguments: {str(e)}"
                                        tool_outputs.append({
                                            "tool_call_id": tool_call.id,
                                            "output": error_msg
                                        })
                                        print(f"Function execution failed: {error_msg}")
                                    except Exception as e:
                                        error_msg = f"Error executing function: {str(e)}"
                                        tool_outputs.append({
                                            "tool_call_id": tool_call.id,
                                            "output": error_msg
                                        })
                                        print(f"Function execution failed: {error_msg}")
                                
                                elif tool_call.type in ["bing_grounding", "file_search"]:
                                    print(f"Processing {tool_call.type} tool call")
                                    title = function_titles.get(tool_call.type, f"🛠 {tool_call.type}")
                                    content = "Search completed"
                                    if tool_call.type == "bing_grounding" and hasattr(tool_call, 'bing_grounding'):
                                        content = extract_bing_query(tool_call.bing_grounding.requesturl)
                                        print(f"Extracted Bing query: {content}")
                                    
                                    conversation.append({
                                        'role': 'assistant',
                                        'content': content,
                                        'metadata': {
                                            'title': title,
                                            'status': 'pending',
                                            'id': f"tool-{tool_call.id}"
                                        }
                                    })
                            
                            # Submit tool outputs
                            if tool_outputs:
                                print(f"\nSubmitting {len(tool_outputs)} tool outputs...")
                                try:
                                    project_client.agents.submit_tool_outputs_to_run(
                                        thread_id=thread.id,
                                        run_id=run.id,
                                        tool_outputs=tool_outputs
                                    )
                                    print("Tool outputs submitted successfully")
                                    
                                    # Add a small delay after submitting outputs to allow for processing
                                    time.sleep(2)
                                except Exception as e:
                                    print(f"Error submitting tool outputs: {str(e)}")
                                    # Don't raise here, just log and continue
                                    conversation.append({
                                        'role': 'system',
                                        'content': f"Tool output submission error: {str(e)}"
                                    })
                                    # Break the loop to avoid infinite retries on submission error
                                    break
                        
                        # Check timeouts and retries
                        if time.time() - start_time > 300:  # 5 minute timeout
                            print("Run timed out after 5 minutes")
                            break
                        
                        # Only sleep and increment retry count if we're not in REQUIRES_ACTION state
                        if run_status.status != RunStatus.REQUIRES_ACTION:
                            # Add exponential backoff with jitter
                            wait_time = min(32, (2 ** retry_count) + random.uniform(0, 1))
                            time.sleep(wait_time)
                            retry_count += 1
                        
                    except Exception as e:
                        print(f"Error checking run status: {str(e)}")
                        retry_count += 1
                        if retry_count >= max_retries:
                            raise
                        time.sleep(min(32, 2 ** retry_count))
                
                # Get final messages
                print("\nRetrieving final messages...")
                messages = project_client.agents.list_messages(thread_id=thread.id)


                data_for_evaluation = AIAgentConverter(project_client=project_client).convert(thread.id)
                all_evaluation_data.append(data_for_evaluation)

                # Add assistant responses
                print("Processing assistant responses...")
                for msg in messages.data:
                    if msg.role == "assistant" and msg.content:
                        conversation.append({
                            'role': 'assistant',
                            'content': msg.content[0].text.value
                        })
                
                all_conversations.append(conversation)
                print(f"\nMessage {idx} processing complete")
                
            except Exception as e:
                print(f"\nError processing message {idx}: {str(e)}")
                # Add error message to conversation
                conversation.append({
                    'role': 'system',
                    'content': f"Error processing message: {str(e)}"
                })
                all_conversations.append(conversation)
                continue
        
        print("\n=== Batch Processing Complete ===")
        return all_conversations, all_evaluation_data
        
    except Exception as e:
        print(f"\nFatal error in batch processing: {str(e)}")
        raise

# Example usage:
if __name__ == "__main__":
    questions = [
        "What's my company's remote work policy?",
        "Check if it will rain tomorrow?",
        "How is Microsoft's stock doing today?",
        "Send my direct report a summary of the HR policy."
    ]
    # use 50 test queries
    from test_data.test_queries import questions

    try:
        print("\nStarting batch message processing...")
        results, all_evaluation_data = process_batch_messages(questions)

        # Create test_data directory if it doesn't exist
        os.makedirs("./test_data", exist_ok=True)

        # Save results to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        results_file = f"./test_data/batch_results_{timestamp}.json"
        eval_file = f"./test_data/batch_evaluation_{timestamp}.json"
        with open(results_file, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nResults saved to: {results_file}")

        with open(eval_file, "w") as f:
            json.dump(all_evaluation_data, f, indent=2)
        print(f"\nEvaluation data saved to: {eval_file}")

        # Print results
        print("\n=== Results ===")
        for idx, conversation in enumerate(results, 1):
            print(f"\nConversation {idx}:")
            print("=" * 80)
            for message in conversation:
                if message['role'] == 'user':
                    print(f"\nUser: {message['content']}")
                elif message['role'] == 'assistant':
                    if 'metadata' in message:
                        print(f"Tool ({message['metadata']['title']}): {message['content']}")
                        print(f"Status: {message['metadata']['status']}")
                    else:
                        print(f"Assistant: {message['content']}")
                elif message['role'] == 'system':
                    print(f"System: {message['content']}")
            print("\n" + "=" * 80)

    except Exception as e:
        print(f"\nError in main execution: {str(e)}")
        error_file = "./test_data/batch_errors.log"
        with open(error_file, "a") as f:
            f.write(f"\n{datetime.now()}: {str(e)}")
        print(f"Error logged to: {error_file}")
        raise