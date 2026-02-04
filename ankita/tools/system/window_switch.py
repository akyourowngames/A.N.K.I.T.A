"""Adapter tool to call the `features.window_switch` feature.

This module provides a `run(args)` entrypoint compatible with the executor.
Args should include `query` (string).
"""
def run(args: dict) -> dict:
    query = args.get('query') or args.get('text') or ''
    try:
        from features.window_switch import handle_window_switch
    except Exception as e:
        return {'status': 'error', 'error': f'feature import failed: {e}'}

    res = handle_window_switch(query)
    return {'status': res.get('status'), 'result': res}
