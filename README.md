# Azure AI Agent Service-enterprise-demo

This sample demonstrates how to build a streaming enterprise agent using **Azure AI Agent Service**. The agent can answer questions in real time using local HR and company policy documents, integrate external context via Bing, using gpt-4o-2024-05-13.

[![YouTube](https://github.com/Azure-Samples/azure-ai-agent-service-enterprise-demo/blob/main/assets/agent-service-youtube.png?raw=true)](https://www.youtube.com/watch?v=ph-1-OIqsxY)

## Features

This demo teaches developers how to:

- **Create or Reuse Agents Programmatically**  
  Demonstrates how to connect to an Azure AI Foundry hub, either create a new agent with customized instructions (using GPT-4o or any supported model), or reuse an existing agent.

- **Incorporate Vector Stores for Enterprise Data**  
  Automatically create or reuse a vector store containing local policy files (e.g. HR, PTO, etc.) for retrieval-augmented generation (RAG).  
  **Optional:** If the default file search tool isn’t available, the notebook automatically attempts direct Azure AI Search integration via environment variables.

- **Integrate Server-Side Tools**  
  Illustrates adding tools—like Bing search, file search, and custom Python functions—into a single `ToolSet`, and how to intercept and log each tool call.

- **Extend Functionality with Azure Logic Apps**  
  Deploy a Logic App to enable the `send_email` functionality. This Logic App can be imported using the provided ARM template, and its HTTP endpoint can be integrated into the agent’s toolset.

- **Stream Real-Time Agent Responses**  
  Demonstrates a streaming approach for partial message updates from the agent, seamlessly handling partial tool invocation and chunked text output.

- **Build an Interactive Gradio UI**  
  Provides a Gradio-based chat interface that prompts the agent with user questions, displays partial tool calls and final results, and makes it easy to extend or adapt the UI.

![gif demo](https://github.com/Azure-Samples/azure-ai-agent-service-enterprise-demo/blob/main/assets/demo-short-3-2.gif?raw=true)

Use this demo as a reference for creating, deploying, and managing enterprise-scale AI agents with strong integration, data security, and real-time conversation capabilities.

## Getting Started

### Prerequisites

- **Python 3.9+**  
- **Visual Studio Code** with the Python and Jupyter extensions  
- An **Azure AI Foundry** resource set up (see [Azure AI Agent Service docs](https://learn.microsoft.com/azure/ai-services/agents/))

### Installation & Setup

1. **Clone** this repository:

   ```bash
   git clone https://github.com/Azure-Samples/azure-ai-agent-service-enterprise-demo.git
   ```

2. **Create a virtual environment** (using venv as an example):

    ```bash
    python -m venv .venv
    ```

3. **Activate** your virtual environment:

    - Windows: `.venv\Scripts\activate`
    - macOS/Linux: `source .venv/bin/activate`

4. **Install** the required dependencies:

    ```bash
    pip install -r requirements.txt
    ```

5. **Create a `.env` file** at the root of this folder to store secret keys and settings (e.g., the connection string and optional model name). You can copy the provided `.env.example` file:

    - Windows (PowerShell):
      ```powershell
      Copy-Item -Path .env.example -Destination .env
      ```
    
    - macOS/Linux:
      ```bash
      cp .env.example .env
      ```

    Then, open the `.env` file and update it with your configuration details.

    - Add your [Azure AI Foundry](https://learn.microsoft.com/azure/ai-services/agents/quickstart?pivots=programming-language-python-azure#configure-and-run-an-agent) connection string:
        ```plaintext
        PROJECT_CONNECTION_STRING="<HostName>;<AzureSubscriptionId>;<ResourceGroup>;<ProjectName>"
        ```

    - Specify the [compatible model](https://learn.microsoft.com/azure/ai-services/agents/how-to/tools/bing-grounding?tabs=python&pivots=overview#setup) you want to use (e.g. GPT-4o):
        ```plaintext
        MODEL_NAME="YOUR_MODEL_NAME"
        ```

    - (Optional) **Grounding with Bing**
        
        You can add real-time web data to your agent via Grounding with Bing Search. For details on how to create a Bing search resource, link it with your Azure AI Agent, and meet display requirements, see Grounding with Bing Search.

        ```plaintext
        BING_CONNECTION_NAME="YOUR_CONNECTION_NAME"
        ```

        > In this sample, the code automatically tries to discover an .env variable named `BING_CONNECTION_NAME`. If available, you’ll see a console message like `bing > connected`. Otherwise, it gracefully proceeds without Bing.

    - (Optional) **OpenWeather** API keys to enable `fetch_weather` tool:
        ```plaintext
        OPENWEATHER_GEO_API_KEY="YOUR_OPENWEATHER_GEOCODING_API_KEY"
        OPENWEATHER_ONE_API_KEY="YOUR_OPENWEATHER_ONE_CALL_API_KEY"
        ```
        If you leave these blank, the weather function will simply return an error or remain disabled.

        > **Tip**: If you don’t plan to use Bing grounding or OpenWeather, you can skip setting up those resources. The demo will still work with your local documents and core agent features.

    > Make sure that .env is listed in your .gitignore. Never commit your credentials to source control!

6. **Open** the project folder in Visual Studio Code:

    - Select your Python interpreter:
      1. Press Ctrl+Shift+P (or Cmd+Shift+P on Mac)
      2. Choose **Python: Select Interpreter** and select the `venv` environment.

### Quickstart

1. **Run Jupyter Notebook:**
    - Open the `enterprise-streaming-agent.ipynb`, in VS Code.
    - Step through the cells to:
      1. Connect to Azure AI Foundry and create or reuse an agent.
      2. Optionally upload local HR/policy files to a vector store.
      3. Add Bing integration, local file search, and custom Python functions (weather, stock lookup, etc.) to the agent’s ToolSet.
      4. If no `FileSearchTool` is detected, the code uses `AZURE_SEARCH_CONNECTION_NAME` and `AZURE_SEARCH_INDEX_NAME` from your `.env` file to add the search tool.
      5. Launch a Gradio UI that streams real-time queries and partial responses.

2. **Try the Demo Chat:**
    - When you run the notebook, a local Gradio instance should launch in your cell output. You can click the localhost link to open the chat UI.
    - Ask the agent questions like:
        - “What’s my company’s remote work policy?”
        - “Fetch the weather forecast for Seattle tomorrow.” _(Requires valid OpenWeather keys)_
        - “How is MSFT stock price trending today?”
        - “Send an email summary of the HR policy.” _(Triggers the Logic App if configured)_

## Deploying the Send Email Logic App
The sample includes a Logic App ARM template (`send_email_logic_app.json`) that you can deploy to enable the send_email functionality.
### Steps to Deploy:
1. The template defines a simple logic app that triggers on an HTTP request. It expects a JSON payload with `recipient`, `subject`, and `body` fields.
2. Deploy the template using the Azure CLI or the Azure Portal.
    - **Azure CLI:**
        ```bash
        az deployment group create \
          --resource-group <your-resource-group> \
          --template-file send_email_logic_app.template.json \
          --parameters logicAppName=send_email_logic_app
        ```
    - **Azure Portal:**
        - Go to the Azure Portal and create a new Logic App.
        - Choose the `Blank Logic App` template.
        - In the designer, add an HTTP trigger and an Office 365 `Send an email` action.
        - Save the Logic App and copy the HTTP endpoint URL.
3. Once deployed, copy the HTTP trigger URL from the Logic App’s trigger.
4. Uncomment and set the `LOGIC_APP_SEND_EMAIL_URL` variable with you Logic App URL:
    ```dotenv
    LOGIC_APP_SEND_EMAIL_URL="https://<your-logic-app-endpoint>"
    ```

## Azure AI Search Integration

This demo supports two approaches for enterprise document retrieval:

### Default Vector Store
By default, the `FileSearchTool` automatically creates a vector store using Azure AI Search in standard agent setup, providing:
- Automatic document chunking and embedding
- Vector + keyword hybrid search
- Zero additional configuration needed

### Direct Azure AI Search Integration
For scenarios requiring direct control over an existing search index, update these environment variables to your `.env`:

```dotenv
#AZURE_SEARCH_CONNECTION_NAME="YOUR_AZURE_SEARCH_CONNECTION_NAME"
#AZURE_SEARCH_INDEX_NAME="YOUR_AZURE_SEARCH_INDEX_NAME"
```

## Resources
- [Azure AI Agent Service Documentation](https://learn.microsoft.com/azure/ai-services/agents/overview)
- [Grounding with Bing Search](https://learn.microsoft.com/azure/ai-services/agents/how-to/tools/bing-grounding)
- [Azure AI Search with Agents](https://learn.microsoft.com/azure/ai-services/agents/how-to/tools/azure-ai-search)
- [Azure Logic Apps Documentation](https://learn.microsoft.com/en-us/azure/logic-apps/)
- [OpenWeather API](https://openweathermap.org/api)

## Known Issues
Please review our [Known Issues](KNOWN_ISSUES.md) for current bugs and workarounds before reporting new problems.

## Acknowledgments

- **[Gradio](https://github.com/gradio-app/gradio)**  
  This project uses Gradio under the [Apache License 2.0](https://github.com/gradio-app/gradio/blob/main/LICENSE). No modifications to Gradio’s source code are distributed in this repository.
