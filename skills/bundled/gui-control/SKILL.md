---
name: gui-control
description: Control keyboard, mouse, and windows autonomously like Jarvis
trigger: type, press, click, move mouse, screenshot, minimize, maximize, focus, switch, shortcut, keyboard, gui, control window, clipboard, copy, paste, list windows, find window, close window, move window, resize window, window
---

## Steps

1. **Understand what user wants to control**
   - Identify the target: keyboard, mouse, window, or application
   - Determine the specific action needed
   - If unclear, ask for clarification

2. **Check if you already know the shortcut**
   - Use search_memory to check if you've learned this shortcut before
   - Search for keywords like the action name (e.g., "minimize all")
   - If found in memory, use it directly - skip to step 4

3. **Search for the right approach (if not in memory)**
   - Use search_web to find:
     - Windows keyboard shortcuts for the task
     - How to automate the specific action
     - Best practices for the operation
   - Learn from search results, don't assume
   - IMPORTANT: After finding a shortcut, save it using add_to_long_term_memory
     - Category: "Important Facts"
     - Content: "Windows shortcut: [action] = [keys]"
     - Example: "Windows shortcut: show desktop = [keys you found]"
   - This builds a knowledge base so you don't need to search again

4. **Plan the automation sequence**
   - Break complex tasks into steps
   - Example: "Focus Notepad and type" = 
     1. Use window_clipboard to switch to Notepad
     2. Wait briefly
     3. Type the text
   - Consider timing between actions (use duration/interval)

5. **Execute with gui_control tool**
   - Available actions:
     - `type` - Type text (params: text, interval)
     - `press` - Press single key (params: key)
     - `hotkey` - Execute shortcut (params: keys as "ctrl,c")
     - `click` - Click mouse (params: x, y, button, clicks)
     - `move_mouse` - Move cursor (params: x, y, duration)
     - `scroll` - Scroll (params: amount)
     - `drag` - Drag mouse (params: x, y, duration)
     - `screenshot` - Capture screen (params: text for filename)
     - `get_position` - Get mouse coordinates
     - `alert` - Show message box (params: text)

6. **Use window_clipboard tool for advanced operations**
   - Window management:
     - `list_windows` - List all open windows
     - `find_window` - Find window by title or process name
     - `switch_to_window` - Switch to specific app (params: title or process)
     - `get_active_window` - Get current active window info
     - `minimize_window` - Minimize window (params: title/process, or active if none)
     - `maximize_window` - Maximize window (params: title/process, or active if none)
     - `restore_window` - Restore window to normal size
     - `close_window` - Close window (params: title or process)
     - `move_window` - Move window (params: x, y, title/process)
     - `resize_window` - Resize window (params: width, height, title/process)
   - Clipboard operations:
     - `clipboard_read` - Read text from clipboard
     - `clipboard_write` - Write text to clipboard (params: text)
     - `clipboard_clear` - Clear clipboard

7. **Handle errors gracefully**
   - If action fails, try alternative approach
   - Use search_web to find solutions
   - Explain what went wrong

8. **Verify success**
   - For critical actions, confirm completion
   - Offer to take screenshot as proof
   - Ask user if result is correct

## Rules

- NEVER use hardcoded shortcuts - ALWAYS search online or check memory first
- ALWAYS check memory first using search_memory before searching online
- After finding a shortcut online, ALWAYS save it to long-term memory using add_to_long_term_memory
- Save format: "Windows shortcut: [action] = [keys]" in "Important Facts" category
- Build your knowledge base over time - each search makes you smarter
- Don't assume you know shortcuts - verify by searching or checking memory
- Use appropriate timing (duration/interval) for smooth automation
- For complex sequences, break into multiple gui_control calls
- Test with get_position before clicking if coordinates needed
- Use hotkey for shortcuts, not multiple press commands
- Keys in hotkey must be comma-separated: "ctrl,c" not "ctrl+c"
- Common key names: enter, tab, esc, space, backspace, delete, up, down, left, right, f1-f12, win, ctrl, alt, shift
- For typing, use interval parameter to control speed (default 0.05s)
- For mouse movements, use duration for smooth motion (default 0.5s)
- FAILSAFE: Moving mouse to screen corner aborts (safety feature)
- If user asks for a shortcut, search for it first, then execute
- If user says "switch to X app", use window_clipboard tool to find and switch
- Always explain what you're doing before executing
- For destructive actions (close, delete), ask for confirmation
