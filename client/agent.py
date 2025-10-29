#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent léger : collecte métriques et POST JSON vers API distante.
Config via /etc/sylon/config.yaml (local only). Ajout de la mise à jour périodique du code.
"""
import time, os, sys, socket, uuid, random, json, logging
from datetime import datetime
import psutil
import requests
import yaml

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

def update_agent_code(cfg, script_path):
    """Downloads the latest agent code, replaces the running script, and exits."""
    remote_url = cfg.get("remote_code_url")
    if remote_url == "NULL" or not remote_url:
        logger.debug("Remote code URL not configured. Skipping code update.")
        return False

    logger.warning("Attempting to self-update agent code from: %s", remote_url)
    timeout = cfg.get("timeout_seconds", 10)

    try:
        # Download the new script
        r = requests.get(remote_url, timeout=timeout)
        r.raise_for_status() 

        new_code = r.text
        
        # Basic integrity check 
        if not new_code or "#!/usr/bin/env python3" not in new_code[:50]:
             logger.error("Downloaded code appears invalid or incomplete. Skipping update.")
             return False

        # Write the new code over the running script
        with open(script_path, "w") as f:
            f.write(new_code)
        
        logger.critical("--- Agent code successfully updated. Exiting (sys.exit(0)) to trigger service restart and load new code. ---")
        return True

    except requests.exceptions.RequestException as e:
        logger.error("Failed to download remote code: %s", e)
    except Exception as e:
        logger.exception("An unexpected error occurred during code update: %s", e)
        
    return False

# --- METRICS AND UTILITIES (No Change) ---

def get_machine_id():
    """Retrieves or generates a unique machine identifier."""
    # Prefer stable host id; fallback to uuid file
    try:
        # systemd-machine-id exists on many distros
        for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            if os.path.exists(path):
                with open(path) as f:
                    return f.read().strip()
    except Exception:
        pass
    # fallback to generated uuid persisted
    path = "/var/lib/sylon/id"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path):
            with open(path) as f:
                return f.read().strip()
        mid = str(uuid.uuid4())
        with open(path, "w") as f:
            f.write(mid)
        return mid
    except Exception:
        return str(uuid.getnode())

def collect_metrics():
    """Collects system metrics."""
    data = {}
    data["timestamp"] = datetime.utcnow().isoformat() + "Z"
    data["hostname"] = socket.gethostname()
    data["machine_id"] = get_machine_id()
    data["platform"] = {
        "system": os.uname().sysname,
        "release": os.uname().release,
        "version": os.uname().version
    }
    # CPU
    data["cpu_percent"] = psutil.cpu_percent(interval=1)
    data["cpu_count_logical"] = psutil.cpu_count(logical=True)
    data["cpu_count_physical"] = psutil.cpu_count(logical=False)
    # Memory
    vm = psutil.virtual_memory()
    data["memory"] = {"total": vm.total, "available": vm.available, "percent": vm.percent}
    # Disk
    du = psutil.disk_usage("/")
    data["disk"] = {"total": du.total, "used": du.used, "free": du.free, "percent": du.percent}
    # Load, uptime, net
    try:
        load1, load5, load15 = os.getloadavg()
        data["loadavg"] = {"1": load1, "5": load5, "15": load15}
    except Exception:
        data["loadavg"] = {}
    data["uptime_seconds"] = int(time.time() - psutil.boot_time())
    net = psutil.net_if_addrs()
    # pick first non-loopback IPv4
    ipv4 = None
    for ifname, addrs in net.items():
        for a in addrs:
            if a.family == socket.AF_INET and not a.address.startswith("127."):
                ipv4 = a.address
                break
        if ipv4: break
    data["ipv4"] = ipv4
    return data

def send_payload(cfg, payload):
    """Sends the collected metrics payload to the remote API endpoint."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}"
    }
    url = cfg["endpoint"]
    max_retries = cfg.get("max_retries", 5)
    base = cfg.get("backoff_base", 2)
    jitter = cfg.get("jitter", 0.3)
    timeout = cfg.get("timeout_seconds", 10)

    if url == "NULL":
        logger.warning("Endpoint is NULL. Skipping payload send.")
        return True

    for attempt in range(1, max_retries+1):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=timeout)
            if r.status_code in (200,201,202):
                logger.info("Payload accepted (status=%s)", r.status_code)
                return True
            elif 400 <= r.status_code < 500:
                logger.error("Client error sending payload: %s %s", r.status_code, r.text)
                return False
            else:
                logger.warning("Server error %s; attempt %s/%s", r.status_code, attempt, max_retries)
        except requests.RequestException as e:
            logger.warning("Request failed attempt %s/%s: %s", attempt, max_retries, e)
        # backoff with jitter
        sleep = (base ** attempt) + random.uniform(0, jitter)
        time.sleep(min(sleep, 60))
    logger.error("All retries failed")
    return False

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
            if update_agent_code(cfg, SCRIPT_PATH):
                # If update_agent_code is successful, it calls sys.exit(0)
                # and this loop iteration will stop, triggering a restart.
                sys.exit(0) 
                
            last_code_update_check = current_time

        # 2. Collect and send metrics
        if current_time - last_metric_send >= metric_interval:
            try:
                payload = collect_metrics()
                send_payload(cfg, payload)
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

# BIG TEST
