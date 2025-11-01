#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Version 0.2

import time, os, sys, socket, uuid, random, json, logging
from datetime import datetime
import psutil
import requests
import yaml

import command

# --- CONFIGURATION AND SETUP ---

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("sylon-agent")
CONFIG_FILE_PATH = "/etc/sylon/config.yaml"

# Default config
DEFAULT_CONFIG = {
    "endpoint": "NULL",
    "api_key": "NULL",
    "interval_seconds": 300,
    # Only remote_code_url remains for self-update capability
    "remote_code_url": "https://raw.githubusercontent.com/NilsIgris/sylon/refs/heads/nils/client/agent.py",
    "remote_command_url": "https://raw.githubusercontent.com/NilsIgris/sylon/refs/heads/nils/client/command.py",
    "update_interval_seconds" : 3000,
    "timeout_seconds": 10,
    "max_retries": 5,
    "backoff_base": 2,
    "jitter": 0.3
}

# --- CONFIG LOADING AND CODE UPDATING ---

def load_config(path=CONFIG_FILE_PATH):
    """Loads config from local file, or uses defaults. This is the only source of config now."""
    cfg = DEFAULT_CONFIG.copy()
    if os.path.exists(path):
        try:
            with open(path) as f:
                local_cfg = yaml.safe_load(f)
            if local_cfg:
                cfg.update(local_cfg)
        except Exception as e:
            logger.error("Error loading local config file %s: %s", path, e)
    else:
        logger.warning("Config file not found (%s), using defaults", path)
    return cfg


# --- MAIN LOOP (Updated) ---

def main():
    """Main execution loop for collecting metrics and updating code."""
    # Load config from local YAML file only
    cfg = load_config() 
    
    # Determine the absolute path of the running script (used for self-update)
    SCRIPT_PATH = os.path.abspath(sys.argv[0])
    logger.info("Running script path: %s", SCRIPT_PATH)

    # Intervals are based on the locally loaded config
    metric_interval = int(cfg.get("interval_seconds", 300))
    update_interval = int(cfg.get("update_interval_seconds", 3000))
    
    last_metric_send = time.time()
    # Forces an initial check for code update on startup
    last_code_update_check = time.time() - update_interval 

    logger.info("Starting agent; sending to %s every %s seconds, checking for CODE updates every %s seconds", 
                cfg["endpoint"], metric_interval, update_interval)

    while True:
        current_time = time.time()
        
        # 1. Check for remote code update
        if current_time - last_code_update_check >= update_interval:
            
            # Check and apply code update
            if command.update_agent_code(cfg, SCRIPT_PATH):
                # If update_agent_code is successful, it calls sys.exit(0)
                # and this loop iteration will stop, triggering a restart.
                logger.info("Update available for agent")
                #version = __file__[49:62]
                version = "cacatosaure"
                logger.info("Local agent version is %s" , version)

            last_code_update_check = current_time

        # 2. Collect and send metrics
        if current_time - last_metric_send >= metric_interval:
            try:
                payload = command.collect_metrics()
                command.send_payload(cfg, payload)
                last_metric_send = current_time
            except Exception as e:
                logger.exception("Unexpected error in metric collection/send loop: %s", e)

        # Calculate time to sleep until the next event (either metric or code update check)
        time_until_next_metric = max(0, metric_interval - (current_time - last_metric_send))
        time_until_next_update = max(0, update_interval - (current_time - last_code_update_check))
        
        sleep_time = min(time_until_next_metric, time_until_next_update)
        
        # Ensure minimum sleep time to prevent tight loop
        if sleep_time < 1:
             sleep_time = 1
             
        time.sleep(sleep_time)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        sys.exit(0)
