#!/bin/bash
# Print Python version and pip path for debugging
python --version
which pip

echo "Installing packages..."
pip install --no-cache-dir -r /home/site/wwwroot/requirements.txt || { echo "Pip install failed"; exit 1; }

echo "Starting Gunicorn..."
gunicorn -w 4 -k uvicorn.workers.UvicornWorker main:app --bind 0.0.0.0:8000 --log-level debug
