import json
import sys
import time
import random
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from memory import get_memory_manager

from . import content_ops
from . import cron_ops
from . import deep_research as deep_research_mod
from . import desktop_ops
from . import fs_ops
from . import music_ops
from . import realtime_search
from . import system_ops
from . import terminal_ops
from . import sheets_ops
from . import youtube_ops
from . import figma_ops
from . import whatsapp_ops
from . import contacts_ops
from . import camera_ops
from . import app_manager
from . import voice_ops
from . import health_ops
from . import sync_ops
from . import maps_ops
from . import task_ops
from . import report_ops
from . import image_gen_ops
from . import autonomous_ops
from . import integration_hub
from . import cognitive_ops


from .specs import TOOL_SPECS  # noqa: F401 — schemas live in tools/specs.py


def _sim(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _match(token: str, choices: List[str], threshold: float = 0.78) -> bool:
    t = token.strip().lower()
    if not t:
        return False
    return any(t == c.lower() or _sim(t, c.lower()) >= threshold for c in choices)


def _tokenize(text: str) -> List[str]:
    cleaned = text
    for ch in ",.;:!?()[]{}<>|/\\\t\r\n":
        cleaned = cleaned.replace(ch, " ")
    return [t for t in cleaned.lower().split(" ") if t]


def _extract_quoted_text(text: str) -> Optional[str]:
    for q in ('"', "'"):
        start = text.find(q)
        if start == -1:
            continue
        end = text.find(q, start + 1)
        if end == -1:
            continue
        val = text[start + 1 : end].strip()
        if val:
            return val
    return None


def _normalize_human_path(raw: str) -> str:
    value = raw.strip().strip("\"'").lower()
    aliases = ["", ".", "this project", "project", "workspace", "this workspace", "here"]
    if any(_sim(value, alias) >= 0.76 for alias in aliases):
        return "."
    return raw.strip().strip("\"'")


def _call(name: str, args: Dict[str, Any], workspace_root: Path, agent_name: Optional[str] = None) -> Dict[str, Any]:
    # FileAgent gets unrestricted access to the entire PC
    unrestricted = (agent_name == "FileAgent")
    
    if name == "lookup_contact":
        return contacts_ops.lookup_contact(name=str(args.get("name", "")))

    if name == "add_contact":
        return contacts_ops.add_contact(
            name=str(args.get("name", "")),
            phone=str(args.get("phone", "")),
        )

    if name == "remove_contact":
        return contacts_ops.remove_contact(name=str(args.get("name", "")))

    if name == "list_contacts":
        return contacts_ops.list_contacts()

    if name == "send_whatsapp":
        return whatsapp_ops.send_whatsapp(
            phone=str(args.get("phone", "")),
            message=str(args.get("message", "")),
            wait=int(args.get("wait", 10)),
        )
    if name == "cron":
        return cron_ops.cron_action(
            workspace_root=workspace_root,
            action=str(args.get("action", "")),
            job=args.get("job") if isinstance(args.get("job"), dict) else None,
            job_id=str(args.get("job_id", "")) if args.get("job_id") is not None else None,
            patch=args.get("patch") if isinstance(args.get("patch"), dict) else None,
            include_disabled=bool(args.get("include_disabled", False)),
            mode=str(args.get("mode", "due")),
            limit=int(args.get("limit", 20)),
        )
    if name == "remember":
        mem = get_memory_manager(workspace_root)
        key = str(args.get("key", "")).strip()
        value = str(args.get("value", "")).strip()
        fact = str(args.get("fact", "")).strip()
        if not fact and key and value:
            fact = f"{key}: {value}"
        return mem.remember(
            fact=fact,
            interface=str(args.get("interface", "tool")),
        )
    if name == "recall":
        mem = get_memory_manager(workspace_root)
        rows = mem.recall(
            query=str(args.get("query", "")),
            limit=int(args.get("limit", 8)),
        )
        return {
            "kind": "memory_recall",
            "query": str(args.get("query", "")),
            "count": len(rows),
            "items": rows,
        }
    if name == "forget":
        mem = get_memory_manager(workspace_root)
        return mem.forget(
            query=str(args.get("query", "")),
            limit=int(args.get("limit", 20)),
        )
    if name == "search_web":
        return realtime_search.search_web(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "search_music":
        return music_ops.search_music(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
        )
    if name == "play_music":
        return music_ops.play_music(
            workspace_root=workspace_root,
            query=str(args.get("query", "")),
            headless=bool(args.get("headless", True)),
            stop_current=bool(args.get("stop_current", True)),
        )
    if name == "stop_music":
        return music_ops.stop_music(workspace_root=workspace_root)
    if name == "current_music":
        return music_ops.current_music(workspace_root=workspace_root)
    if name == "queue_music":
        return music_ops.queue_music(workspace_root=workspace_root, query=str(args.get("query", "")))
    if name == "show_queue":
        return music_ops.show_queue(workspace_root=workspace_root)
    if name == "clear_queue":
        return music_ops.clear_queue(workspace_root=workspace_root)
    if name == "play_next_in_queue":
        return music_ops.play_next_in_queue(workspace_root=workspace_root)
    if name == "pause_music":
        return music_ops.pause_music(workspace_root=workspace_root)
    if name == "resume_music":
        return music_ops.resume_music(workspace_root=workspace_root)
    if name == "music_volume":
        return music_ops.music_volume(workspace_root=workspace_root, level=int(args.get("level", 50)))
    if name == "system_control":
        return system_ops.system_control(
            action=str(args.get("action", "")),
            amount=int(args.get("amount", 1)),
            path=str(args.get("path")) if args.get("path") is not None else None,
            workspace_root=workspace_root,
        )
    if name == "search_price":
        return realtime_search.search_price(
            query=str(args.get("query", "")),
        )
    if name == "search_news":
        return realtime_search.search_news(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 8)),
            include_urls=bool(args.get("include_urls", False)),
        )
    if name == "fetch_page_content":
        return realtime_search.fetch_page_content(
            url=str(args.get("url", "")),
            max_chars=int(args.get("max_chars", 4000)),
        )
    if name == "deep_research":
        # runtime is injected via execute_tool_call._runtime by the Orchestrator
        _rt = getattr(execute_tool_call, "_runtime", None)
        return deep_research_mod.deep_research(
            topic=str(args.get("topic", "")),
            runtime=_rt,
        )
    if name == "search_and_fetch":
        return realtime_search.search_and_fetch(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
            fetch_top=int(args.get("fetch_top", 2)),
            max_chars_per_page=int(args.get("max_chars_per_page", 3000)),
        )
    if name == "terminate_app":
        return terminal_ops.terminate_app(
            app=str(args.get("app", "")),
            force=bool(args.get("force", False)),
        )
    if name == "launch_app":
        return terminal_ops.launch_app(
            workspace_root,
            app=str(args.get("app", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
        )
    if name == "execute_shell":
        return terminal_ops.execute_shell_command(
            command=str(args.get("command", "")),
            timeout=int(args.get("timeout")) if args.get("timeout") is not None else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
        )
    if name == "fast_file_search":
        return terminal_ops.fast_file_search(
            pattern=str(args.get("pattern", "")),
            path=str(args.get("path")) if args.get("path") is not None else None,
            glob=str(args.get("glob")) if args.get("glob") is not None else None,
            max_results=int(args.get("max_results", 50)),
            case_sensitive=bool(args.get("case_sensitive", False)),
        )
    if name == "run_command":
        env = args.get("env")
        env_obj = env if isinstance(env, dict) else None
        return terminal_ops.run_command(
            workspace_root,
            command=str(args.get("command", "")),
            args=[str(v) for v in (args.get("args") or [])] if isinstance(args.get("args"), list) else None,
            cwd=str(args.get("cwd")) if args.get("cwd") is not None else None,
            timeout_ms=int(args.get("timeout_ms", 20000)),
            use_shell=bool(args.get("use_shell", False)),
            env={str(k): str(v) for k, v in env_obj.items()} if env_obj is not None else None,
        )
    if name == "git_op":
        return terminal_ops.git_op(
            action=str(args.get("action", "")),
            message=str(args.get("message")) if args.get("message") else None,
            branch=str(args.get("branch")) if args.get("branch") else None,
            path=str(args.get("path")) if args.get("path") else None,
            confirm=bool(args.get("confirm", False)),
        )
    if name == "process_op":
        return terminal_ops.process_op(
            action=str(args.get("action", "")),
            command=str(args.get("command")) if args.get("command") else None,
            name=str(args.get("name")) if args.get("name") else None,
            port=int(args.get("port")) if args.get("port") is not None else None,
            pid=int(args.get("pid")) if args.get("pid") is not None else None,
        )

    # ── Autonomous Ops ────────────────────────────────────────────────────
    if name == "discover_tools":
        return autonomous_ops.discover_tools()
    if name == "auto_install_tool":
        return autonomous_ops.auto_install_tool(
            tool_name=str(args.get("tool_name", "")),
            prefer_manager=str(args.get("prefer_manager")) if args.get("prefer_manager") else None,
        )
    if name == "auto_install_python_package":
        return autonomous_ops.auto_install_python_package(
            package=str(args.get("package", "")),
        )
    if name == "generate_and_run_script":
        return autonomous_ops.generate_and_run_script(
            description=str(args.get("description", "")),
            language=str(args.get("language", "powershell")),
            script_content=str(args.get("script_content", "")),
            args=args.get("args"),
        )
    if name == "execute_pipeline":
        return autonomous_ops.execute_pipeline(
            steps=args.get("steps", []),
            stop_on_error=bool(args.get("stop_on_error", True)),
        )
    if name == "environment_setup":
        return autonomous_ops.environment_setup(
            project_type=str(args.get("project_type", "auto")),
            project_path=str(args.get("project_path")) if args.get("project_path") else None,
        )
    if name == "system_audit":
        return autonomous_ops.system_audit()
    if name == "execute_elevated":
        return terminal_ops.execute_elevated(
            command=str(args.get("command", "")),
            timeout=int(args.get("timeout", 120)),
        )
    if name == "chain_commands":
        return terminal_ops.chain_commands(
            commands=args.get("commands", []),
            mode=str(args.get("mode", "sequential")),
        )
    if name == "get_system_context":
        return terminal_ops.get_system_context()
    if name == "kill_process_tree":
        return terminal_ops.kill_process_tree(pid=int(args.get("pid", 0)))
    if name == "port_scan":
        return terminal_ops.port_scan(
            start=int(args.get("start", 1)),
            end=int(args.get("end", 1024)),
        )
    if name == "env_op":
        return terminal_ops.env_op(
            action=str(args.get("action", "")),
            name=str(args.get("name", "")),
            value=str(args.get("value", "")),
        )

    # ── Integration Hub ───────────────────────────────────────────────────
    if name == "github_op":
        return integration_hub.github_op(
            action=str(args.get("action", "")),
            repo=str(args.get("repo")) if args.get("repo") else None,
            title=str(args.get("title")) if args.get("title") else None,
            body=str(args.get("body")) if args.get("body") else None,
            branch=str(args.get("branch")) if args.get("branch") else None,
            label=str(args.get("label")) if args.get("label") else None,
            query=str(args.get("query")) if args.get("query") else None,
            number=int(args.get("number")) if args.get("number") is not None else None,
            path=str(args.get("path")) if args.get("path") else None,
            extra_args=str(args.get("extra_args")) if args.get("extra_args") else None,
        )
    if name == "docker_op":
        return integration_hub.docker_op(
            action=str(args.get("action", "")),
            image=str(args.get("image")) if args.get("image") else None,
            container=str(args.get("container")) if args.get("container") else None,
            command=str(args.get("command")) if args.get("command") else None,
            ports=str(args.get("ports")) if args.get("ports") else None,
            volumes=str(args.get("volumes")) if args.get("volumes") else None,
            env_vars=args.get("env_vars") if isinstance(args.get("env_vars"), dict) else None,
            compose_file=str(args.get("compose_file")) if args.get("compose_file") else None,
            extra_args=str(args.get("extra_args")) if args.get("extra_args") else None,
        )
    if name == "ssh_op":
        return integration_hub.ssh_op(
            action=str(args.get("action", "")),
            host=str(args.get("host")) if args.get("host") else None,
            command=str(args.get("command")) if args.get("command") else None,
            user=str(args.get("user")) if args.get("user") else None,
            key_path=str(args.get("key_path")) if args.get("key_path") else None,
            port=int(args.get("port", 22)),
            local_path=str(args.get("local_path")) if args.get("local_path") else None,
            remote_path=str(args.get("remote_path")) if args.get("remote_path") else None,
        )
    if name == "api_test":
        return integration_hub.api_test(
            method=str(args.get("method", "GET")),
            url=str(args.get("url", "")),
            headers=args.get("headers") if isinstance(args.get("headers"), dict) else None,
            body=str(args.get("body")) if args.get("body") else None,
            auth=str(args.get("auth")) if args.get("auth") else None,
            timeout=int(args.get("timeout", 30)),
        )
    if name == "db_query":
        return integration_hub.db_query(
            engine=str(args.get("engine", "")),
            query=str(args.get("query", "")),
            database=str(args.get("database")) if args.get("database") else None,
            host=str(args.get("host")) if args.get("host") else None,
            port=int(args.get("port")) if args.get("port") is not None else None,
            user=str(args.get("user")) if args.get("user") else None,
            password=str(args.get("password")) if args.get("password") else None,
        )
    if name == "service_op":
        return integration_hub.service_op(
            action=str(args.get("action", "")),
            name=str(args.get("name")) if args.get("name") else None,
            command=str(args.get("command")) if args.get("command") else None,
            schedule=str(args.get("schedule")) if args.get("schedule") else None,
        )

    # ── Cognitive Ops ─────────────────────────────────────────────────────
    if name == "resolve_error":
        return cognitive_ops.resolve_error(
            error_text=str(args.get("error_text", "")),
            command=str(args.get("command", "")),
            context=str(args.get("context", "")),
        )
    if name == "smart_retry":
        return cognitive_ops.smart_retry(
            command=str(args.get("command", "")),
            max_retries=int(args.get("max_retries", 3)),
            timeout=int(args.get("timeout", 60)),
            cwd=str(args.get("cwd")) if args.get("cwd") else None,
            auto_fix=bool(args.get("auto_fix", True)),
        )
    if name == "workspace_scan":
        return cognitive_ops.workspace_scan(
            path=str(args.get("path")) if args.get("path") else None,
        )
    if name == "plan_and_execute":
        return cognitive_ops.plan_and_execute(
            goal=str(args.get("goal", "")),
            steps=args.get("steps", []),
            stop_on_error=bool(args.get("stop_on_error", False)),
            verify_command=str(args.get("verify_command")) if args.get("verify_command") else None,
            cwd=str(args.get("cwd")) if args.get("cwd") else None,
        )
    if name == "code_analysis":
        return cognitive_ops.code_analysis(
            path=str(args.get("path", ".")),
            focus=str(args.get("focus", "all")),
        )
    if name == "project_scaffold":
        return cognitive_ops.project_scaffold(
            template=str(args.get("template", "")),
            name=str(args.get("name", "")),
            path=str(args.get("path")) if args.get("path") else None,
            auto_setup=bool(args.get("auto_setup", True)),
        )
    if name == "self_extend":
        return cognitive_ops.self_extend(
            name=str(args.get("name", "")),
            description=str(args.get("description", "")),
            code=str(args.get("code", "")),
        )
    if name == "execute_extension":
        return cognitive_ops.execute_extension(
            name=str(args.get("name", "")),
            args=args.get("args") if isinstance(args.get("args"), dict) else None,
        )
    if name == "process_watch":
        return cognitive_ops.process_watch(
            command=str(args.get("command", "")),
            duration=int(args.get("duration", 60)),
            success_pattern=str(args.get("success_pattern")) if args.get("success_pattern") else None,
            failure_pattern=str(args.get("failure_pattern")) if args.get("failure_pattern") else None,
            capture_last=int(args.get("capture_last", 50)),
        )
    if name == "translate_command":
        return cognitive_ops.translate_command(
            command=str(args.get("command", "")),
            from_platform=str(args.get("from_platform", "linux")),
            to_platform=str(args.get("to_platform")) if args.get("to_platform") else None,
        )
    if name == "list_extensions":
        return cognitive_ops.list_extensions()

    if name == "list_files":
        return fs_ops.list_files(workspace_root, path=str(args.get("path", ".")), max_entries=int(args.get("max_entries", 200)), unrestricted=unrestricted)
    if name == "read_file":
        return fs_ops.read_file(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "read_rich_file":
        return fs_ops.read_rich_file(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "search_text":
        return fs_ops.search_text(
            workspace_root,
            query=str(args.get("query", "")),
            path=str(args.get("path", ".")),
            max_results=int(args.get("max_results", 100)),
            unrestricted=unrestricted,
        )
    if name == "write_file":
        return fs_ops.write_file(
            workspace_root,
            path=str(args.get("path", "")),
            content=str(args.get("content", "")),
            overwrite=bool(args.get("overwrite", True)),
        )
    if name == "edit_file":
        return fs_ops.edit_file(
            workspace_root,
            path=str(args.get("path", "")),
            old_text=str(args.get("old_text", "")),
            new_text=str(args.get("new_text", "")),
            replace_all=bool(args.get("replace_all", False)),
        )
    if name == "rename_path":
        return fs_ops.rename_path(
            workspace_root,
            path=str(args.get("path", "")),
            new_name=str(args.get("new_name", "")),
            overwrite=bool(args.get("overwrite", False)),
        )
    if name == "delete_path":
        return fs_ops.delete_path(
            workspace_root,
            path=str(args.get("path", "")),
            recursive=bool(args.get("recursive", False)),
            missing_ok=bool(args.get("missing_ok", False)),
            unrestricted=unrestricted,
        )
    if name == "move_path":
        return fs_ops.move_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            unrestricted=unrestricted,
        )
    if name == "copy_path":
        return fs_ops.copy_path(
            workspace_root,
            src=str(args.get("src", "")),
            dst=str(args.get("dst", "")),
            overwrite=bool(args.get("overwrite", False)),
            recursive=bool(args.get("recursive", False)),
            unrestricted=unrestricted,
        )
    if name == "make_dir":
        return fs_ops.make_dir(
            workspace_root,
            path=str(args.get("path", "")),
            parents=bool(args.get("parents", True)),
            exist_ok=bool(args.get("exist_ok", True)),
            unrestricted=unrestricted,
        )
    if name == "file_info":
        return fs_ops.file_info(workspace_root, path=str(args.get("path", "")), unrestricted=unrestricted)
    if name == "pc_search":
        return fs_ops.pc_search(
            query=str(args.get("query", "")),
            file_types=args.get("file_types"),
            max_results=int(args.get("max_results", 50)),
        )
    if name == "trash_path":
        return fs_ops.trash_path(
            workspace_root,
            path=str(args.get("path", "")),
            unrestricted=unrestricted,
        )
    if name == "disk_analysis":
        return fs_ops.disk_analysis(
            workspace_root,
            path=str(args.get("path", ".")),
            unrestricted=unrestricted,
        )
    if name == "diff_files":
        return fs_ops.diff_files(
            workspace_root,
            file1=str(args.get("file1", "")),
            file2=str(args.get("file2", "")),
            unrestricted=unrestricted,
        )
    if name == "bulk_op":
        return fs_ops.bulk_op(
            workspace_root,
            operation=str(args.get("operation", "")),
            paths=args.get("paths", []),
            destination=str(args.get("destination")) if args.get("destination") else None,
            unrestricted=unrestricted,
        )
    if name == "desktop_interact":
        return desktop_ops.desktop_interact(
            action=str(args.get("action", "")),
            text=str(args.get("text", "")),
            focus=str(args["focus"]) if args.get("focus") else None,
        )
    if name == "check_syntax":
        return fs_ops.check_syntax(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
        )
    if name == "read_file_lines":
        return fs_ops.read_file_lines(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
            start_line=int(args.get("start_line", 1)),
            end_line=int(args.get("end_line", 1)),
        )
    if name == "edit_file_lines":
        return fs_ops.edit_file_lines(
            workspace_root=workspace_root,
            path=str(args.get("file_path", "")),
            start_line=int(args.get("start_line", 1)),
            end_line=int(args.get("end_line", 1)),
            new_content=str(args.get("new_content", "")),
        )
    if name == "apply_patch":
        return fs_ops.apply_patch(workspace_root, patch=str(args.get("patch", "")))
    if name == "capture_webcam":
        return desktop_ops.capture_webcam(
            camera_index=int(args.get("camera_index", 0)),
            save_path=str(args.get("save_path")) if args.get("save_path") else None,
        )
    if name == "download_file":
        return realtime_search.download_file(
            url=str(args.get("url", "")),
            save_folder=str(args.get("save_folder")) if args.get("save_folder") else None,
        )
    if name == "scrape_structured":
        return realtime_search.scrape_structured(
            url=str(args.get("url", "")),
            extract=str(args.get("extract", "tables")),
        )
    if name == "compare_search":
        return realtime_search.compare_search(
            item_a=str(args.get("item_a", "")),
            item_b=str(args.get("item_b", "")),
            aspects=args.get("aspects"),
        )
    if name == "web_monitor":
        return realtime_search.web_monitor(
            action=str(args.get("action", "")),
            url=str(args.get("url")) if args.get("url") else None,
            keyword=str(args.get("keyword")) if args.get("keyword") else None,
            label=str(args.get("label")) if args.get("label") else None,
        )
    if name == "multi_search":
        return realtime_search.multi_search(
            queries=args.get("queries", []),
            fetch_top=int(args.get("fetch_top", 2)),
        )
    if name == "fact_check":
        return realtime_search.fact_check(
            claim=str(args.get("claim", "")),
            sources=int(args.get("sources", 4)),
        )
    if name == "search_reddit":
        return realtime_search.search_reddit(
            query=str(args.get("query", "")),
            subreddit=str(args.get("subreddit")) if args.get("subreddit") else None,
            max_posts=int(args.get("max_posts", 5)),
        )
    if name == "search_stackoverflow":
        return realtime_search.search_stackoverflow(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
        )
    if name == "image_search":
        return realtime_search.image_search(
            query=str(args.get("query", "")),
            max_results=int(args.get("max_results", 5)),
            download=bool(args.get("download", False)),
        )
    if name == "summarise_url":
        return realtime_search.summarise_url(
            url=str(args.get("url", "")),
            style=str(args.get("style", "bullets")),
            max_bullets=int(args.get("max_bullets", 7)),
        )
    if name == "trending_topics":
        return realtime_search.trending_topics(
            category=str(args.get("category", "general")),
            region=str(args.get("region", "US")),
        )
    if name == "web_to_dataset":
        return realtime_search.web_to_dataset(
            query=str(args.get("query", "")),
            columns=args.get("columns"),
            max_rows=int(args.get("max_rows", 20)),
            output_format=str(args.get("output_format", "json")),
        )
    if name == "write_content":
        return content_ops.write_and_save_content(
            workspace_root=workspace_root,
            topic=str(args.get("topic", "")),
            format_type=str(args.get("format_type", "content")),
            extra_context=str(args.get("extra_context", "")),
            output_dir=str(args.get("output_dir")) if args.get("output_dir") else None,
        )
    if name == "capture_screen":
        return desktop_ops.capture_screen(
            monitor=int(args.get("monitor", 1)),
            save_path=str(args.get("save_path")) if args.get("save_path") else None,
        )
    if name == "read_screen_context":
        return desktop_ops.read_screen_context(
            image_path=str(args.get("image_path", "")),
        )
    if name == "visual_click":
        # visual_click needs the LLMRuntime — retrieve it from the global agent context if available
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return desktop_ops.visual_click(
            target_description=str(args.get("target_description", "")),
            runtime=_runtime,
            screenshot_path=str(args.get("screenshot_path")) if args.get("screenshot_path") else None,
        )
    # ── Google Sheets ──────────────────────────────────────────────────────────
    if name == "sheets_op":
        action = str(args.get("action", ""))
        if action == "append_row":
            return sheets_ops.append_row(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                data=args.get("data", []),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        if action == "read_range":
            return sheets_ops.read_range(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                range_notation=str(args.get("range_notation", "A1:Z100")),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        if action == "create_sheet":
            return sheets_ops.create_sheet(title=str(args.get("title", "")))
        if action == "list_sheets":
            return sheets_ops.list_sheets(max_results=int(args.get("max_results", 20)))
        if action == "update_cell":
            return sheets_ops.update_cell(
                spreadsheet_name=str(args.get("spreadsheet_name", "")),
                cell=str(args.get("cell", "A1")),
                value=args.get("value", ""),
                sheet_tab=str(args.get("sheet_tab", "Sheet1")),
            )
        return {"status": "error", "message": f"Unknown sheets_op action: {action}"}

    # ── YouTube ────────────────────────────────────────────────────────────────
    if name == "youtube_op":
        action = str(args.get("action", ""))
        if action == "get_subscriptions":
            return youtube_ops.get_subscriptions(max_results=int(args.get("max_results", 20)))
        if action == "search_channel_videos":
            return youtube_ops.search_channel_videos(
                channel_name=str(args.get("channel_name", "")),
                query=str(args.get("query", "")),
                max_results=int(args.get("max_results", 10)),
            )
        if action == "create_playlist":
            return youtube_ops.create_playlist(
                name=str(args.get("name", "")),
                description=str(args.get("description", "")),
                video_ids=args.get("video_ids") if isinstance(args.get("video_ids"), list) else None,
            )
        if action == "list_playlists":
            return youtube_ops.list_playlists(max_results=int(args.get("max_results", 20)))
        if action == "add_to_playlist":
            return youtube_ops.add_to_playlist(
                playlist_id=str(args.get("playlist_id", "")),
                video_id=str(args.get("video_id", "")),
            )
        return {"status": "error", "message": f"Unknown youtube_op action: {action}"}

    # ── Figma ──────────────────────────────────────────────────────────────────
    if name == "figma_op":
        action = str(args.get("action", ""))
        if action == "list_projects":
            return figma_ops.list_projects(team_id=str(args.get("team_id", "")))
        if action == "list_files":
            return figma_ops.list_files(project_id=str(args.get("project_id", "")))
        if action == "read_comments":
            return figma_ops.read_comments(file_key=str(args.get("file_key", "")))
        if action == "post_comment":
            return figma_ops.post_comment(
                file_key=str(args.get("file_key", "")),
                message=str(args.get("message", "")),
                node_id=str(args.get("node_id")) if args.get("node_id") else None,
            )
        if action == "get_node_properties":
            return figma_ops.get_node_properties(
                file_key=str(args.get("file_key", "")),
                node_ids=str(args.get("node_ids", "")),
            )
        if action == "get_file_info":
            return figma_ops.get_file_info(file_key=str(args.get("file_key", "")))
        return {"status": "error", "message": f"Unknown figma_op action: {action}"}

    # ── New Tools with LLM Integration ────────────────────────────────────────
    if name == "camera_control":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return camera_ops.camera_control(
            action=str(args.get("action", "")),
            runtime=_runtime,
            count=int(args.get("count", 5)),
            interval=float(args.get("interval", 2.0)),
            duration=int(args.get("duration", 10)),
            timeout=int(args.get("timeout", 5)),
        )
    
    if name == "app_manager":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return app_manager.app_manager(
            action=str(args.get("action", "")),
            runtime=_runtime,
            name=str(args.get("name", "")),
            force=bool(args.get("force", False)),
        )
    
    if name == "voice_control":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return voice_ops.voice_control(
            action=str(args.get("action", "")),
            runtime=_runtime,
            text=str(args.get("text", "")),
            rate=int(args.get("rate", 150)),
            volume=int(args.get("volume", 100)),
            emotion=str(args.get("emotion", "neutral")),
        )
    
    if name == "system_health":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return health_ops.system_health(
            action=str(args.get("action", "")),
            runtime=_runtime,
            n=int(args.get("n", 5)),
            sort_by=str(args.get("sort_by", "cpu")),
        )
    
    if name == "file_sync":
        _runtime = getattr(execute_tool_call, "_runtime", None)
        return sync_ops.file_sync(
            action=str(args.get("action", "")),
            runtime=_runtime,
            folder_path=str(args.get("folder_path") or args.get("path") or ""),
            source=str(args.get("source", "")),
            destination=str(args.get("destination")) if args.get("destination") else None,
            directory=str(args.get("directory") or args.get("path") or ""),
            dry_run=bool(args.get("dry_run", True)),
        )
    
    if name == "window_layout":
        return system_ops.window_layout(
            action=str(args.get("action", "")),
        )
    
    if name == "maps_op":
        return maps_ops.maps_op(
            action=str(args.get("action", "")),
            origin=str(args.get("origin")) if args.get("origin") else None,
            destination=str(args.get("destination")) if args.get("destination") else None,
            query=str(args.get("query")) if args.get("query") else None,
            mode=str(args.get("mode", "driving")),
        )
    
    if name == "task_op":
        return task_ops.task_op(
            action=str(args.get("action", "")),
            title=str(args.get("title")) if args.get("title") else None,
            priority=str(args.get("priority", "medium")),
            deadline=str(args.get("deadline")) if args.get("deadline") else None,
            tags=args.get("tags") if isinstance(args.get("tags"), list) else None,
            status=str(args.get("status", "pending")),
            task_id=str(args.get("task_id")) if args.get("task_id") else None,
        )
    
    if name == "generate_pdf":
        return report_ops.generate_pdf(
            title=str(args.get("title", "")),
            sections=args.get("sections", []),
            output_path=str(args.get("output_path")) if args.get("output_path") else None,
            format=str(args.get("format", "pdf")),
        )

    if name == "generate_image":
        return image_gen_ops.generate_image(
            prompt=str(args.get("prompt", "")),
            width=int(args.get("width", 1024)),
            height=int(args.get("height", 1024)),
            model=str(args.get("model", "flux")),
            output_path=str(args.get("output_path")) if args.get("output_path") else None,
        )

    raise ValueError(f"Unknown tool: {name}")


# ── PRISM PROTOCOL v2 — Adaptive Tool Result Budget (OpenClaw-inspired) ──────
# OpenClaw uses HARD_MAX_TOOL_RESULT_CHARS = 50,000 with proportional truncation.
# ANKITA's context is tighter (Copilot 64k limit) so we use a tiered budget:
#   - Tier 1: 12,000 chars (~3k tokens) — default for most tools
#   - Tier 2: 25,000 chars (~6k tokens) — for heavy tools (search, file reads, research)
#   - Tier 3: 50,000 chars (~12k tokens) — for deep research only
_HARD_CAP_DEFAULT = 12_000
_HARD_CAP_HEAVY   = 25_000
_HARD_CAP_DEEP    = 50_000
_HARD_CAP_MSG     = "\n... [TRUNCATED — ask for a smaller range or more specific query]"

# Tools that produce large outputs and benefit from higher budgets
_HEAVY_RESULT_TOOLS = frozenset({
    "search_web", "search_news", "search_price", "fetch_page_content",
    "read_file", "read_file_lines", "read_rich_file", "list_files",
    "search_text", "execute_shell", "pc_search", "disk_analysis",
    "search_and_fetch", "workspace_scan", "deep_research",
})
_DEEP_RESULT_TOOLS = frozenset({
    "deep_research", "workspace_scan",
})


def _get_tool_budget(tool_name: str = "") -> int:
    """Return the char budget for a specific tool."""
    if tool_name in _DEEP_RESULT_TOOLS:
        return _HARD_CAP_DEEP
    if tool_name in _HEAVY_RESULT_TOOLS:
        return _HARD_CAP_HEAVY
    return _HARD_CAP_DEFAULT


def _hard_cap(result: Any, tool_name: str = "") -> Any:
    """
    Prism Protocol v2 — Adaptive Token Budget Guard 💎

    OpenClaw-inspired proportional truncation:
    - Tool budget is dynamic based on tool type (default 12k, heavy 25k, deep 50k)
    - Vision results (base64) pass through untouched
    - Dict/list results: JSON-serialise, check budget, truncate if needed
    - String results: direct char check

    This replaces the old flat 3000-char cap that caused 30% information loss.
    """
    cap = _get_tool_budget(tool_name)

    if isinstance(result, dict):
        # VISION EXCEPTION: preserve base64 fields from truncation
        if "base64" in result:
            return result
        _inner = result.get("result", {})
        if isinstance(_inner, dict) and "base64" in _inner:
            return result

        serialised = json.dumps(result, ensure_ascii=False)
        if len(serialised) <= cap:
            return result
        truncated = serialised[:cap] + _HARD_CAP_MSG
        return {"status": "truncated", "data": truncated}
    if isinstance(result, list):
        serialised = json.dumps(result, ensure_ascii=False)
        if len(serialised) <= cap:
            return result
        truncated = serialised[:cap] + _HARD_CAP_MSG
        return {"status": "truncated", "data": truncated}
    if isinstance(result, str) and len(result) > cap:
        return result[:cap] + _HARD_CAP_MSG
    return result


# ── Error Classification (OpenClaw-inspired) ────────────────────────────────
# OpenClaw classifies errors into categories (auth, billing, rate_limit,
# context_overflow, transient, etc.) and handles each differently.
# ANKITA mirrors this with a classify → enrich → hint pipeline.

def _classify_error(error: str) -> str:
    """Classify an error into a category for routing recovery actions.

    Categories: auth, billing, rate_limit, context_overflow, permission,
    missing_dep, network, timeout, not_found, parse, unknown
    """
    e = error.lower()
    if any(k in e for k in ("401", "403", "unauthorized", "authentication", "invalid api key")):
        return "auth"
    if any(k in e for k in ("402", "billing", "quota", "subscription", "payment")):
        return "billing"
    if any(k in e for k in ("429", "rate limit", "too many requests", "throttl")):
        return "rate_limit"
    if any(k in e for k in ("context_length", "too large", "maximum context", "token limit")):
        return "context_overflow"
    if any(k in e for k in ("permission", "access denied", "denied", "forbidden")):
        return "permission"
    if any(k in e for k in ("modulenotfounderror", "no module named", "importerror", "not recognized")):
        return "missing_dep"
    if any(k in e for k in ("connection", "network", "dns", "unreachable", "socket")):
        return "network"
    if any(k in e for k in ("timeout", "timed out", "deadline exceeded")):
        return "timeout"
    if any(k in e for k in ("not found", "no such file", "does not exist", "filenotfounderror")):
        return "not_found"
    if any(k in e for k in ("json", "decode", "parse", "syntax")):
        return "parse"
    return "unknown"


def _enrich_error(name: str, error: str) -> str:
    """Add actionable recovery hints to tool errors for the LLM.

    Uses OpenClaw-style error classification to provide targeted recovery paths.
    """
    category = _classify_error(error)
    _CATEGORY_HINTS = {
        "auth": "API key invalid or expired. Check .env credentials.",
        "billing": "Billing/quota issue. Switch providers or check subscription.",
        "rate_limit": "Rate limited. Wait a moment and retry, or use smart_retry().",
        "context_overflow": "Context too large. Compact messages or use smaller queries.",
        "permission": "Try: execute_elevated() or smart_retry() with auto_fix=True",
        "missing_dep": "Try: auto_install_python_package() or smart_retry() which auto-installs",
        "network": "Network issue. Check connectivity or use resolve_error() for diagnosis",
        "timeout": "Increase timeout or try: smart_retry() which handles retries adaptively",
        "not_found": "Check path exists. Try: list_files() to verify, or make_dir() first",
        "parse": "Invalid JSON/syntax in args. Re-check the arguments format carefully",
        "unknown": "Try: resolve_error(error_text=<this error>) for diagnosis and fixes",
    }
    hint = _CATEGORY_HINTS.get(category, _CATEGORY_HINTS["unknown"])
    return f"{error} | ERROR_CLASS: {category} | HINT: {hint}"


# ── OpenClaw-pattern: transient error detection ─────────────────────────────
_TRANSIENT_CATEGORIES = frozenset({"rate_limit", "network", "timeout"})

# Tools that are safe to auto-retry (idempotent or read-only)
_SAFE_TO_RETRY = frozenset({
    "search_web", "search_news", "search_price", "search_and_fetch",
    "fetch_page_content", "search_music", "read_file", "read_file_lines",
    "list_files", "file_info", "search_text", "recall", "lookup_contact",
    "list_contacts", "current_music", "show_queue", "discover_tools",
    "workspace_scan", "code_analysis", "process_op", "git_op",
    "fast_file_search", "pc_search", "disk_analysis", "diff_files",
    "sheets_op", "youtube_op", "figma_op", "maps_op", "image_search",
    "search_reddit", "search_stackoverflow", "trending_topics",
    "summarise_url", "deep_research", "compare_search", "multi_search",
    "fact_check", "get_system_context",
})

# Tools that modify state — retry only on transient errors, with caution
_WRITE_TOOLS_RETRY_ON_TRANSIENT = frozenset({
    "write_file", "edit_file", "edit_file_lines", "execute_shell",
    "run_command", "send_whatsapp", "remember", "apply_patch",
    "generate_and_run_script", "execute_pipeline",
})

# ── Execution metrics (OpenClaw-inspired) ───────────────────────────────────
_tool_metrics: Dict[str, Dict[str, Any]] = {}

def get_tool_metrics() -> Dict[str, Dict[str, Any]]:
    """Return tool execution stats: success rate, avg latency, failure count."""
    return dict(_tool_metrics)

def _record_metric(tool_name: str, success: bool, latency_ms: float):
    if tool_name not in _tool_metrics:
        _tool_metrics[tool_name] = {"calls": 0, "success": 0, "fail": 0, "total_ms": 0.0}
    m = _tool_metrics[tool_name]
    m["calls"] += 1
    m["total_ms"] += latency_ms
    if success:
        m["success"] += 1
    else:
        m["fail"] += 1


def _is_retryable(error_str: str, tool_name: str) -> bool:
    """Determine if a tool error is worth retrying (OpenClaw failover logic)."""
    cat = _classify_error(error_str)
    if cat in _TRANSIENT_CATEGORIES:
        return tool_name in _SAFE_TO_RETRY or tool_name in _WRITE_TOOLS_RETRY_ON_TRANSIENT
    # Missing dep: auto-install then retry
    if cat == "missing_dep":
        return True
    return False


def _auto_recover(error_str: str, tool_name: str, args: Dict[str, Any], workspace_root: Path) -> Optional[Dict[str, Any]]:
    """
    OpenClaw-pattern: attempt automatic recovery before giving up.
    Returns a successful result dict if recovery works, None otherwise.
    """
    cat = _classify_error(error_str)

    # Auto-install missing Python packages and retry
    if cat == "missing_dep":
        import re
        # Extract module name from "No module named 'xyz'" or "ModuleNotFoundError: No module named 'xyz'"
        match = re.search(r"no module named ['\"]?(\w+)", error_str.lower())
        if match:
            pkg = match.group(1)
            print(f"[AutoRecover] 📦 Missing module '{pkg}' — auto-installing…", flush=True)
            try:
                from . import autonomous_ops
                install_result = autonomous_ops.auto_install_python_package(package=pkg)
                if install_result.get("ok") or install_result.get("installed"):
                    print(f"[AutoRecover] ✅ Installed '{pkg}', retrying tool…", flush=True)
                    # Retry the original call
                    result = _call(tool_name, args, workspace_root)
                    return {"ok": True, "tool": tool_name, "result": _hard_cap(result, tool_name=tool_name),
                            "auto_recovered": f"installed_{pkg}"}
            except Exception as recovery_err:
                print(f"[AutoRecover] ❌ Install failed: {recovery_err}", flush=True)

    # Permission errors on file ops: try elevated
    if cat == "permission" and tool_name in ("write_file", "edit_file", "delete_path", "move_path", "copy_path"):
        print(f"[AutoRecover] 🔑 Permission denied on {tool_name} — trying elevated…", flush=True)
        try:
            from . import terminal_ops
            # Build a PowerShell equivalent command
            if tool_name == "write_file" and "path" in args and "content" in args:
                cmd = f'Set-Content -Path "{args["path"]}" -Value @"\n{args.get("content", "")}\n"@ -Force'
                result = terminal_ops.execute_shell_command(command=cmd, timeout=10)
                if result.get("exit_code", 1) == 0:
                    return {"ok": True, "tool": tool_name, "result": {"written": args["path"]},
                            "auto_recovered": "elevated_write"}
        except Exception:
            pass

    return None


def execute_tool_call(tool_call: Dict[str, Any], workspace_root: Path, agent_name: Optional[str] = None) -> Dict[str, Any]:
    """
    Execute a tool call with OpenClaw-pattern resilience:
    1. Parse & validate args
    2. Execute with automatic retry + exponential backoff for transient errors
    3. Auto-recover from known failure patterns (missing deps, permissions)
    4. Track execution metrics
    """
    fn = tool_call.get("function", {})
    name = str(fn.get("name", ""))
    raw_args = fn.get("arguments", "{}")

    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
    except json.JSONDecodeError as err:
        raise ValueError(f"Invalid JSON args for {name}: {err}") from err

    if not isinstance(args, dict):
        raise ValueError(f"Tool args must be an object for {name}")

    # ── OpenClaw-pattern: retry loop with exponential backoff ────────────
    _MAX_RETRIES = 3
    last_error = None
    t0 = time.monotonic()

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            result = _call(name, args, workspace_root, agent_name=agent_name)
            latency = (time.monotonic() - t0) * 1000
            _record_metric(name, True, latency)

            # 💎 Prism Protocol v2: adaptive tool-result budget
            result = _hard_cap(result, tool_name=name)
            # If the tool itself returned an error dict, enrich it
            if isinstance(result, dict) and result.get("ok") is False and "error" in result:
                result["error"] = _enrich_error(name, str(result["error"]))
                # Even "soft" error results get metric tracking
                _record_metric(name, False, latency)

            out = {"ok": True, "tool": name, "result": result}
            if attempt > 1:
                out["retries"] = attempt - 1
            return out

        except Exception as exc:
            last_error = str(exc)
            error_cat = _classify_error(last_error)

            # Check if retryable and we have attempts left
            if attempt < _MAX_RETRIES and _is_retryable(last_error, name):
                # Exponential backoff with jitter (OpenClaw pattern)
                backoff = min(2 ** attempt + random.uniform(0, 1), 15)
                print(f"[RetryEngine] ⚡ {name} failed (attempt {attempt}/{_MAX_RETRIES}, "
                      f"cat={error_cat}): {last_error[:100]}… retrying in {backoff:.1f}s", flush=True)
                time.sleep(backoff)
                continue

            # Not retryable or out of attempts — try auto-recovery
            recovery = _auto_recover(last_error, name, args, workspace_root)
            if recovery is not None:
                latency = (time.monotonic() - t0) * 1000
                _record_metric(name, True, latency)
                return recovery

            # Final failure
            latency = (time.monotonic() - t0) * 1000
            _record_metric(name, False, latency)
            enriched = _enrich_error(name, last_error)
            out = {"ok": False, "tool": name, "error": enriched}
            if attempt > 1:
                out["retries"] = attempt - 1
            return out

    # Should never reach here, but safety net
    latency = (time.monotonic() - t0) * 1000
    _record_metric(name, False, latency)
    return {"ok": False, "tool": name, "error": _enrich_error(name, last_error or "Unknown error")}


def select_tools_for_user_text(user_text: str) -> List[Dict[str, Any]]:
    """
    LLM-powered tool selector — replaces brittle keyword matching.
    Asks the LLM which tools are needed for the user's request.
    Falls back to all tools on error.
    """
    try:
        from llm import build_runtime_from_env, call_chat_once
        
        # Build a compact tool list for the LLM
        tool_names = [spec["function"]["name"] for spec in TOOL_SPECS]
        tool_descriptions = {
            spec["function"]["name"]: spec["function"]["description"]
            for spec in TOOL_SPECS
        }
        
        system_prompt = f"""You are ANKITA's Tool Selector. Your job is to identify which tools are needed for a user request.

Available tools:
{json.dumps(tool_descriptions, indent=2)}

Analyze the user request and return ONLY the tool names needed (as a JSON array of strings).
If multiple tools might be needed, include all relevant ones.
If unsure, include tools that might be useful.

Respond ONLY with valid JSON array. No explanation. No markdown.
["tool_name1", "tool_name2", ...]"""

        runtime = build_runtime_from_env()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        
        response = call_chat_once(runtime, messages, tools=None, max_tokens=200)
        raw = (response.get("content") or "").strip()
        
        # Parse JSON — strip fences if present
        clean = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        selected_names = json.loads(clean)
        
        if not isinstance(selected_names, list):
            raise ValueError("LLM response is not a list")
        
        # Filter TOOL_SPECS to only include selected tools
        selected_tools = [
            spec for spec in TOOL_SPECS 
            if spec["function"]["name"] in selected_names
        ]
        
        if selected_tools:
            print(f"[ToolSelector] Selected {len(selected_tools)} tools: {[s['function']['name'] for s in selected_tools]}", flush=True)
            return selected_tools
        
        # If no tools selected, return all (safe fallback)
        print(f"[ToolSelector] No tools selected, returning all", flush=True)
        return TOOL_SPECS
        
    except Exception as e:
        print(f"[ToolSelector] ⚠️ LLM selection failed: {e} — returning all tools", flush=True)
        return TOOL_SPECS


def _format_result(result: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("kind") == "music_search":
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Music search for '{result.get('query', '')}'", "Top matches:"]
        for i, row in enumerate(rows[:8], 1):
            if not isinstance(row, dict):
                continue
            lines.append(f"{i}. {row.get('title', '')} (score={row.get('score', 0)})")
            lines.append(f"   {row.get('domain', '')}")
        best = result.get("best_match")
        if isinstance(best, dict):
            lines.append(f"Best match: {best.get('title', '')} (score={best.get('score', 0)})")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "music_play":
        return (
            f"[MUSIC PLAYING]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"score: {result.get('score', 0)}\n"
            f"headless: {bool(result.get('headless', True))}"
        )

    if isinstance(result, dict) and result.get("kind") == "music_stop":
        if bool(result.get("stopped")):
            return f"[MUSIC STOPPED] pid={result.get('pid', '')}"
        return f"[MUSIC STOP] no active player ({result.get('reason', 'unknown')})"

    if isinstance(result, dict) and result.get("kind") == "music_queue_add":
        added = result.get("added", {})
        return (
            f"[QUEUED] #{result.get('position', '?')} — {added.get('title', '')}\n"
            f"Queue length: {result.get('queue_length', 0)}"
        )

    if isinstance(result, dict) and result.get("kind") == "music_queue_show":
        queue = result.get("queue", [])
        if not queue:
            return "Music queue is empty."
        lines = [f"Music Queue ({len(queue)} track(s)):"]
        for i, track in enumerate(queue, 1):
            lines.append(f"{i}. {track.get('title', 'Unknown')} (query: {track.get('query', '')})")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "music_queue_clear":
        return "[QUEUE CLEARED] Music queue is now empty."

    if isinstance(result, dict) and result.get("kind") == "music_queue_next":
        if bool(result.get("played")):
            return (
                f"[PLAYING NEXT] {result.get('title', '')}\n"
                f"pid: {result.get('pid', '')}\n"
                f"remaining in queue: {result.get('remaining_in_queue', 0)}"
            )
        return f"[QUEUE NEXT] Could not play next track — {result.get('reason', 'unknown')}"

    if isinstance(result, dict) and result.get("kind") == "music_current":
        if not bool(result.get("playing")):
            return "No music is currently playing."
        return (
            f"[MUSIC CURRENT]\n"
            f"title: {result.get('title', '')}\n"
            f"pid: {result.get('pid', '')}\n"
            f"engine: {result.get('engine', '')}\n"
            f"launcher: {result.get('launcher', '')}"
        )

    if isinstance(result, dict) and result.get("kind") == "system_control":
        lines = [
            f"[SYSTEM] action={result.get('action', '')} ok={bool(result.get('ok'))} amount={result.get('amount', 1)}"
        ]
        if result.get("path"):
            lines.append(f"path: {result.get('path', '')}")
        lines.append(f"stdout: {result.get('stdout', '')}")
        lines.append(f"stderr: {result.get('stderr', '')}")
        return "\n".join(lines).strip()

    if isinstance(result, dict) and result.get("kind") == "cron_status":
        return (
            f"Cron status\n"
            f"- jobs_total: {result.get('jobs_total', 0)}\n"
            f"- jobs_enabled: {result.get('jobs_enabled', 0)}\n"
            f"- jobs_due_now: {result.get('jobs_due_now', 0)}"
        )

    if isinstance(result, dict) and result.get("kind") == "cron_list":
        jobs = result.get("jobs", [])
        if not isinstance(jobs, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron jobs: {len(jobs)}"]
        for row in jobs[:40]:
            if not isinstance(row, dict):
                continue
            jid = row.get("id", "")
            name = row.get("name", "")
            enabled = bool(row.get("enabled", True))
            next_at = row.get("state", {}).get("next_run_at_ms") if isinstance(row.get("state"), dict) else None
            lines.append(f"- {jid} | {name} | enabled={enabled} | next={next_at}")
        if len(jobs) > 40:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "cron_job":
        action = str(result.get("action", ""))
        job = result.get("job", {})
        if not isinstance(job, dict):
            return json.dumps(result, ensure_ascii=False, indent=2)
        return (
            f"Cron {action} complete\n"
            f"- id: {job.get('id', '')}\n"
            f"- name: {job.get('name', '')}\n"
            f"- enabled: {bool(job.get('enabled', True))}\n"
            f"- next_run_at_ms: {job.get('state', {}).get('next_run_at_ms') if isinstance(job.get('state'), dict) else None}"
        )

    if isinstance(result, dict) and result.get("kind") in {"cron_run", "cron_run_due", "cron_runs"}:
        if result.get("kind") == "cron_run":
            return (
                f"Cron run\n"
                f"- job_id: {result.get('job_id', '')}\n"
                f"- status: {result.get('status', '')}\n"
                f"- duration_ms: {result.get('duration_ms', '')}\n"
                f"- error: {result.get('error', '')}"
            )
        if result.get("kind") == "cron_run_due":
            ran = result.get("ran", [])
            if not isinstance(ran, list):
                return json.dumps(result, ensure_ascii=False, indent=2)
            lines = [f"Cron run_due executed: {len(ran)}"]
            for row in ran[:40]:
                if not isinstance(row, dict):
                    continue
                lines.append(f"- {row.get('job_id', '')}: {row.get('status', '')} ({row.get('duration_ms', '')} ms)")
            return "\n".join(lines)
        rows = result.get("runs", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"Cron runs for {result.get('job_id', '')}: {len(rows)}"]
        for row in rows[:40]:
            if not isinstance(row, dict):
                continue
            lines.append(f"- {row.get('ts_ms', '')}: {row.get('status', '')} {row.get('error', '')}")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") == "page_content":
        if not bool(result.get("ok")):
            return f"[FETCH FAILED] {result.get('url', '')}\nreason: {result.get('reason', 'unknown')}"
        content = str(result.get("content", ""))
        truncated = bool(result.get("truncated"))
        suffix = "\n... [truncated — ask to fetch more if needed]" if truncated else ""
        return f"[PAGE CONTENT] {result.get('url', '')}\ndomain: {result.get('domain', '')}\n\n{content}{suffix}"

    if isinstance(result, dict) and result.get("kind") == "search_and_fetch":
        query = str(result.get("query", ""))
        engine = str(result.get("engine", ""))
        fetched = result.get("fetched_pages", [])
        search_results = result.get("search_results", [])
        lines = [f"Search & Fetch results for: '{query}' (engine: {engine})"]
        if fetched:
            lines.append(f"\n--- Scraped content from {len(fetched)} page(s) ---")
            for i, page in enumerate(fetched, 1):
                lines.append(f"\n[Source {i}] {page.get('title', '')} ({page.get('domain', '')})")
                lines.append(f"URL: {page.get('url', '')}")
                lines.append(page.get("content", ""))
                if bool(page.get("truncated")):
                    lines.append("... [truncated]")
        else:
            lines.append("\n[No page content could be scraped — showing search results only]")
            for i, row in enumerate(search_results[:5], 1):
                title = str(row.get("title", ""))
                snippet = str(row.get("snippet", ""))
                url = str(row.get("url", ""))
                lines.append(f"{i}. {title}")
                if snippet:
                    lines.append(f"   {snippet}")
                if url:
                    lines.append(f"   {url}")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("kind") in {"web_search", "news_search"}:
        rows = result.get("results", [])
        if not isinstance(rows, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        kind = str(result.get("kind"))
        engine = str(result.get("engine", ""))
        query = str(result.get("query", ""))
        include_urls = bool(result.get("include_urls", False))
        label = "News Brief" if kind == "news_search" else "Web Brief"
        lines = [f"{label} ({engine}) on '{query}'", "Key pointers:"]
        for i, row in enumerate(rows[:12], 1):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "")).strip()
            url = str(row.get("url", "")).strip()
            source = str(row.get("source", "")).strip()
            published = str(row.get("published", "")).strip()
            snippet = str(row.get("snippet", "")).strip()
            meta = " | ".join(x for x in [source or row.get("domain", ""), published] if x)
            lines.append(f"{i}. {title}".strip())
            if meta:
                lines.append(f"   {meta}")
            if snippet:
                lines.append(f"   {snippet}")
            if include_urls and url:
                lines.append(f"   {url}")
        if len(rows) > 12:
            lines.append("... [truncated in display]")
        if not include_urls:
            lines.append("Ask 'with links' if you want source URLs.")
        return "\n".join(lines)

    if isinstance(result, dict) and result.get("terminated") is True:
        proc = result.get("process", "")
        requested = result.get("requested", "")
        return f"[CLOSED] requested={requested} process={proc}".strip()

    if isinstance(result, dict) and result.get("launched") is True:
        app = result.get("app", "")
        pid = result.get("pid", "")
        cwd = result.get("cwd", ".")
        args = result.get("args", [])
        args_text = " ".join(str(a) for a in args) if isinstance(args, list) else ""
        return f"[LAUNCHED] {app} {args_text}\npid: {pid}\ncwd: {cwd}".strip()

    if isinstance(result, dict) and "argv" in result and "exit_code" in result:
        ok = bool(result.get("ok"))
        status = "OK" if ok else "FAILED"
        exit_code = result.get("exit_code")
        timed_out = bool(result.get("timed_out"))
        duration = result.get("duration_ms")
        cwd = result.get("cwd", ".")
        argv = result.get("argv", [])
        stdout = str(result.get("stdout", "") or "")
        stderr = str(result.get("stderr", "") or "")
        lines = [
            f"[{status}] exit={exit_code} timeout={timed_out} duration_ms={duration}",
            f"cwd: {cwd}",
            f"cmd: {' '.join(str(x) for x in argv)}",
        ]
        if stdout.strip():
            lines.append("stdout:")
            lines.append(stdout.rstrip())
        if stderr.strip():
            lines.append("stderr:")
            lines.append(stderr.rstrip())
        return "\n".join(lines)

    if isinstance(result, dict) and "path" in result and "content" in result:
        content = str(result.get("content", ""))
        head = content[:3000]
        truncated = len(content) > len(head)
        suffix = "\n... [truncated]" if truncated else ""
        return f"file: {result.get('path')}\n{head}{suffix}"

    if isinstance(result, dict) and "entries" in result:
        entries = result.get("entries", [])
        if not isinstance(entries, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [f"entries: {len(entries)} (truncated={bool(result.get('truncated'))})"]
        for item in entries[:120]:
            if not isinstance(item, dict):
                continue
            p = item.get("path", "")
            t = item.get("type", "")
            if t == "file":
                lines.append(f"FILE {p}")
            else:
                lines.append(f"DIR  {p}")
        if len(entries) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    if isinstance(result, dict) and "matches" in result:
        matches = result.get("matches", [])
        if not isinstance(matches, list):
            return json.dumps(result, ensure_ascii=False, indent=2)
        lines = [
            f"matches: {len(matches)} (truncated={bool(result.get('truncated'))}, engine={result.get('engine')})"
        ]
        lines.extend(str(m) for m in matches[:120])
        if len(matches) > 120:
            lines.append("... [truncated in display]")
        return "\n".join(lines)

    return json.dumps(result, ensure_ascii=False, indent=2)


def _first_path_after_prep(words: List[str]) -> str:
    preps = ["in", "inside", "from", "at", "on", "within", "under"]
    for i, w in enumerate(words):
        if _match(w.strip("\"'"), preps, 0.7):
            if i + 1 < len(words):
                return _normalize_human_path(" ".join(words[i + 1 :]))
            return "."
    return "."


def _looks_like_python_snippet(text: str) -> bool:
    raw = text.strip()
    lower = raw.lower()
    python_prefixes = (
        "print(",
        "import ",
        "from ",
        "def ",
        "class ",
        "for ",
        "while ",
        "if ",
        "with ",
        "x =",
        "y =",
        "z =",
    )
    if lower.startswith("python ") or lower.startswith("py "):
        return False
    if any(lower.startswith(p) for p in python_prefixes):
        return True
    if raw.endswith(")") and "(" in raw and " " not in raw.split("(", 1)[0]:
        return True
    return False


def _parse_local_intent(user_text: str, workspace_root: Path) -> Optional[Tuple[str, Dict[str, Any]]]:
    text = user_text.strip()
    tokens = _tokenize(text)
    words = text.split()
    lower_words = [w.lower().strip("\"'") for w in words]

    if not tokens:
        return None

    if tokens[0] in {"stop", "pause"} and len(tokens) == 1:
        return ("stop_music", {})

    if tokens[0] in {"stop", "pause"} and any(t in {"music", "song", "audio"} for t in tokens[1:]):
        return ("stop_music", {})

    if tokens[0] in {"play", "listen"}:
        if len(words) == 1:
            return ("__run_help", {"message": "Usage: play <song name>"})
        query = text.split(maxsplit=1)[1].strip().strip("\"'")
        if query:
            return ("play_music", {"query": query, "headless": True, "stop_current": True})

    if tokens[0] == "queue" or (tokens[0] in {"add", "enqueue"} and any(t in {"song", "music", "track"} for t in tokens)):
        if len(words) <= 1:
            return ("show_queue", {})
        query = text.split(maxsplit=1)[1].strip().strip("\"'")
        if query:
            return ("queue_music", {"query": query})

    if tokens[0] in {"next", "skip"} and any(t in {"song", "music", "track", "queue"} for t in tokens):
        return ("play_next_in_queue", {})

    if tokens[0] in {"show", "list", "view"} and any(t in {"queue"} for t in tokens[1:]):
        return ("show_queue", {})

    if tokens[0] in {"clear", "empty", "reset"} and any(t in {"queue"} for t in tokens[1:]):
        return ("clear_queue", {})

    if any(t in {"song", "music", "track"} for t in tokens) and any(
        t in {"what", "which", "name", "current", "now", "playing"} for t in tokens
    ):
        return ("current_music", {})

    has_volume = any(_match(t, ["volume", "sound", "audio", "loudness"], 0.72) for t in tokens)
    has_up = any(_match(t, ["up", "increase", "higher", "raise", "boost", "louder"], 0.72) for t in tokens)
    has_down = any(_match(t, ["down", "decrease", "lower", "reduce", "softer", "quieter"], 0.72) for t in tokens)
    has_desktop = any(_match(t, ["desktop"], 0.75) for t in tokens)
    has_show = any(_match(t, ["show", "minimize", "hide"], 0.74) for t in tokens)
    has_lock = any(_match(t, ["lock"], 0.75) for t in tokens)
    has_screen = any(_match(t, ["screen", "pc", "computer", "system"], 0.72) for t in tokens)
    has_mute = any(_match(t, ["mute", "unmute", "silent"], 0.72) for t in tokens)
    has_next = any(_match(t, ["next", "skip"], 0.72) for t in tokens)
    has_prev = any(_match(t, ["previous", "prev", "back"], 0.72) for t in tokens)
    has_media = any(_match(t, ["song", "track", "music", "audio", "media"], 0.72) for t in tokens)
    has_play_pause = any(_match(t, ["playpause", "pause", "resume", "play"], 0.72) for t in tokens) and has_media
    has_brightness = any(_match(t, ["brightness", "backlight"], 0.74) for t in tokens)
    has_wifi = any(_match(t, ["wifi", "wi-fi", "wlan", "wireless"], 0.72) for t in tokens)
    has_bluetooth = any(_match(t, ["bluetooth", "bt"], 0.72) for t in tokens)
    has_screenshot = any(_match(t, ["screenshot", "snapshot", "capture"], 0.72) for t in tokens) and any(
        _match(t, ["screen", "desktop"], 0.72) for t in tokens
    ) or any(_match(t, ["screenshot"], 0.72) for t in tokens)
    has_window = any(_match(t, ["window", "windows"], 0.72) for t in tokens)
    has_restore = any(_match(t, ["restore", "undo"], 0.72) for t in tokens)
    has_disable = any(_match(t, ["disable", "off", "turnoff", "disconnect"], 0.72) for t in tokens)
    has_enable = any(_match(t, ["enable", "on", "turnon", "connect"], 0.72) for t in tokens)

    if has_show and has_desktop:
        return ("system_control", {"action": "show_desktop", "amount": 1})
    if has_lock and has_screen:
        return ("system_control", {"action": "lock_screen", "amount": 1})
    if has_volume and has_up:
        return ("system_control", {"action": "volume_up", "amount": 6})
    if has_volume and has_down:
        return ("system_control", {"action": "volume_down", "amount": 6})
    if has_mute:
        return ("system_control", {"action": "mute_toggle", "amount": 1})
    if has_next and has_media:
        return ("system_control", {"action": "media_next", "amount": 1})
    if has_prev and has_media:
        return ("system_control", {"action": "media_prev", "amount": 1})
    if has_play_pause:
        return ("system_control", {"action": "media_play_pause", "amount": 1})
    if has_brightness and has_up:
        return ("system_control", {"action": "brightness_up", "amount": 10})
    if has_brightness and has_down:
        return ("system_control", {"action": "brightness_down", "amount": 10})
    if has_brightness:
        nums = [int(t) for t in tokens if t.isdigit()]
        if nums:
            return ("system_control", {"action": "brightness_set", "amount": max(1, min(nums[0], 100))})
    if has_wifi and has_disable:
        return ("system_control", {"action": "wifi_off", "amount": 1})
    if has_wifi and has_enable:
        return ("system_control", {"action": "wifi_on", "amount": 1})
    if has_bluetooth and has_disable:
        return ("system_control", {"action": "bluetooth_off", "amount": 1})
    if has_bluetooth and has_enable:
        return ("system_control", {"action": "bluetooth_on", "amount": 1})
    if has_screenshot:
        return ("system_control", {"action": "screenshot", "amount": 1})
    if has_window and has_show and not has_desktop:
        return ("system_control", {"action": "window_minimize_all", "amount": 1})
    if has_window and has_restore:
        return ("system_control", {"action": "window_restore_all", "amount": 1})

    if tokens[0] == "cron":
        if len(tokens) == 1:
            return ("cron", {"action": "status"})
        action = tokens[1]
        if action in {"status", "list"}:
            return ("cron", {"action": action})
        if action in {"run", "remove", "runs"}:
            if len(words) < 3:
                return ("__run_help", {"message": f"Usage: cron {action} <job_id>"})
            return ("cron", {"action": action, "job_id": words[2].strip()})
        if action == "due":
            return ("cron", {"action": "run_due"})

    if tokens[0] in {"close", "kill", "stop", "terminate", "quit"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: close <app>. Examples: close notepad | kill chrome"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            return ("terminate_app", {"app": target_text, "force": True})

    # Realtime web/news search (separate from workspace file search)
    news_tokens = {"news", "headline", "headlines", "latest"}
    web_tokens = {"web", "internet", "online", "google"}
    search_tokens = {"search", "find", "lookup"}
    link_tokens = {"link", "links", "url", "urls", "source", "sources"}
    has_news = any(t in news_tokens for t in tokens)
    has_web = any(t in web_tokens for t in tokens)
    has_search = any(t in search_tokens for t in tokens)
    wants_links = any(t in link_tokens for t in tokens)
    if has_news:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in news_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        query = query or "latest technology news"
        return ("search_news", {"query": query, "max_results": 8, "include_urls": wants_links})
    if has_web and has_search:
        query = _extract_quoted_text(text)
        if not query:
            filtered = [w for w in words if w.lower().strip("\"'") not in web_tokens | search_tokens | {"for", "about"}]
            query = " ".join(filtered).strip()
        if query:
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    # Factual queries — use search_and_fetch to get real data not just links
    factual_triggers = {"price", "cost", "weather", "temperature", "rate", "how much", "what is",
                        "specs", "details", "score", "value", "definition", "meaning", "who is", "when did"}
    if any(trigger in text.lower() for trigger in factual_triggers):
        query = _extract_quoted_text(text) or text.strip()
        if query:
            return ("search_and_fetch", {"query": query, "fetch_top": 2})

    if tokens[0] in {"open", "launch", "start"}:
        if len(words) == 1:
            return (
                "__run_help",
                {"message": "Usage: open <app|file>. Examples: open notepad | open README.md"},
            )
        target_text = text.split(maxsplit=1)[1].strip().strip("\"'")
        if target_text:
            normalized_path = _normalize_human_path(target_text)
            try:
                resolved = fs_ops.resolve_safe_path(workspace_root, normalized_path)
                if resolved.exists() and resolved.is_file():
                    return ("read_file", {"path": normalized_path})
            except Exception:
                pass
            # If user mentions an extension-like token, prefer file read attempt.
            if "." in Path(normalized_path).name and " " not in Path(normalized_path).name:
                return ("read_file", {"path": normalized_path})
            return ("launch_app", {"app": target_text, "args": []})

    if tokens[0] in {"run", "exec", "execute", "cmd"}:
        if len(words) == 1:
            return (
                "__run_help",
                {
                    "message": "Usage: run <command>. Examples: run dir | run python -c \"print('hi')\" | run Get-ChildItem -Force",
                },
            )
        command_text = text.split(maxsplit=1)[1].strip()
        if command_text:
            if _looks_like_python_snippet(command_text):
                return (
                    "run_command",
                    {
                        "command": sys.executable,
                        "args": ["-c", command_text],
                        "use_shell": False,
                        "timeout_ms": 20000,
                    },
                )
            return ("run_command", {"command": command_text, "use_shell": True, "timeout_ms": 20000})

    has_list = any(_match(t, ["list", "show", "display", "ls"], 0.74) for t in tokens)
    has_files = any(_match(t, ["file", "files", "dir", "directory", "folder", "workspace", "project"], 0.72) for t in tokens)
    if has_list and has_files:
        return ("list_files", {"path": _first_path_after_prep(words), "max_entries": 300})

    if tokens[0] in {"read", "open", "cat"} and len(words) > 1:
        return ("read_file", {"path": _normalize_human_path(" ".join(words[1:]))})

    has_search = any(_match(t, ["search", "find", "grep", "contains", "lookup"], 0.72) for t in tokens)
    if has_search:
        query = _extract_quoted_text(text)
        path = _first_path_after_prep(words)
        if not query:
            idx = 0
            for i, w in enumerate(lower_words):
                if _match(w, ["search", "find", "grep", "contains", "lookup"], 0.72):
                    idx = i
                    break
            end = len(words)
            for i, w in enumerate(lower_words):
                if i <= idx:
                    continue
                if _match(w, ["in", "inside", "within", "under"], 0.7):
                    end = i
                    break
            query = " ".join(words[idx + 1 : end]).strip().strip("\"'")
        if query:
            if query.lower().startswith("for "):
                query = query[4:].strip()
            scope_tokens = {
                "workspace",
                "project",
                "repo",
                "repository",
                "codebase",
                "file",
                "files",
                "folder",
                "directory",
                "path",
                "here",
            }
            has_local_scope = any(t in scope_tokens for t in tokens)
            if has_local_scope:
                return ("search_text", {"query": query, "path": path, "max_results": 100})
            wants_links = any(t in {"link", "links", "url", "urls", "source", "sources"} for t in tokens)
            return ("search_web", {"query": query, "max_results": 8, "include_urls": wants_links})

    return None


def try_direct_local_command(user_text: str, workspace_root: Path) -> Optional[str]:
    parsed = _parse_local_intent(user_text, workspace_root)
    if not parsed:
        return None
    name, args = parsed
    if name == "__run_help":
        return str(args.get("message", "Usage: run <command>"))
    return _format_result(_call(name, args, workspace_root))


def _strip_blobs(content: Any) -> Any:
    """
    Strip base64 image blobs and huge JSON payloads from a message content field.
    Handles both string content and list-of-blocks (multimodal) content.
    """
    import re as _re
    if isinstance(content, str):
        # Strip inline base64 data URIs (data:image/...;base64,<blob>)
        stripped = _re.sub(
            r'data:image/[^;]+;base64,[A-Za-z0-9+/=]{200,}',
            '[IMAGE_DATA_REMOVED]',
            content,
        )
        # If the resulting string is still very large (>8000 chars), truncate it
        if len(stripped) > 8000:
            stripped = stripped[:8000] + "\n... [truncated to fit token limit]"
        return stripped
    if isinstance(content, list):
        # Multimodal content blocks — remove image_url blocks entirely
        return [
            block for block in content
            if not (isinstance(block, dict) and block.get("type") == "image_url")
        ] or "[IMAGE_REMOVED]"
    return content


def _estimate_tokens(messages: List[Dict[str, Any]]) -> int:
    """
    Rough token estimator: chars / 4.
    Fast enough to call before every LLM request.
    """
    total = 0
    for m in messages:
        content = m.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += len(str(block.get("text", "")))
        # Also count tool_calls if present
        if m.get("tool_calls"):
            total += len(str(m["tool_calls"]))
    return total // 4  # rough chars-to-tokens ratio


def compact_messages(
    messages: List[Dict[str, Any]],
    keep_tail: int = 8,
    char_limit: int = 120_000,   # ~30k tokens safety margin below 64k limit
    runtime: Any = None,  # LLMRuntime for LLM-powered summarization (tier 2)
) -> List[Dict[str, Any]]:
    """
    Smart message compactor — Token Limit Guardian v2 (OpenClaw-inspired).

    3-Tier Cascading Recovery (like OpenClaw's compaction system):

    Tier 1: TRIM — Fast, no LLM call
      1a. Strip base64 blobs + large image_url blocks from ALL messages.
      1b. Cap oversized tool results to _HARD_CAP_DEFAULT (proportional truncation).
      1c. Drop old tool messages (role='tool') beyond the last 4 turns.
      1d. Drop oldest non-system messages until we fit.

    Tier 2: SUMMARIZE — LLM-powered (OpenClaw's "explicit compaction")
      If Tier 1 isn't enough and runtime is available, ask the LLM to
      summarize the older conversation into a compact context block.
      This preserves decisions, TODOs, and key facts (unlike dropping).

    Tier 3: EMERGENCY — Nuclear option
      Keep only system + last N messages. Insert loss notice.
    """
    if not messages:
        return messages

    # ── Tier 1a: Strip blobs from every message ─────────────────────────────
    cleaned: List[Dict[str, Any]] = []
    for m in messages:
        m2 = dict(m)
        if "content" in m2:
            m2["content"] = _strip_blobs(m2["content"])
        cleaned.append(m2)

    if _estimate_tokens(cleaned) * 4 <= char_limit:
        return cleaned

    # ── Tier 1b: Cap oversized tool results ─────────────────────────────────
    for m in cleaned:
        if m.get("role") == "tool":
            content = m.get("content", "")
            if isinstance(content, str) and len(content) > _HARD_CAP_DEFAULT:
                m["content"] = content[:_HARD_CAP_DEFAULT] + _HARD_CAP_MSG

    if _estimate_tokens(cleaned) * 4 <= char_limit:
        return cleaned

    # ── Tier 1c: Separate system message, drop old tool messages ────────────
    system_msg = cleaned[0] if cleaned and cleaned[0].get("role") == "system" else None
    rest = cleaned[1:] if system_msg else cleaned

    last_n = rest[-8:] if len(rest) > 8 else rest
    older = rest[:-8] if len(rest) > 8 else []
    older_filtered = [
        m for m in older
        if m.get("role") in ("user", "assistant") and m.get("content", "").strip()
    ]
    rest = older_filtered + last_n

    # ── Tier 1d: Drop oldest until fit ──────────────────────────────────────
    trimmed_count = 0
    while rest and _estimate_tokens(([system_msg] if system_msg else []) + rest) * 4 > char_limit:
        rest.pop(0)
        trimmed_count += 1

    if len(rest) >= keep_tail:
        result: List[Dict[str, Any]] = []
        if system_msg:
            result.append(system_msg)
        if trimmed_count > 0:
            result.append({
                "role": "system",
                "content": (
                    f"[Token Guardian] Context trimmed: {trimmed_count} older messages removed "
                    f"to stay within the model's token limit. Recent conversation follows."
                ),
            })
        result.extend(rest)
        return result

    # ── Tier 2: LLM-powered summarization (OpenClaw-style) ──────────────────
    # Ask the LLM to summarize the dropped messages into a compact block
    # preserving key decisions, TODOs, file paths, and context.
    if runtime is not None and trimmed_count > 3:
        try:
            from llm import call_chat_once as _compact_llm_call
            # Gather the messages we're about to drop for summarization
            dropped = cleaned[1:trimmed_count + 1] if system_msg else cleaned[:trimmed_count]
            if dropped:
                summary_input = "\n".join(
                    f"[{m.get('role', '?')}]: {str(m.get('content', ''))[:500]}"
                    for m in dropped[:20]  # Cap at 20 messages to avoid overflow
                )
                summary_msgs = [
                    {"role": "system", "content": (
                        "You are a conversation summarizer. Compress the following conversation "
                        "into a brief context block (max 300 words). PRESERVE: file paths, "
                        "decisions made, TODOs, key facts, error resolutions, and any important "
                        "user preferences. DROP: pleasantries, redundant tool outputs, and "
                        "verbose explanations. Output ONLY the summary, no preamble."
                    )},
                    {"role": "user", "content": summary_input},
                ]
                summary_resp = _compact_llm_call(runtime, summary_msgs, tools=None, max_tokens=400)
                summary_text = (summary_resp.get("content") or "").strip()
                if summary_text and len(summary_text) > 20:
                    result = []
                    if system_msg:
                        result.append(system_msg)
                    result.append({
                        "role": "system",
                        "content": (
                            f"[Context Summary — {trimmed_count} earlier messages compressed]\n"
                            f"{summary_text}"
                        ),
                    })
                    result.extend(rest)
                    print(f"[TokenGuardian] Tier 2: LLM summarized {trimmed_count} messages into {len(summary_text)} chars", flush=True)
                    return result
        except Exception as _sum_err:
            print(f"[TokenGuardian] Tier 2 summarization failed: {_sum_err}", flush=True)

    # ── Tier 3: Emergency — keep only system + last N ───────────────────────
    result = []
    if system_msg:
        result.append(system_msg)
    emergency_tail = cleaned[-keep_tail:]
    result.append({
        "role": "system",
        "content": (
            f"[EMERGENCY COMPACTION] {len(cleaned) - keep_tail - (1 if system_msg else 0)} "
            f"messages were dropped to prevent context overflow. "
            f"Only the last {keep_tail} messages remain."
        ),
    })
    result.extend(emergency_tail)
    return result
