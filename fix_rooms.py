import os

ROOT = r"C:\foreverstill\systems\wren_sovereign"
TARGET_FILES = [
    r"wren\mind\memory_tools.py",
    r"wren\core\gateway.py"
]

# The wrong line we just created vs the absolute truth
WRONG = "from wren.rooms import rooms as room_registry"
RIGHT = "from wren import rooms as room_registry"

def fix():
    print("🛠️ Applying Rooms Import Correction...")
    for rel_path in TARGET_FILES:
        full_path = os.path.join(ROOT, rel_path)
        if not os.path.exists(full_path):
            continue
            
        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        if WRONG in content:
            new_content = content.replace(WRONG, RIGHT)
            with open(full_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"✅ Corrected: {rel_path}")
        else:
            print(f"⚪ No error found in: {rel_path}")

if __name__ == "__main__":
    fix()
