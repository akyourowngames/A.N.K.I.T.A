# ANKITA Browser Extension

This Chrome extension is the Phase 2 executor for ANKITA's localhost browser bridge.

## What it does

- Connects to `browser_bridge.py` on `127.0.0.1:8766`
- Registers itself as a browser executor
- Long-polls for commands
- Executes DOM-aware browser actions on the active logged-in browser tab
- Returns structured results back to ANKITA

## Install

1. Start ANKITA or run the bridge directly:
   - `python chatbot.py`
   - or `python browser_bridge.py`
2. Open Chrome and go to `chrome://extensions`
3. Enable `Developer mode`
4. Click `Load unpacked`
5. Select the `browser_extension` folder from this repo

## Usage

- Open the extension popup
- Check that the bridge is connected
- Use `Attach Active Tab` to bind ANKITA to the tab you already have open
- After that, ANKITA can use `browser_automation` with the bridge backend

## Current capabilities

- Attach to active tab
- Open/navigate/reload/back/forward
- DOM click, fill, select, hover, wait, extract, snapshot
- Switch tab, close tab, create tab
- Visible tab screenshots

## Current limits

- File upload from arbitrary local paths is not implemented yet
- Arbitrary code-string execution is intentionally disabled in the content script
- Restricted URLs like `chrome://` pages are not scriptable
