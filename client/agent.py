#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent léger : collecte métriques et POST JSON vers API distante.
Config via /etc/sylon/config.yaml
"""
import time, os, sys, socket, uuid, random, json, logging
from datetime import datetime
import psutil
import requests
import yaml

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger("sylon-agent")

# Default config
DEFAULT_CONFIG = {
    "endpoint": "NULL",
    "api_key": "NULL",
    "interval_seconds": 300,
    "timeout_seconds": 10,
    "max_retries": 5,
    "backoff_base": 2,
    "jitter": 0.3
}

def load_config(path="/etc/sylon/config.yaml"):
    if os.path.exists(path):
        with open(path) as f:
            cfg = yaml.safe_load(f)
            if not cfg: return DEFAULT_CONFIG
            DEFAULT_CONFIG.update(cfg)
            return DEFAULT_CONFIG
    else:
        logger.warning("Config file not found, using defaults")
        return DEFAULT_CONFIG

def collect_metrics():
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

def get_machine_id():
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

def send_payload(cfg, payload):
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {cfg['api_key']}"
    }
    url = cfg["endpoint"]
    max_retries = cfg.get("max_retries", 5)
    base = cfg.get("backoff_base", 2)
    jitter = cfg.get("jitter", 0.3)
    timeout = cfg.get("timeout_seconds", 10)

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

def main():
    cfg = load_config()
    interval = int(cfg.get("interval_seconds", 300))
    logger.info("Starting agent; sending to %s every %s seconds", cfg["endpoint"], interval)
    while True:
        try:
            payload = collect_metrics()
            send_payload(cfg, payload)
        except Exception as e:
            logger.exception("Unexpected error in main loop: %s", e)
        time.sleep(interval)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        sys.exit(0)