import os

def patch_rooms_indent():
    # Path to the file with the indentation error
    file_path = r"C:\foreverstill\systems\wren_sovereign\wren\rooms\__init__.py"
    
    if not os.path.exists(file_path):
        print(f"❌ Error: Could not find {file_path}")
        return

    print(f"🛠️  Opening {file_path} to fix indentation drift...")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    patched = False
    new_lines = []

    for line in lines:
        # Find the line that is missing the indentation
        if line.strip() == "from wren.system import steward_stores as _stewards":
            print("🎯 Found indentation drift. Aligning with function block...")
            # Add the 4 spaces needed to keep it inside the validate_room function
            new_line = "    from wren.system import steward_stores as _stewards\n"
            new_lines.append(new_line)
            patched = True
        else:
            new_lines.append(line)

    if patched:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print("✅ Patch applied. Indentation is now logically sound.")
    else:
        print("⚠️  Could not find the drifting line. It may already be fixed.")

if __name__ == "__main__":
    patch_rooms_indent()
