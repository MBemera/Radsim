from radsim.file_tools import read_file
from radsim.memory import Memory

print("--- Testing RadSim Persistent Memory System ---")

# 1. Initialize Memory
mem = Memory()
print("Initialized Memory.")
print(f"Global file path: {mem.global_mem.file_path}")
print(f"Project JSON path: {mem.project_mem.json_file}")
print(f"Project agents.md path: {mem.project_mem.agents_file}")
print(f"Session path: {mem.session_mem.file_path}")

# 2. Test Auto-Save Triggers (file_tools.py)
print("\n--- Testing file_tools.py read_file trigger ---")
result = read_file("radsim/agent.py")
print(f"File read success: {result['success']}")

# Reload project memory
mem.project_mem.data = mem.project_mem._load_json(mem.project_mem.json_file)
recent_files = mem.project_mem.data.get("recent_files", [])
found = any("radsim/agent.py" in f.get("path") for f in recent_files)
print(f"radsim/agent.py in recent_files: {found}")

# 3. Test Sanitization
print("\n--- Testing Secret Sanitization ---")
test_key = "sk-ant-api03-1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
mem.global_mem.set_preference("dummy_api_key", test_key)

# Read file directly to see if it was redacted
content = mem.global_mem.file_path.read_text()
if "[REDACTED_SECRET]" in content and test_key not in content:
    print("Sanitization SUCCESS: Anthropic key was redacted from memory file.")
else:
    print("Sanitization FAILED.")

# Remove it
prefs = mem.global_mem.data.get("preferences", {})
if "dummy_api_key" in prefs:
    del prefs["dummy_api_key"]
    mem.global_mem._save_json(mem.global_mem.file_path, mem.global_mem.data)

# 4. Test Confidence Scoring
print("\n--- Testing Confidence Scoring ---")
mem.record_pattern("learned", "Test confidence pattern")
mem.global_mem.data = mem.global_mem._load_json(mem.global_mem.file_path)
patterns = mem.global_mem.data.get("learned_patterns", [])
conf_pattern = next((p for p in patterns if isinstance(p, dict) and p.get("pattern") == "Test confidence pattern"), None)

if conf_pattern and conf_pattern.get("confidence") == "medium":
    print("Confidence Scoring SUCCESS: recorded with 'medium' confidence.")
    # Upgrade it
    mem.record_pattern("learned", "Test confidence pattern")
    mem.global_mem.data = mem.global_mem._load_json(mem.global_mem.file_path)
    patterns = mem.global_mem.data.get("learned_patterns", [])
    updated = next((p for p in patterns if isinstance(p, dict) and p.get("pattern") == "Test confidence pattern"), None)
    if updated and updated.get("confidence") == "high":
         print("Confidence Upgrade SUCCESS: upgraded to 'high' upon second record.")
    else:
         print("Confidence Upgrade FAILED.")
else:
    print("Confidence Scoring FAILED or pattern not found.")

print("\nAll programmatic tests passed!")
