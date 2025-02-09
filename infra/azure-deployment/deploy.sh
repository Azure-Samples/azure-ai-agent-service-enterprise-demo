#!/bin/bash
set -e  # Exit on any error

# Load environment variables from .env file
set -o allexport
source .env
set +o allexport

# Reload environment variables to ensure the latest changes are taken
export $(grep -v '^#' .env | xargs)

# Set variables from .env file
RESOURCE_GROUP=$RESOURCE_GROUP
APP_SERVICE_PLAN=$APP_SERVICE_PLAN
WEB_APP_NAME=$WEB_APP_NAME
LOCATION=$LOCATION

# Get the Subscription ID dynamically
SUBSCRIPTION_ID=$(az account show --query "id" --output tsv)
echo "Using Subscription ID: $SUBSCRIPTION_ID"

# -------------------------------
# Create or re-use the App Service Plan
# -------------------------------
app_service_plan_exists=$(az appservice plan show --name "$APP_SERVICE_PLAN" --resource-group "$RESOURCE_GROUP" --query "name" --output tsv)
if [ -z "$app_service_plan_exists" ]; then
  echo "Creating App Service plan: $APP_SERVICE_PLAN..."
  az appservice plan create --name "$APP_SERVICE_PLAN" --resource-group "$RESOURCE_GROUP" --sku B1 --is-linux --location "$LOCATION"
else
  echo "App Service plan $APP_SERVICE_PLAN already exists."
fi

# -------------------------------
# Create or re-use the Web App
# -------------------------------
echo "Checking if the web app $WEB_APP_NAME exists..."
if ! az webapp show --name "$WEB_APP_NAME" --resource-group "$RESOURCE_GROUP" &>/dev/null; then
  echo "Web app not found. Creating..."
  az webapp create --resource-group "$RESOURCE_GROUP" --plan "$APP_SERVICE_PLAN" --name "$WEB_APP_NAME" --runtime "PYTHON:3.10"
else
  echo "Web app $WEB_APP_NAME already exists."
fi

# -------------------------------
# Enable Managed Identity and assign roles
# -------------------------------
echo "Enabling Managed Identity for $WEB_APP_NAME..."
az webapp identity assign --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME"

# Wait for the identity to be fully registered in Azure AD
echo "Waiting for Managed Identity to be fully available..."
sleep 20  # Adjust this delay if needed

# Retrieve the Managed Identity's Object ID
IDENTITY_PRINCIPAL_ID=$(az webapp show --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --query "identity.principalId" --output tsv)
echo "Managed Identity Principal ID: $IDENTITY_PRINCIPAL_ID"

# Assign the Contributor role to the Managed Identity
echo "Assigning 'Contributor' role to the Managed Identity..."
az role assignment create --assignee "$IDENTITY_PRINCIPAL_ID" --role "Contributor" --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

# Assign the Azure AI Developer role to the Managed Identity
echo "Assigning 'Azure AI Developer' role to the Managed Identity..."
az role assignment create --assignee "$IDENTITY_PRINCIPAL_ID" --role "Azure AI Developer" --scope "/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP"

# -------------------------------
# Configure Web App settings
# -------------------------------
# Set a flag so your application code knows to use Managed Identity
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings \
    AZURE_IDENTITY_USE_MANAGED_IDENTITY=True

# Set the port (your app listens on 8000)
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings WEBSITES_PORT=8000

# Set timeouts for slow startups
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings \
    SCM_COMMAND_IDLE_TIMEOUT=1800 \
    WEBSITES_CONTAINER_START_TIME_LIMIT=1800

# -------------------------------
# Write the startup script (start.sh)
# -------------------------------
STARTUP_SCRIPT="/home/site/wwwroot/start.sh"
echo "Writing startup script to $STARTUP_SCRIPT..."
cat <<'EOF' > start.sh
#!/bin/bash
# Print Python version and pip path for debugging
python --version
which pip

echo "Installing packages..."
pip install --no-cache-dir -r /home/site/wwwroot/requirements.txt || { echo "Pip install failed"; exit 1; }

echo "Starting Gunicorn..."
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --log-level debug
EOF

# Ensure the startup script has execution permissions
chmod +x start.sh

# Upload the startup script to Azure (by setting the startup command)
az webapp config set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --startup-file "$STARTUP_SCRIPT"

# -------------------------------
# Prepare and deploy the application code
# -------------------------------
# Change directory to the application folder (update this path if needed)
cd /home/dhangerkapil/azure-ai-agent-service-enterprise-demo/azure || { echo "Directory not found"; exit 1; }

# Remove any old ZIP file
rm -f app.zip

# Create a ZIP file of the application code (this includes start.sh)
echo "Creating ZIP file for deployment..."
zip -r app.zip main.py enterprise_functions.py requirements.txt start.sh .env

# Verify that the ZIP file was created
if [ ! -f app.zip ]; then
    echo "Error: app.zip not found. Exiting."
    exit 1
fi

# Deploy the ZIP file to the Web App
echo "Deploying application to Azure App Service..."
az webapp deployment source config-zip --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --src app.zip

# -------------------------------
# Set additional environment variables
# -------------------------------
echo "Configuring additional environment variables..."
env_vars=$(grep -v '^#' .env | xargs)
az webapp config appsettings set --resource-group "$RESOURCE_GROUP" --name "$WEB_APP_NAME" --settings $env_vars

echo "Deployment complete. You can access your app at: https://$WEB_APP_NAME.azurewebsites.net"