"""
WiFi Tool - Enable/disable WiFi and get connection status.
Polished with better status messages and error handling.
"""
import subprocess


def _run_netsh(cmd: list[str]) -> tuple[bool, str]:
    """Run a netsh command and return (success, output)."""
    try:
        result = subprocess.run(
            ["netsh"] + cmd,
            capture_output=True,
            text=True,
            shell=False,
            timeout=10
        )
        output = (result.stdout or "") + (result.stderr or "")
        return result.returncode == 0, output.strip()
    except Exception as e:
        return False, str(e)


def _get_wifi_interface() -> str | None:
    """Get the first available WiFi interface name."""
    ok, output = _run_netsh(["wlan", "show", "interfaces"])
    if not ok:
        return None
    
    for line in output.split("\n"):
        line = line.strip()
        if line.lower().startswith("name"):
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()
    return "Wi-Fi"  # Default name


def run(action: str = "status", **kwargs) -> dict:
    """
    Manage WiFi connection.
    
    Actions:
        - status/info: Get current WiFi connection status
        - on/enable: Enable WiFi adapter
        - off/disable: Disable WiFi adapter
        - networks/scan: List available networks
        - disconnect: Disconnect from current network
    """
    action = (action or "status").strip().lower()
    
    # Normalize action aliases
    action_aliases = {
        "info": "status",
        "state": "status",
        "check": "status",
        "enable": "on",
        "disable": "off",
        "scan": "networks",
        "list": "networks",
    }
    action = action_aliases.get(action, action)
    
    interface = _get_wifi_interface()
    
    try:
        if action in ("status",):
            ok, output = _run_netsh(["wlan", "show", "interfaces"])
            
            if not ok or "no wireless" in output.lower():
                return {
                    "status": "success",
                    "message": "WiFi adapter not found or disabled",
                    "connected": False,
                    "enabled": False
                }
            
            # Parse the output
            connected = False
            ssid = None
            signal = None
            
            for line in output.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    key = key.strip().lower()
                    value = value.strip()
                    
                    if "state" in key:
                        connected = value.lower() == "connected"
                    elif "ssid" in key and "bssid" not in key:
                        ssid = value
                    elif "signal" in key:
                        signal = value
            
            if connected and ssid:
                message = f"Connected to '{ssid}'"
                if signal:
                    message += f" ({signal} signal)"
                return {
                    "status": "success",
                    "message": message,
                    "connected": True,
                    "ssid": ssid,
                    "signal": signal
                }
            else:
                return {
                    "status": "success",
                    "message": "WiFi is on but not connected to any network",
                    "connected": False,
                    "enabled": True
                }
        
        if action in ("on",):
            ok, output = _run_netsh(["interface", "set", "interface", interface, "admin=enabled"])
            if ok or "enabled" in output.lower():
                return {"status": "success", "message": "WiFi enabled"}
            if "elevation" in output.lower() or "administrator" in output.lower():
                return {"status": "fail", "reason": "Requires administrator privileges", "hint": "Run as admin"}
            return {"status": "fail", "reason": "Failed to enable WiFi", "error": output}
        
        if action in ("off",):
            ok, output = _run_netsh(["interface", "set", "interface", interface, "admin=disabled"])
            if ok or "disabled" in output.lower():
                return {"status": "success", "message": "WiFi disabled"}
            if "elevation" in output.lower() or "administrator" in output.lower():
                return {"status": "fail", "reason": "Requires administrator privileges", "hint": "Run as admin"}
            return {"status": "fail", "reason": "Failed to disable WiFi", "error": output}
        
        if action in ("networks",):
            ok, output = _run_netsh(["wlan", "show", "networks", "mode=bssid"])
            
            if not ok:
                return {"status": "fail", "reason": "Failed to scan networks", "error": output}
            
            networks = []
            current_network = {}
            
            for line in output.split("\n"):
                line = line.strip()
                if line.startswith("SSID") and "BSSID" not in line:
                    if current_network and current_network.get("ssid"):
                        networks.append(current_network)
                    parts = line.split(":", 1)
                    ssid = parts[1].strip() if len(parts) > 1 else ""
                    current_network = {"ssid": ssid}
                elif "Signal" in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        current_network["signal"] = parts[1].strip()
                elif "Authentication" in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        current_network["security"] = parts[1].strip()
            
            if current_network and current_network.get("ssid"):
                networks.append(current_network)
            
            # Filter out empty SSIDs
            networks = [n for n in networks if n.get("ssid")]
            
            if networks:
                # Format network list
                net_list = ", ".join([f"{n['ssid']} ({n.get('signal', '?')})" for n in networks[:5]])
                return {
                    "status": "success",
                    "message": f"Found {len(networks)} networks: {net_list}",
                    "networks": networks[:10]
                }
            return {"status": "success", "message": "No networks found", "networks": []}
        
        if action in ("disconnect",):
            ok, output = _run_netsh(["wlan", "disconnect"])
            if ok:
                return {"status": "success", "message": "Disconnected from WiFi"}
            return {"status": "fail", "reason": "Failed to disconnect", "error": output}
        
        return {"status": "fail", "reason": f"Unknown action: {action}"}
        
    except Exception as e:
        return {"status": "fail", "reason": "WiFi operation failed", "error": str(e)}
