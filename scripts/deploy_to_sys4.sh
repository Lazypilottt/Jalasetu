#!/usr/bin/env bash
set -euo pipefail

# Remote deploy script for sys4 — run this on sys4 (as the deploy user)
# It clones/pulls the repository, creates a Python venv, installs requirements,
# creates a systemd service at /etc/systemd/system/jalasetu.service and starts it.

# Configure these if needed
REPO_URL="https://github.com/Lazypilottt/Jalasetu.git"
BRANCH="main"
DEPLOY_DIR="${DEPLOY_DIR:-$HOME/jalasetu}"
PYTHON_BIN="python3"
SERVICE_NAME="jalasetu"
API_HOST="0.0.0.0"
API_PORT=8000
VENV_DIR="$DEPLOY_DIR/venv"

echo "Remote deploy script starting"
echo "Repo: $REPO_URL (branch: $BRANCH)"
echo "Deploy dir: $DEPLOY_DIR"

echo "Checking prerequisites..."
if ! command -v git >/dev/null 2>&1; then
  echo "ERROR: git is not installed. Install git (e.g. sudo apt-get install -y git) and re-run." >&2
  exit 2
fi

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: $PYTHON_BIN not found. Install Python 3.8+ and re-run." >&2
  exit 2
fi

# Clone or update repository
if [ -d "$DEPLOY_DIR/.git" ]; then
  echo "Repository already exists — fetching latest"
  cd "$DEPLOY_DIR"
  git fetch --all --prune
  git checkout "$BRANCH" || git checkout -b "$BRANCH"
  git reset --hard "origin/$BRANCH"
  git clean -fdx
else
  echo "Cloning repository into $DEPLOY_DIR"
  mkdir -p "$(dirname "$DEPLOY_DIR")"
  git clone --branch "$BRANCH" "$REPO_URL" "$DEPLOY_DIR"
fi

# Optional: pull submodules if any
if [ -f "$DEPLOY_DIR/.gitmodules" ]; then
  echo "Updating submodules"
  cd "$DEPLOY_DIR"
  git submodule update --init --recursive
fi

# Create or recreate virtualenv
if [ -d "$VENV_DIR" ]; then
  echo "Recreating virtualenv at $VENV_DIR"
  rm -rf "$VENV_DIR"
fi
$PYTHON_BIN -m venv "$VENV_DIR"
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"

pip install --upgrade pip setuptools wheel

REQ_FILE="$DEPLOY_DIR/requirements.txt"
if [ -f "$REQ_FILE" ]; then
  echo "Installing Python requirements"
  pip install -r "$REQ_FILE"
else
  echo "requirements.txt not found, installing minimal runtime packages"
  pip install fastapi uvicorn[standard]
fi

# Create systemd service file
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
TMP_SERVICE="/tmp/$SERVICE_NAME.service"
cat > "$TMP_SERVICE" <<SERVICE
[Unit]
Description=JalaSetu FastAPI service
After=network.target

[Service]
User=$(whoami)
WorkingDirectory=$DEPLOY_DIR
Environment=PATH=$VENV_DIR/bin
ExecStart=$VENV_DIR/bin/uvicorn app.main:app --host $API_HOST --port $API_PORT --workers 1
Restart=on-failure
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
SERVICE

echo "Created temporary service unit at $TMP_SERVICE"

echo "Moving service to $SERVICE_FILE (requires sudo)"
sudo mv "$TMP_SERVICE" "$SERVICE_FILE"

echo "Reloading systemd and enabling service"
sudo systemctl daemon-reload
sudo systemctl enable --now "$SERVICE_NAME"

echo "Service status (last lines):"
sudo systemctl status "$SERVICE_NAME" --no-pager | sed -n '1,200p' || true

echo "Deployment complete. API should be reachable at: http://$(hostname -I | awk '{print $1}'):$API_PORT/analyzeContour"

echo "If something failed, check journal logs: sudo journalctl -u $SERVICE_NAME -b --no-pager"
