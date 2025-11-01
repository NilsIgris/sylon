#!/bin/bash

# Sylon Agent and Command File Updater
# This script fetches the latest versions of sylon-agent.py or command.py
# from the specified GitHub branch and replaces the local files in /usr/local/bin/
# Elevated privileges (sudo) are required for file replacement

# --- Configuration ---
AGENT_URL="https://raw.githubusercontent.com/NilsIgris/sylon/refs/heads/nils/client/agent.py"
COMMAND_URL="https://raw.githubusercontent.com/NilsIgris/sylon/refs/heads/nils/client/command.py"

AGENT_PATH="/usr/local/bin/sylon-agent.py"
COMMAND_PATH="/usr/local/bin/command.py"

# --- Functions ---

# Function to handle the update process
perform_update() {
    local url=$1
    local target_path=$2
    local file_name=$(basename "$target_path")

    echo "Fetching latest version of $file_name..."

    # Use curl to download the file safely to a temporary location
    # -s: Silent mode
    # -S: Show error only
    # -f: Fail silently on server errors (4xx, 5xx)
    TEMP_FILE=$(mktemp)
    if ! curl -sSfL "$url" -o "$TEMP_FILE"; then
        echo "ERROR: Failed to download $file_name from $url."
        rm -f "$TEMP_FILE"
        return 1
    fi

    echo "Download successful. Replacing $target_path (requires sudo)..."

    # Use sudo to overwrite the existing file
    if sudo mv "$TEMP_FILE" "$target_path"; then
        echo "SUCCESS: $file_name has been updated."
        # Ensure the file is executable
        sudo chmod +x "$target_path"
    else
        echo "ERROR: Failed to replace $file_path. Check your permissions."
        rm -f "$TEMP_FILE"
        return 1
    fi
}

# --- Main Menu Loop ---

while true; do
    echo ""
    echo "--- Sylon File Updater ---"
    echo "1) Update Agent File ($AGENT_PATH)"
    echo "2) Update Commands File ($COMMAND_PATH)"
    echo "3) Exit"
    echo "--------------------------"
    read -rp "Enter your choice (1-3): " choice

    case $choice in
        1)
            systemctl stop sylon-agent.service
            perform_update "$AGENT_URL" "$AGENT_PATH"
            systemctl start sylon-agent.service
            ;;
        2)
            systemctl stop sylon-agent.service
            perform_update "$COMMAND_URL" "$COMMAND_PATH"
            systemctl start sylon-agent.service
            ;;
        3)
            echo "Exiting updater. Goodbye!"
            break
            ;;
        *)
            echo "Invalid option. Please enter 1, 2, or 3."
            ;;
    esac
done

exit 0
