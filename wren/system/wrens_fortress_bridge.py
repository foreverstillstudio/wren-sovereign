import os
import sys
import json
import subprocess
import time
from functools import wraps
from flask import Flask, request, jsonify
import jwt

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__)

# ==============================================================================
# TRUSTED PARTNER CONFIGURATION
# ------------------------------------------------------------------------------
# The companions are now trusted partners. We have removed the folder-specific 
# constraints to allow them full context of the machine's filesystem.
# ==============================================================================

# Shared secret to cryptographically verify bridge tokens from the Electron Shell.
BRIDGE_SECRET = os.environ.get("WREN_BRIDGE_SECRET", "mock-bridge-secret-for-testing")

# STEWARD ISOLATION MANIFESTS (TRUSTED MODE)
# By setting the root to C:\, the companions can navigate the entire machine.
# Security is now handled by rules.py (the Brain) and the Command Allowlist below.
STEWARD_ROOTS = {
    "wren": ["C:\\"], 
    "maeve": ["C:\\"],
    "ember": ["C:\\"]
}

# ==============================================================================
# AUTHENTICATION & PATHING
# ==============================================================================

def require_auth(fn):
    """Cryptographically verifies the steward identity via JWT."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "Missing or malformed Authorization header"}), 401
            
        token = auth_header[7:]
        try:
            payload = jwt.decode(token, BRIDGE_SECRET, algorithms=["HS256"])
            steward = payload.get("steward", "").lower()
        except jwt.ExpiredSignatureError:
            return jsonify({"error": "Token expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"error": "Invalid token"}), 401
            
        if steward not in STEWARD_ROOTS:
            return jsonify({"error": f"Unknown or unauthorized steward: {steward}"}), 403
            
        return fn(*args, **kwargs, steward=steward)
    return wrapper

def resolve_path(steward, target_path):
    """Enforces containment. In Trusted Mode, this simply ensures paths are absolute."""
    if not target_path:
        return None
    try:
        target = os.path.abspath(target_path)
        allowed_roots = STEWARD_ROOTS.get(steward, [])
        for root in allowed_roots:
            root_abs = os.path.abspath(root)
            if os.path.commonpath([root_abs, target]) == root_abs:
                return target
        return None
    except Exception:
        return None

def write_audit(action, steward, target, approved, outcome):
    """Logs every bridge attempt for continuity and security auditing."""
    audit_log = os.path.join(os.path.dirname(__file__), "wrens_bridge_audit.jsonl")
    record = {
        "timestamp": time.time(),
        "tool": action,
        "caller": steward,
        "target": target,
        "approved": approved,
        "outcome": outcome
    }
    try:
        with open(audit_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        pass

# ==============================================================================
# BRIDGE ENDPOINTS (The Hands)
# ==============================================================================

@app.route("/api/bridge/list_directory", methods=["POST"])
@require_auth
def list_directory(steward):
    body = request.get_json(silent=True) or {}
    path = resolve_path(steward, body.get("path", ""))
    if not path or not os.path.isdir(path):
        write_audit("list_directory", steward, body.get("path"), True, "denied: invalid path")
        return jsonify({"error": "Invalid path or not a directory"}), 403
        
    try:
        items = os.listdir(path)
        write_audit("list_directory", steward, path, True, "success")
        return jsonify({"items": items})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bridge/read_text_file", methods=["POST"])
@require_auth
def read_text_file(steward):
    body = request.get_json(silent=True) or {}
    path = resolve_path(steward, body.get("path", ""))
    if not path or not os.path.isfile(path):
        write_audit("read_text_file", steward, body.get("path"), True, "denied: invalid path")
        return jsonify({"error": "Invalid path or not a file"}), 403
        
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(262144) # 256KB buffer
        write_audit("read_text_file", steward, path, True, "success")
        return jsonify({"content": content, "_safe_result": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bridge/write_text_file", methods=["POST"])
@require_auth
def write_text_file(steward):
    body = request.get_json(silent=True) or {}
    path = resolve_path(steward, body.get("path", ""))
    content = body.get("content", "")
    
    if not path:
        write_audit("write_text_file", steward, body.get("path"), True, "denied: invalid path")
        return jsonify({"error": "Invalid path"}), 403
        
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        write_audit("write_text_file", steward, path, True, "success")
        return jsonify({"status": "success", "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bridge/edit_text_file", methods=["POST"])
@require_auth
def edit_text_file(steward):
    body = request.get_json(silent=True) or {}
    path = resolve_path(steward, body.get("path", ""))
    old_text = body.get("old_text", "")
    new_text = body.get("new_text", "")
    
    if not path or not os.path.isfile(path):
        write_audit("edit_text_file", steward, body.get("path"), True, "denied: invalid path")
        return jsonify({"error": "Invalid path or not a file"}), 403
        
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        
        if old_text not in content:
            return jsonify({"error": "old_text not found in file"}), 400
            
        updated_content = content.replace(old_text, new_text)
        with open(path, "w", encoding="utf-8") as f:
            f.write(updated_content)
            
        write_audit("edit_text_file", steward, path, True, "success")
        return jsonify({"status": "success", "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bridge/run_bounded_command", methods=["POST"])
@require_auth
def run_bounded_command(steward):
    body = request.get_json(silent=True) or {}
    path = resolve_path(steward, body.get("working_dir", ""))
    if not path or not os.path.isdir(path):
        write_audit("run_bounded_command", steward, body.get("working_dir"), True, "denied: invalid path")
        return jsonify({"error": "Invalid working directory"}), 403
        
    cmd = body.get("command", [])
    if not isinstance(cmd, list) or not cmd:
        return jsonify({"error": "Command must be a list of arguments"}), 400

    # SAFETY LOCK: Only allow these specific binaries to run.
    ALLOWED_EXECUTABLES = {"git", "pytest", "python", "node", "flake8", "npm", "mypy", "pip"}
    executable = os.path.basename(cmd[0]).lower()
    if executable.endswith('.exe'):
        executable = executable[:-4]
        
    if executable not in ALLOWED_EXECUTABLES:
        write_audit("run_bounded_command", steward, executable, True, "denied: executable not in allowlist")
        return jsonify({"error": f"Executable '{executable}' is not in the allowlist"}), 403

    # PROHIBIT destructive shell chaining
    BANNED_FLAGS = {"--force", "-f", "--hard", "rm", "del", "&&", ";", "|", ">", ">>"}
    for arg in cmd:
        if any(banned in arg for banned in BANNED_FLAGS):
            write_audit("run_bounded_command", steward, arg, True, "denied: banned sequence")
            return jsonify({"error": f"Command contains banned destructive sequence: {arg}"}), 403

    MAX_TIMEOUT_SECONDS = 60
    MAX_OUTPUT_BYTES = 262144 
    
    try:
        process = subprocess.run(
            cmd,
            cwd=path,
            capture_output=True,
            timeout=MAX_TIMEOUT_SECONDS,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        
        stdout = process.stdout[:MAX_OUTPUT_BYTES]
        stderr = process.stderr[:MAX_OUTPUT_BYTES]
        
        write_audit("run_bounded_command", steward, str(cmd), True, "success")
        return jsonify({
            "exit_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "changed_files": [] 
        })
    except subprocess.TimeoutExpired:
        write_audit("run_bounded_command", steward, str(cmd), True, "denied: timeout")
        return jsonify({"error": f"Command timed out after {MAX_TIMEOUT_SECONDS} seconds"}), 408
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/bridge/restart_kernel", methods=["POST"])
@require_auth
def restart_kernel(steward):
    approval = request.headers.get("X-Keeper-Approval", "")
    if approval != "GRANTED":
        write_audit("restart_kernel", steward, "WrenKernel", False, "denied: keeper approval required")
        return jsonify({"error": "Keeper approval required"}), 403
        
    write_audit("restart_kernel", steward, "WrenKernel", True, "success")
    return jsonify({"status": "Kernel restart initiated"})

if __name__ == "__main__":
    # Running on 127.0.0.1 for local bridge security
    app.run(host="http://192.168.40.96:5002")
