"""
Google Sheets Connector for A.N.K.I.T.A 📊

Gives ANKITA structured long-term memory:
  - append_row   : "Add 500rs for Pizza to Expenses"
  - read_range   : "Read my workout log"
  - create_sheet : "Make a new sheet for Project X"
  - list_sheets  : "What spreadsheets do I have?"
  - update_cell  : "Change B3 to 1200 in Expenses"

Authentication: Google OAuth2 via auth_manager.get_google_credentials()
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

_MISSING_LIBS = False
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
except ImportError:
    _MISSING_LIBS = True


def _sheets_service():
    """Build and return an authenticated Google Sheets API service object."""
    if _MISSING_LIBS:
        raise RuntimeError(
            "Google API libraries not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )
    from tools.auth_manager import get_google_credentials
    creds = get_google_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _drive_service():
    """Build and return an authenticated Google Drive API service (for listing spreadsheets)."""
    if _MISSING_LIBS:
        raise RuntimeError(
            "Google API libraries not installed. "
            "Run: pip install google-api-python-client google-auth-oauthlib google-auth-httplib2"
        )
    from tools.auth_manager import get_google_credentials
    creds = get_google_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_spreadsheet_id(service_drive, name: str) -> Optional[str]:
    """Search Google Drive for a spreadsheet by name and return its ID."""
    query = f"mimeType='application/vnd.google-apps.spreadsheet' and name='{name}' and trashed=false"
    results = service_drive.files().list(q=query, fields="files(id, name)", pageSize=5).execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    return None


# ---------------------------------------------------------------------------
# Public API functions (called by engine.py dispatcher)
# ---------------------------------------------------------------------------

def append_row(spreadsheet_name: str, data: List[Any], sheet_tab: str = "Sheet1") -> Dict[str, Any]:
    """
    Append a row of data to the first sheet of the named spreadsheet.

    Args:
        spreadsheet_name: Human-readable name, e.g. "Expenses 2026"
        data: List of values, e.g. ["2026-02-28", "Pizza", 500, "Food"]
        sheet_tab: Tab name within the spreadsheet (default: "Sheet1")

    Returns:
        {"status": "success", "updated_range": "...", "rows_added": 1}
    """
    try:
        svc = _sheets_service()
        drive = _drive_service()

        spreadsheet_id = _find_spreadsheet_id(drive, spreadsheet_name)
        if not spreadsheet_id:
            return {"status": "error", "message": f"Spreadsheet '{spreadsheet_name}' not found in Google Drive."}

        range_name = f"{sheet_tab}!A:Z"
        body = {"values": [data]}
        result = (
            svc.spreadsheets()
            .values()
            .append(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body=body,
            )
            .execute()
        )
        updates = result.get("updates", {})
        return {
            "status": "success",
            "spreadsheet": spreadsheet_name,
            "updated_range": updates.get("updatedRange", ""),
            "rows_added": updates.get("updatedRows", 1),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def _sanitize_sheet(values: List[List[Any]], max_rows: int = 50) -> str:
    """
    Prism Protocol — Sheet Sanitizer 📊
    Converts a raw 2D array from Google Sheets into a clean Markdown table string.
    - Strips completely empty rows
    - Caps at max_rows rows (default 50) to keep context window lean
    - Returns a human-readable table instead of a raw JSON blob
    """
    # Filter empty rows
    non_empty = [row for row in values if any(str(cell).strip() for cell in row)]
    if not non_empty:
        return "_Sheet is empty._"

    capped = non_empty[:max_rows]
    truncated = len(non_empty) > max_rows

    # Determine column count from widest row
    col_count = max(len(row) for row in capped)

    # Pad all rows to same width
    padded = [row + [""] * (col_count - len(row)) for row in capped]

    # Use first row as header if it looks like one (mostly non-numeric)
    def is_header_like(row: List[Any]) -> bool:
        non_empty_cells = [c for c in row if str(c).strip()]
        if not non_empty_cells:
            return False
        numeric = sum(1 for c in non_empty_cells if str(c).replace(".", "").replace("-", "").isdigit())
        return numeric < len(non_empty_cells) / 2

    lines: List[str] = []
    if len(padded) > 1 and is_header_like(padded[0]):
        header = padded[0]
        lines.append("| " + " | ".join(str(c) for c in header) + " |")
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in padded[1:]:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
    else:
        for row in padded:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")

    table = "\n".join(lines)
    if truncated:
        table += f"\n\n_... {len(non_empty) - max_rows} more rows not shown. Use a smaller range._"
    return table


def read_range(spreadsheet_name: str, range_notation: str = "A1:Z100", sheet_tab: str = "Sheet1") -> Dict[str, Any]:
    """
    Read a range from the named spreadsheet.

    Args:
        spreadsheet_name: Human-readable name, e.g. "To-Do List"
        range_notation: A1 notation range, e.g. "A1:D20" (default reads first 100 rows)
        sheet_tab: Tab name within the spreadsheet (default: "Sheet1")

    Returns:
        {"status": "success", "values": [[...], ...], "row_count": N}
    """
    try:
        svc = _sheets_service()
        drive = _drive_service()

        spreadsheet_id = _find_spreadsheet_id(drive, spreadsheet_name)
        if not spreadsheet_id:
            return {"status": "error", "message": f"Spreadsheet '{spreadsheet_name}' not found in Google Drive."}

        full_range = f"{sheet_tab}!{range_notation}"
        result = (
            svc.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=full_range)
            .execute()
        )
        values = result.get("values", [])
        # 💎 Prism Protocol: convert raw 2D array → clean Markdown table
        table_md = _sanitize_sheet(values)
        return {
            "status":      "success",
            "spreadsheet": spreadsheet_name,
            "range":       full_range,
            "table":       table_md,
            "row_count":   len([r for r in values if any(str(c).strip() for c in r)]),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def create_sheet(title: str) -> Dict[str, Any]:
    """
    Create a new Google Spreadsheet with the given title.

    Args:
        title: The spreadsheet name, e.g. "Project X Budget"

    Returns:
        {"status": "success", "spreadsheet_id": "...", "url": "..."}
    """
    try:
        svc = _sheets_service()
        body = {"properties": {"title": title}}
        spreadsheet = svc.spreadsheets().create(body=body, fields="spreadsheetId").execute()
        sid = spreadsheet.get("spreadsheetId")
        return {
            "status": "success",
            "title": title,
            "spreadsheet_id": sid,
            "url": f"https://docs.google.com/spreadsheets/d/{sid}",
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_sheets(max_results: int = 20) -> Dict[str, Any]:
    """
    List the user's Google Spreadsheets from Drive.

    Args:
        max_results: Maximum number of sheets to return (default 20)

    Returns:
        {"status": "success", "sheets": [{"name": ..., "id": ..., "url": ...}, ...]}
    """
    try:
        drive = _drive_service()
        query = "mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
        results = (
            drive.files()
            .list(q=query, fields="files(id, name)", pageSize=max_results, orderBy="modifiedTime desc")
            .execute()
        )
        files = results.get("files", [])
        sheets = [
            {
                "name": f["name"],
                "id":   f["id"],
                "url":  f"https://docs.google.com/spreadsheets/d/{f['id']}",
            }
            for f in files
        ]
        return {"status": "success", "sheets": sheets, "count": len(sheets)}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def update_cell(spreadsheet_name: str, cell: str, value: Any, sheet_tab: str = "Sheet1") -> Dict[str, Any]:
    """
    Update a single cell in the named spreadsheet.

    Args:
        spreadsheet_name: Human-readable name, e.g. "Expenses 2026"
        cell: A1 notation, e.g. "B3"
        value: The new cell value
        sheet_tab: Tab name within the spreadsheet (default: "Sheet1")

    Returns:
        {"status": "success", "updated_cell": "...", "new_value": ...}
    """
    try:
        svc = _sheets_service()
        drive = _drive_service()

        spreadsheet_id = _find_spreadsheet_id(drive, spreadsheet_name)
        if not spreadsheet_id:
            return {"status": "error", "message": f"Spreadsheet '{spreadsheet_name}' not found in Google Drive."}

        full_range = f"{sheet_tab}!{cell}"
        body = {"values": [[value]]}
        result = (
            svc.spreadsheets()
            .values()
            .update(
                spreadsheetId=spreadsheet_id,
                range=full_range,
                valueInputOption="USER_ENTERED",
                body=body,
            )
            .execute()
        )
        return {
            "status": "success",
            "spreadsheet": spreadsheet_name,
            "updated_cell": full_range,
            "new_value": value,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
