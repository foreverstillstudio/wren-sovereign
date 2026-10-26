import os

ROOT = r"C:\foreverstill\systems\wren_sovereign"
TARGET_FILE = r"wren\mind\memory_tools.py"

def fix():
    print("🛠️ Fixing Type-Hint Drift in memory_tools.py...")
    full_path = os.path.join(ROOT, TARGET_FILE)
    if not os.path.exists(full_path):
        print("⚠️ File not found.")
        return
        
    with open(full_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
        
    # 1. Ensure 'Any' is in the typing import
    import_fixed = False
    for i, line in enumerate(lines):
        if line.startswith("from typing import"):
            if "Any" not in line:
                # Insert Any into the existing typing import
                lines[i] = line.replace("import (", "import (Any, ") if "(" in line else line.replace("import ", "import Any, ")
                import_fixed = True
                break
    
    # If no typing import found, add it to the top
    if not import_fixed:
        lines.insert(0, "from typing import Any\n")

    # 2. Replace provider.Provider with Any
    content = "".join(lines)
    if "provider.Provider" in content:
        content = content.replace("provider.Provider", "Any")
        
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print("✅ Type-Hint Drift Purified.")
    else:
        print("⚪ No Provider type-hints found.")

if __name__ == "__main__":
    fix()
