import json

from azure.ai.projects.models import (RunStepType, MessageRole, ThreadMessage, MessageTextContent,
                                      MessageTextDetails, RunStepFunctionToolCall, RunStepFunctionToolCallDetails, OpenAIPageableListOfRunStep,
                                      RunStep, RunStepMessageCreationDetails, RunStepMessageCreationReference, RunStepCompletionUsage, RunStepToolCallDetails,
                                      OpenAIPageableListOfThreadMessage)

class ThreadMessageEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, (RunStepFunctionToolCallDetails, OpenAIPageableListOfRunStep, RunStep,
                            RunStepMessageCreationDetails, RunStepMessageCreationReference, RunStepCompletionUsage,
                            RunStepToolCallDetails, OpenAIPageableListOfThreadMessage)):
            return obj.__dict__["_data"]
        if isinstance(obj, RunStepFunctionToolCall):
            return obj.__dict__["_data"]
        if isinstance(obj, MessageTextDetails):
            return obj.__dict__["_data"]
        if isinstance(obj, MessageTextContent):
            return obj.__dict__["_data"]
        if isinstance(obj, ThreadMessage):
            json_data = obj.__dict__["_data"]
            if obj.__dict__.get("tool_calls"):
                json_data["tool_calls"] = obj.__dict__["tool_calls"]
            return json_data  # or implement a method to convert to a dictionary
        return super().default(obj)

# project_client.telemetry.enable(destination=sys.stdout)

class AIAgentConverter:
    def __init__(self, project_client):
        self.project_client = project_client

    def convert(self, thread_id, filter_run_id=None):
        """
        Fetches all messages in a thread and converts them to JSON.
        if filter_run_id is provided, only messages from that run are included. Assuming all messages before the last assistant messages for that run are part of that run.
        """
        messages = self.project_client.agents.list_messages(thread_id=thread_id)
        with open("messages.json", 'w') as file:
            json.dump(messages, file, indent=4, cls=ThreadMessageEncoder)

        messages = messages.data

        assistant_message_index_for_run = None
        for i in range(0, len(messages)):
            message = messages[i]
            print(f"Message: {message.content}")
            message_id = message.id
            message_type = message.role
            run_id = message.run_id
            if message_type == MessageRole.AGENT:
                if filter_run_id is not None and run_id == filter_run_id:
                    assistant_message_index_for_run = i
                tool_calls = []
                if filter_run_id is None or run_id == filter_run_id:
                    run_details = self.project_client.agents.list_run_steps(thread_id=thread_id, run_id=run_id)
                    with open("run_details.json", 'w') as file:
                        json.dump(run_details, file, indent=4, cls=ThreadMessageEncoder)
                    for run_step in run_details.data:
                        print(f"Run step: {run_step.type}")
                        if run_step.type == RunStepType.MESSAGE_CREATION:
                            print(f"Assistant message: {run_step.step_details.message_creation.message_id}")
                        elif run_step.type == RunStepType.TOOL_CALLS:
                            tool_calls.extend(run_step.step_details.tool_calls)
                            print(f"Tool call: {run_step.step_details.tool_calls}")
                    message.tool_calls = tool_calls

        evaluation_data = messages[assistant_message_index_for_run:] if assistant_message_index_for_run is not None else messages,
        json_data = json.dumps(
            messages[assistant_message_index_for_run:] if assistant_message_index_for_run is not None else messages,
            cls=ThreadMessageEncoder)
        with open("proposed_evaluation_data.json", 'w') as file:
            json.dump(evaluation_data, file, indent=4, cls=ThreadMessageEncoder)
        return json.loads(json_data)
