# Telegram Bot Command Handling Fix Plan

## Overview

**Problem:**
The current Telegram integration for RadSim doesn't properly process bot commands sent from mobile devices. When users send `/commands`, the bot doesn't return available options, and the system lacks true agentic behavior for command discovery and interaction.

**Goal:**
Enable intelligent bot command processing with inline keyboards, command discovery, and proper argument parsing for a fully agentic Telegram experience.

---

## Current Issues Identified

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| 1 | **No Bot Command Entity Parsing** | `telegram.py` | Commands parsed as raw text only, missing Telegram's `entities` metadata |
| 2 | **Hardcoded Safe Commands List** | `agent.py` | Static `telegram_safe_commands` set doesn't reflect actual available commands |
| 3 | **No Command Discovery/Help** | `agent.py` | Users sending `/commands` receive no response about available options |
| 4 | **No Inline Keyboard Support** | `telegram.py` | Missing reply markup for clickable buttons |
| 5 | **Command Arguments Not Parsed** | `telegram.py` | Commands like `/skill learn file.md` aren't properly routed |
| 6 | **Missing Bot Menu Registration** | `telegram.py` | No `setMyCommands` API call for Telegram's native menu |

---

## Phase 1: Enhanced Message Parsing

**File:** `radsim/telegram.py`

### New Functions

#### `parse_incoming_message(message: dict) -> dict`
Extract command, text, and arguments from Telegram message with entity support.

**Input:**
```json
{
  "message_id": 123,
  "from": {"first_name": "User"},
  "chat": {"id": "7779435210"},
  "date": 1704067200,
  "text": "/skill learn coding.md",
  "entities": [
    {"offset": 0, "length": 6, "type": "bot_command"}
  ]
}
```

**Output:**
```json
{
  "text": "/skill learn coding.md",
  "sender": "User",
  "chat_id": "7779435210",
  "timestamp": 1704067200,
  "is_command": true,
  "command": "/skill",
  "args": ["learn", "coding.md"],
  "entities": [...]
}
```

### Code Template
```python
def parse_incoming_message(message: dict) -> dict:
    """Extract command metadata from Telegram message.
    
    Args:
        message: Raw message dict from Telegram API
        
    Returns:
        Enriched message dict with parsed command info
    """
    text = message.get("text", "")
    chat_id = str(message.get("chat", {}).get("id", ""))
    sender = message.get("from", {}).get("first_name", "Unknown")
    timestamp = message.get("date", 0)
    
    result = {
        "text": text,
        "sender": sender,
        "chat_id": chat_id,
        "timestamp": timestamp,
        "is_command": False,
        "command": None,
        "args": [],
    }
    
    # Check for bot command entities
    entities = message.get("entities", [])
    for entity in entities:
        if entity.get("type") == "bot_command":
            offset = entity.get("offset", 0)
            length = entity.get("length", 0)
            full_command = text[offset:offset + length]
            
            # Split command from args
            parts = text.split()
            if parts:
                result["command"] = parts[0].lower()
                result["args"] = parts[1:]
                result["is_command"] = True
            break
    
    return result
```

---

## Phase 2: Command Registry Integration

**File:** `radsim/agent.py` and `radsim/commands.py`

### Changes to `CommandRegistry`

#### New Method: `is_telegram_safe(command: str) -> bool`
Determine if a command can run without interactive terminal input.

```python
def is_telegram_safe(self, command: str) -> bool:
    """Check if command is safe to run via Telegram.
    
    Safe commands:
    - Don't call input()
    - Don't require tty access
    - Have predictable execution time
    
    Blocked commands:
    - Any requiring interactive confirmation
    - File/directory selection prompts
    - Commands needing terminal output display
    """
    # Interactive/blocking commands
    blocked = {
        "/config", "/switch", "/setup",
        "/exit", "/quit", "/kill", "/stop", "/abort"
    }
    
    if command in blocked:
        return False
    
    # Check if command handler signature suggests interactivity
    handler = self.commands.get(command, {}).get("handler")
    if handler:
        import inspect
        source = inspect.getsource(handler)
        # Commands using input() are not Telegram-safe
        if "input(" in source:
            return False
    
    return True
```

#### New Method: `get_telegram_command_list() -> list`
Return formatted list of available commands with descriptions.

```python
def get_telegram_command_list(self) -> list:
    """Get list of commands safe for Telegram with descriptions."""
    commands = []
    for name, info in self.commands.items():
        if info.get("primary") == name:  # Only add primary names, not aliases
            if self.is_telegram_safe(name):
                commands.append({
                    "command": name.lstrip("/"),
                    "description": info.get("description", "")[:64]  # Telegram limit
                })
    return sorted(commands, key=lambda x: x["command"])
```

### Update to `_telegram_loop` in `agent.py`

**Replace:**
```python
# Commands safe to run via Telegram (no input() calls)
telegram_safe_commands = {"/help", "/tools", ...}
```

**With:**
```python
# Dynamic command safety check
registry = CommandRegistry()
```

**Add command routing:**
```python
if msg.get("is_command"):
    cmd = msg["command"]
    args = msg.get("args", [])
    
    if registry.is_telegram_safe(cmd):
        result = registry.handle_telegram_command(cmd, args, agent)
        send_telegram_message(result["message"], keyboard=result.get("keyboard"))
    else:
        send_telegram_message(
            f"⚠️ Command '{cmd}' requires terminal interaction.\n"
            f"Please run it directly in the RadSim terminal."
        )
    continue
```

---

## Phase 3: Inline Keyboard Support

**File:** `radsim/telegram.py`

### New Functions

#### `send_message_with_keyboard(chat_id, text, buttons: list) -> dict`
Send message with inline keyboard markup.

```python
def send_message_with_keyboard(message, buttons: list, token=None, chat_id=None):
    """Send message with inline keyboard options.
    
    Args:
        message: Text message to send
        buttons: List of dicts with 'text' and 'callback_data' keys
                 Example: [{"text": "Learn", "callback_data": "skill_learn"}]
        token: Bot token
        chat_id: Target chat ID
        
    Returns:
        Dict with success status and message_id
    """
    if not token or not chat_id:
        token, chat_id = load_telegram_config()
    
    url = f"{TELEGRAM_API_BASE}{token}/sendMessage"
    
    # Build inline keyboard structure
    keyboard = []
    row = []
    for btn in buttons:
        row.append({
            "text": btn["text"],
            "callback_data": btn.get("callback_data", btn["text"])
        })
        if len(row) == 2:  # 2 buttons per row
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    body = {
        "chat_id": chat_id,
        "text": message,
        "reply_markup": {
            "inline_keyboard": keyboard
        }
    }
    
    # ... send request
```

#### `create_command_keyboard(command: str, args: list = None) -> list`
Generate appropriate keyboard buttons for a given command.

```python
def create_command_keyboard(command: str, args: list = None) -> list:
    """Create context-aware keyboard for command.
    
    Args:
        command: The slash command (e.g., "/skill")
        args: Already provided arguments
        
    Returns:
        List of button dicts for inline keyboard
    """
    keyboards = {
        "/skill": [
            {"text": "📚 List Skills", "callback_data": "skill_list"},
            {"text": "➕ Learn Skill", "callback_data": "skill_learn"},
            {"text": "🗑️ Clear Skill", "callback_data": "skill_clear"},
            {"text": "❓ Help", "callback_data": "skill_help"},
        ],
        "/memory": [
            {"text": "💾 Show All", "callback_data": "memory_show"},
            {"text": "🔍 Search", "callback_data": "memory_search"},
            {"text": "🧹 Clear All", "callback_data": "memory_clear"},
        ],
        "/tools": [
            {"text": "🔧 Core Tools", "callback_data": "tools_core"},
            {"text": "📁 File Ops", "callback_data": "tools_file"},
            {"text": "🌐 Web Tools", "callback_data": "tools_web"},
        ],
        "/commands": [
            {"text": "⚡ Quick Actions", "callback_data": "cmds_quick"},
            {"text": "⚙️ Settings", "callback_data": "cmds_settings"},
            {"text": "📊 Status", "callback_data": "cmds_status"},
        ],
    }
    
    # If subcommand provided, show context-specific options
    if args and args[0] in ["learn", "list", "clear"]:
        return [
            {"text": "⬅️ Back", "callback_data": "main_menu"},
        ]
    
    return keyboards.get(command, [
        {"text": "📖 Help", "callback_data": "help"},
        {"text": "🔄 Refresh", "callback_data": f"refresh_{command}"},
    ])
```

#### `handle_callback_query(update: dict) -> dict`
Process button click callbacks from inline keyboards.

```python
def handle_callback_query(update: dict) -> dict:
    """Process callback from inline keyboard button press.
    
    Args:
        update: Telegram update containing callback_query
        
    Returns:
        Dict with action to take
    """
    query = update.get("callback_query", {})
    callback_data = query.get("data", "")
    message = query.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    message_id = message.get("message_id")
    
    result = {
        "type": "callback",
        "callback_data": callback_data,
        "chat_id": chat_id,
        "message_id": message_id,
        "action": None,
        "response_text": None,
    }
    
    # Map callback_data to actions
    if callback_data.startswith("skill_"):
        subcommand = callback_data.replace("skill_", "")
        result["action"] = "execute_command"
        result["command"] = "/skill"
        result["args"] = [subcommand]
        result["response_text"] = f"Executing: /skill {subcommand}"
        
    elif callback_data.startswith("memory_"):
        subcommand = callback_data.replace("memory_", "")
        result["action"] = "execute_command"
        result["command"] = "/memory"
        result["args"] = [subcommand]
        
    elif callback_data == "main_menu":
        result["action"] = "show_help"
        result["response_text"] = "Main menu - use /commands to see all options"
        
    else:
        result["action"] = "unknown"
        result["response_text"] = "Unknown option selected"
    
    return result
```

#### `answer_callback_query(query_id: str, token: str, text: str = None)`
Acknowledge button press to Telegram.

---

## Phase 4: Command Response System

**File:** `radsim/agent.py`

### Enhanced `_telegram_loop` Logic

```python
def _telegram_loop():
    """Background loop for processing Telegram messages."""
    from .commands import CommandRegistry
    from .telegram import (
        check_incoming, is_listening, send_telegram_message,
        send_message_with_keyboard, create_command_keyboard,
        handle_callback_query, answer_callback_query
    )
    
    registry = CommandRegistry()
    
    while True:
        time.sleep(0.5)
        try:
            if not is_listening():
                continue
            
            # Check for incoming messages
            msg = check_incoming()
            if msg:
                process_telegram_message(msg, registry, agent)
            
            # Also check for callback queries (button presses)
            callback = check_incoming_callback()
            if callback:
                process_callback_query(callback, registry, agent)
                
        except Exception as err:
            logger.debug(f"Telegram processor error: {err}")

def process_telegram_message(msg, registry, agent):
    """Handle incoming text message or command."""
    sender = msg.get("sender", "Telegram")
    text = msg.get("text", "")
    
    print_info(f"\n[Telegram from {sender}]: {text}")
    
    # Handle bot commands
    if msg.get("is_command"):
        cmd = msg["command"]
        args = msg.get("args", [])
        
        # Special handling for /help command
        if cmd == "/help":
            commands = registry.get_telegram_command_list()
            help_text = format_telegram_help(commands)
            send_telegram_message(help_text)
            return
        
        # Special handling for /commands
        if cmd == "/commands":
            keyboard = create_command_keyboard(cmd, args)
            send_message_with_keyboard(
                "Choose a category to explore commands:",
                keyboard
            )
            return
        
        # Check if command is safe
        if not registry.is_telegram_safe(cmd):
            send_telegram_message(
                f"⚠️ *'{cmd}' requires terminal interaction*\n\n"
                f"This command needs direct access to your terminal. "
                f"Please run it in the RadSim terminal session.",
                parse_mode="Markdown"
            )
            return
        
        # Execute safe command
        with agent._processing_lock:
            # For commands with sub-options, show keyboard
            if not args and cmd in ["/skill", "/memory", "/tools"]:
                keyboard = create_command_keyboard(cmd, args)
                send_message_with_keyboard(
                    f"What would you like to do with *{cmd}*?",
                    keyboard,
                    parse_mode="Markdown"
                )
                return
            
            # Execute the command
            result = registry.handle_telegram_input(cmd, args, agent)
            if result.get("response"):
                reply = result["response"][:4000]  # Telegram limit
                send_telegram_message(reply)

def process_callback_query(callback, registry, agent):
    """Handle inline keyboard button presses."""
    action = handle_callback_query(callback)
    
    # Answer the callback (required by Telegram)
    answer_callback_query(
        callback["callback_query"]["id"],
        text=action.get("response_text")
    )
    
    if action["action"] == "execute_command":
        result = registry.handle_telegram_input(
            action["command"],
            action["args"],
            agent
        )
        if result.get("response"):
            # Edit original message or send new one
            send_telegram_message(result["response"])

def format_telegram_help(commands: list) -> str:
    """Format help text for Telegram."""
    lines = ["*📱 Available Commands*\n"]
    lines.append("Commands you can run from mobile:\n")
    
    for cmd in commands[:20]:  # Limit to avoid message too long
        name = cmd["command"]
        desc = cmd["description"]
        lines.append(f"`/{name}` - {desc}")
    
    lines.append("\n📌 *Tip:* Use /commands for interactive menu")
    return "\n".join(lines)
```

---

## Phase 5: Bot Menu Registration

**File:** `radsim/telegram.py`

### New Function: `set_bot_commands()`

```python
def set_bot_commands(commands: list, token: str = None) -> dict:
    """Register commands with Telegram's native bot menu.
    
    This populates the command menu that appears when users
    type "/" in the chat.
    
    Args:
        commands: List of dicts with 'command' (no slash) and 'description'
        token: Bot token (loads from config if None)
        
    Returns:
        Dict with success status
    """
    if not token:
        token, _ = load_telegram_config()
    
    if not token:
        return {"success": False, "error": "No token configured"}
    
    url = f"{TELEGRAM_API_BASE}{token}/setMyCommands"
    
    # Format for Telegram API
    bot_commands = [
        {
            "command": cmd["command"].lstrip("/"),
            "description": cmd["description"][:64]  # Telegram limit
        }
        for cmd in commands[:100]  # Telegram limit
    ]
    
    body = {"commands": bot_commands}
    data = json.dumps(body).encode("utf-8")
    
    try:
        req = Request(url, data=data, headers={"Content-Type": "application/json"})
        resp = urlopen(req, timeout=10)
        result = json.loads(resp.read().decode("utf-8"))
        
        if result.get("ok"):
            return {"success": True}
        return {"success": False, "error": result.get("description")}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### Integration Point

Call `set_bot_commands()` in `start_listening()` after validating token:

```python
def start_listening():
    """Start the Telegram listener."""
    token, chat_id = load_telegram_config()
    
    # ... validation
    
    # Register commands with Telegram
    from .commands import CommandRegistry
    registry = CommandRegistry()
    commands = registry.get_telegram_command_list()
    result = set_bot_commands(commands, token)
    
    if not result["success"]:
        logger.warning(f"Failed to set bot commands: {result['error']}")
    
    # ... start listener
```

---

## Expected Behavior After Fix

### Scenario 1: User sends `/skill`
```
Bot: "What would you like to do with *\/skill*?"
[📚 List Skills] [➕ Learn Skill]
[🗑️ Clear Skill]  [❓ Help]
```

### Scenario 2: User sends `/commands`
```
Bot: "Choose a category to explore commands:"
[⚡ Quick Actions] [⚙️ Settings]
[📊 Status]       [📁 File Ops]
```

### Scenario 3: User sends `/config` (interactive command)
```
Bot: "⚠️ *'/config' requires terminal interaction*
This command needs direct access to your terminal. 
Please run it in the RadSim terminal session."

[Open Terminal] [Dismiss]
```

### Scenario 4: User taps 📚 "List Skills" button
```
Bot: "📚 *Current Skills:*
1. Always show diffs before edits
2. Use type hints in Python
3. Prefer pytest for testing"
```

### Scenario 5: Mobile Menu Display
When user types "/" in Telegram mobile:
```
┌─────────────────────────────┐
│ /help   - Show help         │
│ /tools  - List all tools    │
│ /status - Check bot status  │
│ /memory - Manage memory     │
│ ...                         │
└─────────────────────────────┘
```

---

## Testing Checklist

- [ ] Send `/help` → Receive formatted command list
- [ ] Send `/commands` → Receive inline keyboard
- [ ] Tap keyboard button → Execute corresponding action
- [ ] Type any `/command` on mobile → See in native command menu
- [ ] Send `/invalid` → Receive "Available commands:" hint
- [ ] Send command with args (`/skill learn test.md`) → Properly parsed and executed
- [ ] Blocked command (`/exit`) → Receive warning with explanation
- [ ] Callback timeout → Graceful handling
- [ ] Invalid callback data → Error handled without crash

---

## Implementation Priority

| Priority | Phase | Effort | Impact |
|----------|-------|--------|--------|
| P0 | Phase 1 - Message Parsing | Medium | High - Foundation for all other work |
| P0 | Phase 5 - Bot Menu | Low | High - Immediate UX improvement |
| P1 | Phase 2 - Registry Integration | Medium | High - Enables dynamic command handling |
| P1 | Phase 4 - Response System | Medium | Medium - Completes command flow |
| P2 | Phase 3 - Inline Keyboards | High | Medium - Enhances mobile UX |

---

## Files to Modify

1. `/Users/brighthome/Documents/CLAUDE CODE/RADSIM/radsim/telegram.py`
   - Add `parse_incoming_message()`, `send_message_with_keyboard()`, `create_command_keyboard()`, `handle_callback_query()`, `set_bot_commands()`

2. `/Users/brighthome/Documents/CLAUDE CODE/RADSIM/radsim/agent.py`
   - Update `_telegram_loop()` with enhanced command routing
   - Add `process_telegram_message()` and `process_callback_query()`

3. `/Users/brighthome/Documents/CLAUDE CODE/RADSIM/radsim/commands.py`
   - Add `is_telegram_safe()`, `get_telegram_command_list()`, `handle_telegram_input()`

---

*Document created for RadSim Telegram bot enhancement*
