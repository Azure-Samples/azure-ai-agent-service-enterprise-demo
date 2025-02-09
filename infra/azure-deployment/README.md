# Azure AI Agent Service Enterprise Demo - Web App Deployment

This guide provides step-by-step instructions to deploy a simple Gradio app on Azure Web App. This deployment is intended for demonstration purposes and is not recommended for production use.

## Step 1: Run the Enterprise Streaming Agent Notebook

Before deploying the web app, run the [enterprise-streaming-agent.ipynb](../../enterprise-streaming-agent.ipynb) notebook to create the agent and vector store. Use the generated values in the `.env` file for deployment.

## Step 2: Prepare Environment Variables

Copy the `.env.example` file to `.env` and fill in the required values. Most of these values will be the same as those used in the notebook, except for the Azure Web App deployment settings like location and app service plan.

```bash
cp .env.example .env
```

Edit the `.env` file and replace the placeholder values with your actual values:

```env
PROJECT_CONNECTION_STRING="<HostName>;<AzureSubscriptionId>;<ResourceGroup>;<ProjectName>"
RESOURCE_GROUP="YOUR_RESOURCE_GROUP_NAME"
APP_SERVICE_PLAN="YOUR_APP_SERVICE_PLAN_NAME"
WEB_APP_NAME="YOUR_WEB_APP_NAME"
LOCATION="YOUR_APPSERVICEPLAN_LOCATION"
AGENT_NAME="YOUR_AGENT_NAME"
BING_CONNECTION_NAME="YOUR_CONNECTION_NAME"
VECTOR_STORE_NAME="YOUR_VECTOR_STORE_NAME"
OPENWEATHER_ONE_API_KEY="YOUR_OPENWEATHER_ONE_CALL_API_KEY"
OPENWEATHER_GEO_API_KEY="YOUR_OPENWEATHER_GEOCODING_API_KEY"
```

## Step 3: Deploy the Web App

### 3.1: Run the Deployment Script

Navigate to the `azure-deployment` folder and run the `deploy.sh` script. This script will create the necessary Azure resources and deploy the application.

### 3.2: Verify Deployment

After the deployment script completes, verify the deployment by accessing your web app at:

```
https://<YOUR_WEB_APP_NAME>.azurewebsites.net
```

## Files Overview

### `deploy.sh`

This script handles the creation of Azure resources and deployment of the application.

### `start.sh`

This script is used to start the application on the Azure Web App.

### `requirements.txt`

This file lists the Python dependencies required for the application.

### `main.py`

This is the main application file that initializes the FastAPI app and integrates with Gradio.

### `enterprise_functions.py`

This file contains custom Python functions used by the application.

### `.env.example`

This file provides a template for the environment variables required for the deployment.

## Notes

- This deployment is intended for demonstration purposes and is not recommended for production use.
- Ensure that all environment variables are correctly set before running the deployment script.

## Conclusion

By following these steps, you should be able to deploy the Azure AI Agent Service Enterprise Demo on Azure Web App. If you encounter any issues, refer to the Azure documentation or seek help from the Azure community.
