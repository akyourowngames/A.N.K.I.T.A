from __future__ import annotations

import email.utils
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from tools.registry import ToolInputError, optional_text, require_text
import tools.web_tools as web_tools


DEFAULT_CONFIG_PATH = Path("config/research_agent.json")


def research_status(_params: dict[str, Any] | None = None) -> dict[str, Any]:
    config = load_config()
    research_root = resolve_path(str(config.get("research_root") or "memory/research"))
    watchlists = load_json_file(watchlist_path(config), {"watchlists": []})
    return {
        "summary": f"{config.get('agent_name', 'Research Agent')} ready.",
        "config_path": str(config_path()),
        "research_root": str(research_root),
        "query_family_count": len(config.get("query_families", [])),
        "source_policies": sorted((config.get("source_policies") or {}).keys()),
        "search_providers": provider_status(config),
        "watchlist_count": len(watchlists.get("watchlists", [])) if isinstance(watchlists, dict) else 0,
    }


def research_config(params: dict[str, Any]) -> dict[str, Any]:
    operation = optional_text(params, "operation", "get").casefold()
    config = load_config()
    if operation == "get":
        return {"config_path": str(config_path()), "config": public_config(config)}
    if operation == "update":
        values = params.get("values")
        if not isinstance(values, dict):
            raise ToolInputError("values must be an object for update")
        merged = merge_dicts(config, values)
        save_config(merged)
        return {"updated": True, "config_path": str(config_path()), "config": public_config(merged)}
    raise ToolInputError(f"Unsupported research config operation: {operation}")


def research_plan(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    topic = require_text(params, "topic")
    normalized_topic = optional_text(params, "normalized_topic", topic)
    mode = configured_choice(params, config, "mode", "default_mode", "briefing")
    quality = configured_choice(params, config, "quality", "default_quality", "standard")
    time_window = optional_text(params, "time_window", str(config.get("default_time_window") or "last 7 days"))
    region = optional_text(params, "region", str(config.get("default_region") or "global"))
    language = optional_text(params, "language", str(config.get("default_language") or "English"))
    risk_level = optional_text(params, "risk_level", str(config.get("default_risk_level") or "normal"))
    source_policy_key = optional_text(params, "source_policy", source_policy_for_mode(config, mode))
    source_types = text_list_param(params.get("source_types")) or mode_source_types(config, mode)
    limit = quality_limit(config, quality, "queries")
    queries = build_queries(
        config,
        topic=normalized_topic,
        time_window=time_window,
        mode=mode,
        source_policy=source_policy_key,
        region=region,
        language=language,
        limit=limit,
    )
    plan = {
        "topic": topic,
        "normalized_topic": normalized_topic,
        "mode": mode,
        "quality": quality,
        "time_window": time_window,
        "region": region,
        "language": language,
        "risk_level": risk_level,
        "source_policy": source_policy_key,
        "source_types": source_types,
        "queries": queries,
        "success_criteria": success_criteria(config, mode, source_policy_key),
    }
    return {
        "summary": f"Research plan prepared for {normalized_topic}.",
        "plan": plan,
        "source_policy": policy_for_key(config, source_policy_key),
    }


def research_search(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    plan = object_param(params.get("plan"))
    topic = optional_text(params, "topic", str(plan.get("normalized_topic") or plan.get("topic") or ""))
    quality = optional_text(params, "quality", str(plan.get("quality") or config.get("default_quality") or "standard"))
    time_window = optional_text(params, "time_window", str(plan.get("time_window") or config.get("default_time_window") or ""))
    count = bounded_int(params.get("count"), quality_limit(config, quality, "results_per_query"), 1, 20)
    timeout = bounded_int(params.get("timeout_seconds"), int(config.get("search_timeout_seconds") or 15), 1, 120)
    queries = query_items(params.get("queries")) or query_items(plan.get("queries"))
    if not queries and topic:
        plan_result = research_plan({"topic": topic, "quality": quality})
        queries = query_items(plan_result["plan"].get("queries"))
    if not queries:
        raise ToolInputError("queries or topic is required")

    max_queries = bounded_int(params.get("max_queries"), quality_limit(config, quality, "queries"), 1, 24)
    provider_errors: list[dict[str, str]] = []
    all_results: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in queries[:max_queries]:
        query_text = str(query.get("query") or "").strip()
        if not query_text:
            continue
        results, errors = search_one_query(config, query_text, count=count, timeout=timeout, time_window=time_window)
        provider_errors.extend(errors)
        for rank, result in enumerate(results, start=1):
            url = str(result.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            all_results.append(
                {
                    "title": str(result.get("title") or ""),
                    "url": url,
                    "snippet": str(result.get("snippet") or result.get("content") or ""),
                    "publisher": publisher_from_url(url),
                    "query": query_text,
                    "query_type": query.get("type", ""),
                    "source_provider": result.get("source_provider", ""),
                    "rank": rank,
                    "published_date": result.get("published_date", ""),
                    "score": result.get("score", None),
                }
            )
    return {
        "summary": f"Found {len(all_results)} unique research result(s).",
        "topic": topic,
        "queries_used": queries[:max_queries],
        "count": len(all_results),
        "results": all_results,
        "provider_errors": provider_errors,
    }


def research_fetch_sources(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    quality = optional_text(params, "quality", str(config.get("default_quality") or "standard"))
    max_sources = bounded_int(params.get("max_sources"), quality_limit(config, quality, "sources"), 1, 50)
    max_chars = bounded_int(params.get("max_chars"), int(config.get("max_chars_per_source") or 8000), 500, 100000)
    timeout = bounded_int(params.get("timeout_seconds"), int(config.get("fetch_timeout_seconds") or 15), 1, 120)
    urls = source_urls_from_params(params)[:max_sources]
    if not urls:
        raise ToolInputError("urls or search_results is required")

    metadata_by_url = source_metadata_from_params(params)
    sources: list[dict[str, Any]] = []
    for url in urls:
        try:
            source = fetch_source(url, max_chars=max_chars, timeout=timeout, config=config)
            sources.append(apply_search_metadata(source, metadata_by_url.get(url, {})))
        except Exception as error:
            metadata = metadata_by_url.get(url, {})
            sources.append(
                {
                    "source_id": short_hash(url),
                    "ok": False,
                    "url": url,
                    "title": metadata.get("title", ""),
                    "search_snippet": metadata.get("snippet", ""),
                    "publisher": publisher_from_url(url),
                    "error": f"{type(error).__name__}: {error}",
                    "fetched_at": utc_now(),
                }
            )
    return {
        "summary": f"Fetched {sum(1 for item in sources if item.get('ok'))} of {len(sources)} source(s).",
        "count": len(sources),
        "sources": sources,
    }


def research_rank_sources(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    policy_key = optional_text(params, "source_policy", str(config.get("default_source_policy") or "general"))
    policy = policy_for_key(config, policy_key)
    weights = object_param(config.get("source_score_weights"))
    sources = source_items(params)
    ranked: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for source in sources:
        if not source.get("ok", True):
            ranked.append({**source, "source_score": 0.0, "risk_flags": ["fetch_failed"]})
            continue
        text_hash = str(source.get("text_hash") or short_hash(str(source.get("text") or "")))
        if text_hash and text_hash in seen_hashes:
            item = {**source, "source_score": 0.0, "risk_flags": ["duplicate_text"]}
            ranked.append(item)
            continue
        seen_hashes.add(text_hash)
        score, flags = score_source(source, policy, weights)
        ranked.append({**source, "source_score": round(score, 3), "risk_flags": flags})
    ranked.sort(key=lambda item: item.get("source_score", 0), reverse=True)
    return {
        "summary": f"Ranked {len(ranked)} source(s).",
        "source_policy": policy_key,
        "ranked_sources": ranked,
    }


def research_extract_claims(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    sources = source_items(params)
    max_claims = bounded_int(params.get("max_claims"), int(config.get("max_claims") or 24), 1, 100)
    per_source = bounded_int(params.get("claims_per_source"), int(config.get("claims_per_source") or 3), 1, 10)
    claims: list[dict[str, Any]] = []
    claims_by_key: dict[str, dict[str, Any]] = {}
    for source in sources:
        if not source.get("ok", True):
            continue
        source_id = str(source.get("source_id") or short_hash(str(source.get("url") or "")))
        text = source_text_for_claims(source)
        sentences = extract_sentences(text, config)
        for sentence in sentences[:per_source]:
            claim_text = clean_claim_text(sentence)
            key = normalized_key(claim_text)
            if not key:
                continue
            existing = claims_by_key.get(key)
            if existing is not None:
                append_unique(existing["source_ids"], source_id)
                append_unique(existing["source_urls"], str(source.get("url") or ""))
                append_unique(existing["source_titles"], str(source.get("title") or ""))
                continue
            claim = {
                "claim_id": short_hash(source_id + claim_text),
                "claim": claim_text,
                "source_ids": [source_id],
                "source_urls": [source.get("url", "")],
                "source_titles": [source.get("title", "")],
                "publisher": source.get("publisher", ""),
                "published_date": source.get("published_date", ""),
                "entities": extract_entities(claim_text),
                "evidence_quote": claim_text[:500],
            }
            claims_by_key[key] = claim
            claims.append(claim)
            if len(claims) >= max_claims:
                break
        if len(claims) >= max_claims:
            break
    return {
        "summary": f"Extracted {len(claims)} claim candidate(s) from source text.",
        "count": len(claims),
        "claims": claims,
    }


def research_verify_claims(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    claims = claim_items(params)
    sources = source_items(params)
    source_by_id = {str(source.get("source_id") or ""): source for source in sources}
    policy_key = optional_text(params, "source_policy", str(config.get("default_source_policy") or "general"))
    policy = policy_for_key(config, policy_key)
    minimum_sources = bounded_int(
        params.get("minimum_independent_sources"),
        int(policy.get("minimum_independent_sources") or config.get("minimum_independent_sources") or 2),
        1,
        10,
    )
    threshold = bounded_float(config.get("claim_support_similarity"), 0.34, 0.05, 0.95)
    minimum_shared_tokens = bounded_int(config.get("claim_support_min_tokens"), 6, 1, 30)
    cross_scan = bool(config.get("claim_support_cross_scan", False))
    verified: list[dict[str, Any]] = []
    for claim in claims:
        text = str(claim.get("claim") or "")
        support_sources = support_for_claim(text, claim, sources, source_by_id, threshold, minimum_shared_tokens, cross_scan)
        unique_domains = sorted({publisher_from_url(str(item.get("url") or "")) for item in support_sources if item.get("url")})
        avg_score = average([float(item.get("source_score") or 0.0) for item in support_sources])
        confidence_score = confidence_from_support(len(unique_domains), avg_score, minimum_sources)
        confidence = confidence_label(confidence_score, len(unique_domains), minimum_sources)
        status = "verified" if confidence == "high" else "limited" if confidence == "medium" else "unconfirmed"
        if len(unique_domains) < minimum_sources:
            status = "needs_more_sources"
        verified.append(
            {
                **claim,
                "supporting_sources": [
                    {
                        "source_id": item.get("source_id", ""),
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "publisher": item.get("publisher", ""),
                        "published_date": item.get("published_date", ""),
                        "source_score": item.get("source_score", 0),
                    }
                    for item in support_sources
                ],
                "independent_source_count": len(unique_domains),
                "confidence": confidence,
                "confidence_score": round(confidence_score, 3),
                "conflict_status": status,
            }
        )
    verified.sort(key=lambda item: item.get("confidence_score", 0), reverse=True)
    return {
        "summary": f"Verified {len(verified)} claim candidate(s) against source overlap.",
        "source_policy": policy_key,
        "minimum_independent_sources": minimum_sources,
        "verified_claims": verified,
    }


def research_synthesize(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    plan = object_param(params.get("plan"))
    mode = optional_text(params, "mode", str(plan.get("mode") or config.get("default_mode") or "briefing"))
    sources = source_items(params)
    claims = verified_claim_items(params)
    limit = bounded_int(params.get("max_claims"), int(config.get("synthesis_claims") or 12), 1, 50)
    top_claims = claims[:limit]
    evidence_pack = {
        "topic": plan.get("normalized_topic") or plan.get("topic") or optional_text(params, "topic"),
        "mode": mode,
        "time_window": plan.get("time_window") or optional_text(params, "time_window"),
        "generated_at": utc_now(),
        "top_claims": top_claims,
        "timeline": timeline_from_claims(top_claims),
        "source_list": compact_sources(sources),
        "uncertainty": [claim for claim in top_claims if claim.get("confidence") != "high"],
        "source_policy": params.get("source_policy") or plan.get("source_policy") or config.get("default_source_policy"),
    }
    report_draft = report_from_evidence(evidence_pack)
    compiler_content = compiler_content_from_evidence(evidence_pack)
    return {
        "summary": f"Evidence pack ready with {len(top_claims)} claim(s) and {len(evidence_pack['source_list'])} source(s).",
        "evidence_pack": evidence_pack,
        "compiler_content": compiler_content,
        "report_draft": report_draft,
        "safe_user_output": report_draft,
    }


def research_save(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    topic = optional_text(params, "topic", "research")
    evidence_pack = object_param(params.get("evidence_pack"))
    report = optional_text(params, "report")
    if not report and evidence_pack:
        report = report_from_evidence(evidence_pack)
    if not report:
        raise ToolInputError("report or evidence_pack is required")
    run_id = optional_text(params, "run_id", short_hash(topic + utc_now()))
    extension = str(config.get("report_extension") or ".txt")
    if not extension.startswith("."):
        extension = "." + extension
    dossier_dir = resolve_path(str(config.get("dossier_dir") or "memory/research/dossiers"))
    cache_dir = resolve_path(str(config.get("cache_dir") or "memory/research/cache"))
    dossier_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    slug = slug_text(topic)
    report_path = dossier_dir / f"{timestamp_slug()}-{slug}{extension}"
    evidence_path = cache_dir / f"{run_id}-evidence.json"
    report_path.write_text(report, encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence_pack, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run_log(config, {"run_id": run_id, "topic": topic, "report_path": str(report_path), "evidence_path": str(evidence_path), "created_at": utc_now()})
    return {
        "saved": True,
        "run_id": run_id,
        "report_path": str(report_path),
        "evidence_path": str(evidence_path),
        "summary": f"Saved research dossier for {topic}.",
    }


def research_watchlist(params: dict[str, Any]) -> dict[str, Any]:
    config = load_config()
    operation = optional_text(params, "operation", "list").casefold()
    path = watchlist_path(config)
    data = load_json_file(path, {"watchlists": []})
    watchlists = data.get("watchlists", []) if isinstance(data, dict) else []
    if not isinstance(watchlists, list):
        watchlists = []

    if operation == "list":
        return {"watchlists": watchlists, "count": len(watchlists), "path": str(path)}
    if operation in {"upsert", "add", "update"}:
        topic = require_text(params, "topic")
        source_policy = valid_source_policy(
            config,
            optional_text(params, "source_policy", str(config.get("default_source_policy") or "general")),
        )
        item = {
            "topic": topic,
            "mode": optional_text(params, "mode", str(config.get("default_mode") or "briefing")),
            "frequency": optional_text(params, "frequency", "manual"),
            "source_policy": source_policy,
            "last_checked": optional_text(params, "last_checked"),
            "created_at": utc_now(),
        }
        new_items = [existing for existing in watchlists if str(existing.get("topic") or "").casefold() != topic.casefold()]
        new_items.append(item)
        save_json_file(path, {"watchlists": new_items})
        return {"saved": True, "watchlist": item, "count": len(new_items), "path": str(path)}
    if operation == "remove":
        topic = require_text(params, "topic")
        new_items = [existing for existing in watchlists if str(existing.get("topic") or "").casefold() != topic.casefold()]
        save_json_file(path, {"watchlists": new_items})
        return {"removed": len(watchlists) - len(new_items), "count": len(new_items), "path": str(path)}
    raise ToolInputError(f"Unsupported research watchlist operation: {operation}")


def research_run(params: dict[str, Any]) -> dict[str, Any]:
    topic = require_text(params, "topic")
    plan_result = research_plan(params)
    plan = plan_result["plan"]
    search_result = research_search(
        {
            "plan": plan,
            "quality": plan.get("quality"),
            "count": params.get("count"),
            "timeout_seconds": params.get("timeout_seconds"),
        }
    )
    fetch_result = research_fetch_sources(
        {
            "search_results": search_result.get("results", []),
            "quality": plan.get("quality"),
            "max_sources": params.get("max_sources"),
            "timeout_seconds": params.get("timeout_seconds"),
        }
    )
    rank_result = research_rank_sources(
        {
            "sources": fetch_result.get("sources", []),
            "source_policy": plan.get("source_policy"),
        }
    )
    ranked_sources = apply_time_window_to_sources(
        rank_result.get("ranked_sources", []),
        str(plan.get("time_window") or ""),
        minimum=bounded_int(load_config().get("minimum_sources_after_freshness"), 2, 1, 10),
    )
    claim_result = research_extract_claims(
        {
            "sources": ranked_sources,
            "max_claims": params.get("max_claims"),
            "claims_per_source": params.get("claims_per_source") or load_config().get("run_claims_per_source"),
        }
    )
    verify_result = research_verify_claims(
        {
            "claims": claim_result.get("claims", []),
            "sources": ranked_sources,
            "source_policy": plan.get("source_policy"),
        }
    )
    synth_result = research_synthesize(
        {
            "plan": plan,
            "sources": ranked_sources,
            "verified_claims": verify_result.get("verified_claims", []),
            "source_policy": plan.get("source_policy"),
        }
    )
    evidence_pack = slim_evidence_pack(synth_result.get("evidence_pack", {}), bounded_int(params.get("max_claims"), 6, 1, 20))
    report_draft = report_from_evidence(evidence_pack)
    compiler_content = compiler_content_from_evidence(evidence_pack)
    saved: dict[str, Any] = {}
    if bool(params.get("save", False)):
        saved = research_save(
            {
                "topic": topic,
                "evidence_pack": evidence_pack,
                "run_id": short_hash(topic + utc_now()),
            }
        )
    rendered_report: dict[str, Any] = {}
    render_format = optional_text(params, "render_format")
    if render_format:
        rendered_report = render_research_report(
            compiler_content,
            render_format,
            optional_text(params, "render_template", "research_briefing"),
            optional_text(params, "output_path"),
        )
    safe_user_output = report_draft
    if rendered_report:
        path = str(rendered_report.get("output_path") or "")
        safe_user_output = f"Research report saved to {path}.\n\n{report_draft}".strip() + "\n"
    return {
        "summary": "Research pipeline completed.",
        "plan": compact_plan(plan),
        "pipeline": {
            "search_result_count": search_result.get("count", 0),
            "fetched_source_count": fetch_result.get("count", 0),
            "ranked_source_count": len(rank_result.get("ranked_sources", [])),
            "fresh_source_count": len(ranked_sources),
            "verified_claim_count": len(verify_result.get("verified_claims", [])),
            "provider_errors": search_result.get("provider_errors", []),
        },
        "evidence_pack": evidence_pack,
        "compiler_content": compiler_content,
        "report_draft": report_draft,
        "rendered_report": rendered_report,
        "safe_user_output": safe_user_output,
        "saved": saved,
    }


def config_path() -> Path:
    value = os.environ.get("JARVIS_RESEARCH_CONFIG", "").strip()
    return Path(value) if value else DEFAULT_CONFIG_PATH


def load_config() -> dict[str, Any]:
    path = config_path()
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            return ensure_config(data)
    data = ensure_config({})
    save_config(data)
    return data


def save_config(config: dict[str, Any]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(ensure_config(config), ensure_ascii=False, indent=2), encoding="utf-8")


def ensure_config(config: dict[str, Any]) -> dict[str, Any]:
    config.setdefault("agent_name", "Jarvis Research Agent")
    config.setdefault("research_root", "memory/research")
    config.setdefault("dossier_dir", "memory/research/dossiers")
    config.setdefault("cache_dir", "memory/research/cache")
    config.setdefault("watchlist_path", "memory/research/watchlists.json")
    config.setdefault("run_log_path", "memory/research/runs.jsonl")
    config.setdefault("default_mode", "briefing")
    config.setdefault("default_quality", "standard")
    config.setdefault("default_time_window", "last 7 days")
    config.setdefault("default_source_policy", "general")
    config.setdefault("query_families", [{"name": "broad", "templates": ["{topic} {time_window}"]}])
    config.setdefault("source_policies", {"general": {"preferred_domains": [], "primary_domains": [], "minimum_independent_sources": 2}})
    config.setdefault("quality_limits", {})
    config.setdefault("source_score_weights", {})
    config.setdefault("published_date_fields", ["article:published_time", "published_time", "date", "pubdate"])
    config.setdefault("tavily_news_for_recent_windows", True)
    config.setdefault("minimum_sources_after_freshness", 2)
    config.setdefault("run_claims_per_source", 1)
    config.setdefault("claim_support_min_tokens", 6)
    config.setdefault("claim_support_cross_scan", False)
    return config


def public_config(config: dict[str, Any]) -> dict[str, Any]:
    public = dict(config)
    public.pop("api_key", None)
    return public


def provider_status(config: dict[str, Any]) -> list[dict[str, Any]]:
    providers = []
    for provider in provider_order(config):
        providers.append({"name": provider, "ready": provider_ready(provider, config)})
    return providers


def provider_order(config: dict[str, Any]) -> list[str]:
    values = config.get("search_provider_order")
    if isinstance(values, list):
        return [str(item).strip().casefold() for item in values if str(item).strip()]
    return ["tavily", "duckduckgo"]


def provider_ready(provider: str, config: dict[str, Any]) -> bool:
    if provider == "tavily":
        return bool(os.environ.get(str(config.get("tavily_api_key_env") or "TAVILY_API_KEY"), "").strip())
    if provider == "duckduckgo":
        return bool(config.get("duckduckgo_search_url") or os.environ.get("JARVIS_WEB_SEARCH_URL", ""))
    return False


def configured_choice(params: dict[str, Any], config: dict[str, Any], param_name: str, default_name: str, fallback: str) -> str:
    value = optional_text(params, param_name, str(config.get(default_name) or fallback))
    return value.casefold().replace(" ", "_")


def source_policy_for_mode(config: dict[str, Any], mode: str) -> str:
    modes = object_param(config.get("modes"))
    entry = object_param(modes.get(mode))
    return str(entry.get("source_policy") or config.get("default_source_policy") or "general")


def mode_source_types(config: dict[str, Any], mode: str) -> list[str]:
    modes = object_param(config.get("modes"))
    entry = object_param(modes.get(mode))
    values = entry.get("source_types")
    if isinstance(values, list):
        return [str(item) for item in values if str(item).strip()]
    return [str(item) for item in config.get("default_source_types", []) if str(item).strip()]


def policy_for_key(config: dict[str, Any], key: str) -> dict[str, Any]:
    policies = object_param(config.get("source_policies"))
    policy = object_param(policies.get(key))
    if policy:
        return policy
    return object_param(policies.get(str(config.get("default_source_policy") or "general")))


def valid_source_policy(config: dict[str, Any], key: str) -> str:
    policies = object_param(config.get("source_policies"))
    clean = key.strip()
    if clean in policies:
        return clean
    return str(config.get("default_source_policy") or "general")


def success_criteria(config: dict[str, Any], mode: str, policy_key: str) -> list[str]:
    modes = object_param(config.get("modes"))
    mode_entry = object_param(modes.get(mode))
    criteria = text_list_param(mode_entry.get("success_criteria"))
    if criteria:
        return criteria
    policy = policy_for_key(config, policy_key)
    return text_list_param(policy.get("success_criteria"))


def quality_limit(config: dict[str, Any], quality: str, name: str) -> int:
    limits = object_param(config.get("quality_limits"))
    quality_entry = object_param(limits.get(quality.casefold()))
    value = quality_entry.get(name)
    fallback = {"queries": 6, "results_per_query": 5, "sources": 8}.get(name, 5)
    return bounded_int(value, fallback, 1, 100)


def build_queries(
    config: dict[str, Any],
    topic: str,
    time_window: str,
    mode: str,
    source_policy: str,
    region: str,
    language: str,
    limit: int,
) -> list[dict[str, str]]:
    values = {
        "topic": topic,
        "time_window": time_window,
        "mode": mode,
        "source_policy": source_policy,
        "region": region,
        "language": language,
    }
    queries: list[dict[str, str]] = []
    for family in config.get("query_families", []):
        if not isinstance(family, dict):
            continue
        family_name = str(family.get("name") or "query")
        templates = text_list_param(family.get("templates"))
        for template in templates:
            query = fill_template(template, values)
            if query:
                queries.append({"type": family_name, "query": query})
            if len(queries) >= limit:
                return queries
    if not queries:
        fallback = fill_template(str(config.get("fallback_query_template") or "{topic}"), values)
        queries.append({"type": "fallback", "query": fallback})
    return queries[:limit]


def fill_template(template: str, values: dict[str, str]) -> str:
    text = template
    for key, value in values.items():
        text = text.replace("{" + key + "}", value)
    return " ".join(text.split())


def search_one_query(config: dict[str, Any], query: str, count: int, timeout: int, time_window: str = "") -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    errors: list[dict[str, str]] = []
    for provider in provider_order(config):
        if not provider_ready(provider, config):
            continue
        try:
            if provider == "tavily":
                return search_tavily(config, query, count, timeout, time_window), errors
            if provider == "duckduckgo":
                return search_duckduckgo(config, query, count, timeout), errors
        except Exception as error:
            errors.append({"provider": provider, "query": query, "error": f"{type(error).__name__}: {error}"})
    return [], errors


def search_tavily(config: dict[str, Any], query: str, count: int, timeout: int, time_window: str = "") -> list[dict[str, Any]]:
    api_key = os.environ.get(str(config.get("tavily_api_key_env") or "TAVILY_API_KEY"), "").strip()
    if not api_key:
        return []
    endpoint = str(config.get("tavily_search_url") or "https://api.tavily.com/search")
    payload = {
        "api_key": api_key,
        "query": query,
        "max_results": count,
        "search_depth": str(config.get("tavily_search_depth") or "basic"),
        "include_answer": False,
        "include_raw_content": False,
    }
    days = days_from_time_window(time_window)
    if days > 0 and bool(config.get("tavily_news_for_recent_windows", True)):
        payload["topic"] = "news"
        payload["days"] = days
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    results = data.get("results", []) if isinstance(data, dict) else []
    output: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        output.append(
            {
                "title": str(item.get("title") or ""),
                "url": str(item.get("url") or ""),
                "snippet": str(item.get("content") or ""),
                "published_date": str(item.get("published_date") or ""),
                "score": item.get("score"),
                "source_provider": "tavily",
            }
        )
    return output


def search_duckduckgo(config: dict[str, Any], query: str, count: int, timeout: int) -> list[dict[str, Any]]:
    base = str(config.get("duckduckgo_search_url") or os.environ.get("JARVIS_WEB_SEARCH_URL", "https://duckduckgo.com/html/"))
    joiner = "&" if "?" in base else "?"
    url = f"{base}{joiner}q={urllib.parse.quote_plus(query)}"
    request = urllib.request.Request(url, headers={"User-Agent": str(config.get("user_agent") or "Jarvis-Research-Agent")})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        html = response.read(500000).decode("utf-8", errors="replace")
    parser = DuckDuckGoParser()
    parser.feed(html)
    output = []
    seen: set[str] = set()
    for item in parser.results:
        url = clean_search_href(str(item.get("url") or ""))
        if not url or url in seen:
            continue
        seen.add(url)
        output.append({"title": item.get("title", ""), "url": url, "snippet": item.get("snippet", ""), "source_provider": "duckduckgo"})
        if len(output) >= count:
            break
    return output


class DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._title_href = ""
        self._title_parts: list[str] = []
        self._capture_title = False
        self._capture_snippet = False
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key: value or "" for key, value in attrs}
        class_value = attrs_map.get("class", "")
        if tag.casefold() == "a" and "result__a" in class_value and attrs_map.get("href"):
            self._capture_title = True
            self._title_href = attrs_map.get("href", "")
            self._title_parts = []
            self._snippet_parts = []
        if "result__snippet" in class_value:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "a" and self._capture_title:
            title = " ".join(" ".join(self._title_parts).split())
            if title and self._title_href:
                self.results.append({"title": unescape(title), "url": self._title_href, "snippet": ""})
            self._capture_title = False
            self._title_href = ""
            self._title_parts = []
        if self._capture_snippet:
            snippet = " ".join(" ".join(self._snippet_parts).split())
            if snippet and self.results:
                self.results[-1]["snippet"] = unescape(snippet)
            self._capture_snippet = False
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self._title_parts.append(text)
        if self._capture_snippet:
            self._snippet_parts.append(text)


def clean_search_href(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urllib.parse.urlparse(href)
    if parsed.path == "/l/" or parsed.path.endswith("/l/"):
        values = urllib.parse.parse_qs(parsed.query).get("uddg", [])
        if values:
            return urllib.parse.unquote(values[0])
    if parsed.scheme:
        return href
    return urllib.parse.urljoin("https://duckduckgo.com", href)


def fetch_source(url: str, max_chars: int, timeout: int, config: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": str(config.get("user_agent") or "Jarvis-Research-Agent")})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("content-type", "")
        header_date = response.headers.get("date", "")
        body = response.read(max_chars * 6 + 50000)
        raw_text = body.decode("utf-8", errors="replace")
        final_url = getattr(response, "url", url)
        status = getattr(response, "status", None)
    parser = SourceMetadataParser()
    if "html" in content_type.casefold() or raw_text.lstrip().startswith("<"):
        parser.feed(raw_text)
        text = web_tools.readable_text(raw_text, content_type)
        title = parser.best_title()
    else:
        text = raw_text
        title = ""
    clean = "\n".join(line for line in (" ".join(line.split()) for line in text.splitlines()) if line)
    published_date = first_date(parser.metadata, header_date, config)
    source = {
        "source_id": short_hash(final_url),
        "ok": True,
        "url": final_url,
        "title": title or first_nonempty_line(clean)[:160],
        "publisher": publisher_from_url(final_url),
        "author": parser.metadata.get("author", ""),
        "published_date": published_date,
        "updated_date": first_metadata_value(parser.metadata, ["article:modified_time", "modified_time", "updated_time"]),
        "fetched_at": utc_now(),
        "status": status,
        "content_type": content_type,
        "truncated": len(clean) > max_chars,
        "text": clean[:max_chars],
        "text_hash": short_hash(clean),
        "snippet": clean[:360],
        "links": parser.links[:20],
    }
    return source


class SourceMetadataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.metadata: dict[str, str] = {}
        self.links: list[str] = []
        self._capture_title = False
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.casefold(): value or "" for key, value in attrs}
        tag_name = tag.casefold()
        if tag_name == "title":
            self._capture_title = True
            self._title_parts = []
        if tag_name == "meta":
            key = attrs_map.get("property") or attrs_map.get("name") or attrs_map.get("itemprop")
            content = attrs_map.get("content", "")
            if key and content:
                self.metadata[key.casefold()] = unescape(content.strip())
        if tag_name == "a" and attrs_map.get("href"):
            self.links.append(attrs_map["href"])

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "title" and self._capture_title:
            self.metadata["title"] = unescape(" ".join(" ".join(self._title_parts).split()))
            self._capture_title = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            text = " ".join(data.split())
            if text:
                self._title_parts.append(text)

    def best_title(self) -> str:
        return first_metadata_value(self.metadata, ["og:title", "twitter:title", "title"])


def score_source(source: dict[str, Any], policy: dict[str, Any], weights: dict[str, Any]) -> tuple[float, list[str]]:
    flags: list[str] = []
    score = bounded_float(weights.get("base"), 0.2, 0, 10)
    domain = publisher_from_url(str(source.get("url") or ""))
    if domain_matches_any(domain, text_list_param(policy.get("preferred_domains"))):
        score += bounded_float(weights.get("authority"), 0.35, 0, 10)
    if domain_matches_any(domain, text_list_param(policy.get("primary_domains"))):
        score += bounded_float(weights.get("primary_source"), 0.3, 0, 10)
    recency = recency_score(str(source.get("published_date") or source.get("fetched_at") or ""))
    score += recency * bounded_float(weights.get("recency"), 0.2, 0, 10)
    text = str(source.get("text") or "")
    if len(text) >= int(policy.get("minimum_text_chars") or 600):
        score += bounded_float(weights.get("content_depth"), 0.1, 0, 10)
    else:
        flags.append("thin_text")
    if not str(source.get("published_date") or "").strip():
        flags.append("missing_published_date")
        score -= bounded_float(weights.get("missing_date_penalty"), 0.08, 0, 10)
    if not str(source.get("title") or "").strip():
        flags.append("missing_title")
        score -= bounded_float(weights.get("missing_title_penalty"), 0.04, 0, 10)
    return max(0.0, score), flags


def extract_sentences(text: str, config: dict[str, Any]) -> list[str]:
    min_words = int(config.get("claim_min_words") or 8)
    max_words = int(config.get("claim_max_words") or 44)
    max_chars = int(config.get("claim_scan_chars") or 12000)
    sentences: list[str] = []
    current: list[str] = []
    for char in text[:max_chars]:
        current.append(char)
        if char in ".!?।":
            sentence = " ".join("".join(current).split())
            current = []
            words = sentence.split()
            if min_words <= len(words) <= max_words:
                sentences.append(sentence)
    if current:
        sentence = " ".join("".join(current).split())
        words = sentence.split()
        if min_words <= len(words) <= max_words:
            sentences.append(sentence)
    return sentences


def extract_entities(text: str) -> list[str]:
    entities: list[str] = []
    current: list[str] = []
    for raw in text.split():
        token = raw.strip(".,:;!?()[]{}\"'")
        if not token:
            continue
        if token[:1].isupper() or (len(token) > 1 and token.isupper()):
            current.append(token)
            continue
        if current:
            entities.append(" ".join(current))
            current = []
    if current:
        entities.append(" ".join(current))
    unique: list[str] = []
    seen: set[str] = set()
    for entity in entities:
        key = entity.casefold()
        if key not in seen and len(entity) > 1:
            seen.add(key)
            unique.append(entity)
    return unique[:12]


def clean_claim_text(text: str) -> str:
    cleaned = " ".join(text.split()).strip()
    while cleaned and cleaned[0] in "#-*•":
        cleaned = cleaned[1:].strip()
    return cleaned


def append_unique(values: list[Any], value: Any) -> None:
    if value and value not in values:
        values.append(value)


def support_for_claim(
    text: str,
    claim: dict[str, Any],
    sources: list[dict[str, Any]],
    source_by_id: dict[str, dict[str, Any]],
    threshold: float,
    minimum_shared_tokens: int,
    cross_scan: bool,
) -> list[dict[str, Any]]:
    support: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_id in claim.get("source_ids", []):
        source = source_by_id.get(str(source_id))
        if source:
            support.append(source)
            seen.add(str(source.get("source_id") or ""))
    if not cross_scan:
        return support
    for source in sources:
        source_id = str(source.get("source_id") or "")
        if source_id in seen:
            continue
        body = source_text_for_claims(source)[:12000]
        if token_overlap_count(text, body) >= minimum_shared_tokens and token_similarity(text, body) >= threshold:
            support.append(source)
            seen.add(source_id)
    return support


def confidence_from_support(domain_count: int, avg_score: float, minimum_sources: int) -> float:
    source_part = min(1.0, domain_count / max(1, minimum_sources))
    score_part = min(1.0, avg_score)
    return (source_part * 0.65) + (score_part * 0.35)


def confidence_label(score: float, domain_count: int, minimum_sources: int) -> str:
    if domain_count >= minimum_sources and score >= 0.72:
        return "high"
    if score >= 0.45:
        return "medium"
    return "low"


def timeline_from_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for claim in claims:
        rows.append({"date": claim.get("published_date", ""), "claim": claim.get("claim", ""), "confidence": claim.get("confidence", "")})
    return sorted(rows, key=lambda item: str(item.get("date") or ""))


def compact_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for index, source in enumerate(sources, start=1):
        if not source.get("ok", True):
            continue
        compact.append(
            {
                "index": index,
                "source_id": source.get("source_id", ""),
                "title": source.get("title", ""),
                "publisher": source.get("publisher", ""),
                "published_date": source.get("published_date", ""),
                "url": source.get("url", ""),
                "source_score": source.get("source_score", 0),
            }
        )
    return compact


def compact_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic": plan.get("topic", ""),
        "normalized_topic": plan.get("normalized_topic", ""),
        "mode": plan.get("mode", ""),
        "quality": plan.get("quality", ""),
        "time_window": plan.get("time_window", ""),
        "region": plan.get("region", ""),
        "language": plan.get("language", ""),
        "risk_level": plan.get("risk_level", ""),
        "source_policy": plan.get("source_policy", ""),
        "source_types": plan.get("source_types", []),
    }


def slim_evidence_pack(evidence: dict[str, Any], max_claims: int) -> dict[str, Any]:
    slim = dict(evidence)
    slim["top_claims"] = compact_claims([claim for claim in evidence.get("top_claims", []) if isinstance(claim, dict)])[:max_claims]
    slim["timeline"] = timeline_from_claims(slim["top_claims"])
    slim["uncertainty"] = [claim for claim in slim["top_claims"] if claim.get("confidence") != "high"]
    slim["source_list"] = [
        source
        for source in evidence.get("source_list", [])
        if isinstance(source, dict)
    ][: max(3, max_claims)]
    return slim


def compact_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact = []
    for claim in claims:
        compact.append(
            {
                "claim_id": claim.get("claim_id", ""),
                "claim": claim.get("claim", ""),
                "confidence": claim.get("confidence", ""),
                "confidence_score": claim.get("confidence_score", 0),
                "conflict_status": claim.get("conflict_status", ""),
                "independent_source_count": claim.get("independent_source_count", 0),
                "published_date": claim.get("published_date", ""),
                "supporting_sources": claim.get("supporting_sources", []),
            }
        )
    return compact


def report_from_evidence(evidence: dict[str, Any]) -> str:
    topic = str(evidence.get("topic") or "Research")
    time_window = str(evidence.get("time_window") or "current search window")
    lines = [f"{topic} research briefing ({time_window})", ""]
    claims = [claim for claim in evidence.get("top_claims", []) if isinstance(claim, dict)]
    if claims:
        for index, claim in enumerate(claims, start=1):
            confidence = str(claim.get("confidence") or "unknown").title()
            lines.append(f"{index}. {claim.get('claim', '')}")
            lines.append(f"   Confidence: {confidence}")
            source_text = claim_source_text(claim, evidence)
            if source_text:
                lines.append(f"   Sources: {source_text}")
            status = str(claim.get("conflict_status") or "")
            if status and status not in {"verified", "limited"}:
                lines.append(f"   Note: {status.replace('_', ' ')}")
            lines.append("")
    else:
        lines.append("No claim candidates were extracted from the fetched sources.")
        lines.append("")
    sources = [source for source in evidence.get("source_list", []) if isinstance(source, dict)]
    if sources:
        lines.append("Sources read:")
        for source in sources:
            title = str(source.get("title") or source.get("publisher") or source.get("url") or "Source")
            url = str(source.get("url") or "")
            date = str(source.get("published_date") or "")
            suffix = f" ({date})" if date else ""
            lines.append(f"- {title}{suffix}: {url}")
    return "\n".join(line.rstrip() for line in lines).strip() + "\n"


def compiler_content_from_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    topic = str(evidence.get("topic") or "Research")
    time_window = str(evidence.get("time_window") or "current search window")
    generated_at = str(evidence.get("generated_at") or utc_now())
    claims = [claim for claim in evidence.get("top_claims", []) if isinstance(claim, dict)]
    sources = [source for source in evidence.get("source_list", []) if isinstance(source, dict)]
    findings = []
    for claim in claims:
        finding = {
            "claim": claim.get("claim", ""),
            "confidence": claim.get("confidence", ""),
            "status": claim.get("conflict_status", ""),
            "sources": claim_source_text(claim, evidence),
        }
        findings.append(finding)
    timeline_items = [
        {"date": item.get("date", ""), "event": item.get("claim", "")}
        for item in evidence.get("timeline", [])
        if isinstance(item, dict)
    ]
    uncertainty = [
        {
            "claim": claim.get("claim", ""),
            "confidence": claim.get("confidence", ""),
            "status": claim.get("conflict_status", ""),
        }
        for claim in claims
        if claim.get("confidence") != "high"
    ]
    sections = [
        {
            "heading": "Summary",
            "level": 1,
            "body": f"Research briefing for {topic} covering {time_window}. Generated from current source results at {generated_at}.",
            "items": [],
            "table": None,
            "citations": [],
        },
        {
            "heading": "Key Findings",
            "level": 1,
            "body": "",
            "items": findings,
            "table": None,
            "citations": [],
        },
    ]
    if timeline_items:
        sections.append(
            {
                "heading": "Timeline",
                "level": 1,
                "body": "",
                "items": timeline_items,
                "table": None,
                "citations": [],
            }
        )
    if uncertainty:
        sections.append(
            {
                "heading": "Uncertainty",
                "level": 1,
                "body": "Claims below need more confirmation or have limited source support.",
                "items": uncertainty,
                "table": None,
                "citations": [],
            }
        )
    bibliography = []
    for index, source in enumerate(sources, start=1):
        bibliography.append(
            {
                "index": index,
                "title": source.get("title") or source.get("publisher") or source.get("url") or f"Source {index}",
                "url": source.get("url", ""),
                "publisher": source.get("publisher", ""),
                "date": source.get("published_date", ""),
            }
        )
    return {
        "title": f"{topic} Research Briefing",
        "subtitle": time_window,
        "metadata": {
            "author": "Jarvis",
            "date": generated_at,
            "topic": topic,
            "version": "1",
            "source_policy": evidence.get("source_policy", ""),
        },
        "sections": sections,
        "bibliography": bibliography,
        "appendix": [],
    }


def render_research_report(content: dict[str, Any], target_format: str, template: str, output_path: str) -> dict[str, Any]:
    from tools.registry import discover_tools

    payload = json.loads(
        discover_tools().execute(
            "compiler_render",
            {
                "content": content,
                "format": target_format,
                "template": template,
                "output_path": output_path,
            },
        )
    )
    if not payload.get("ok"):
        raise ToolInputError(str(payload.get("error") or "compiler_render failed"))
    result = payload.get("result")
    if not isinstance(result, dict):
        raise ToolInputError("compiler_render returned an invalid result")
    return result


def claim_source_text(claim: dict[str, Any], evidence: dict[str, Any]) -> str:
    sources = [source for source in claim.get("supporting_sources", []) if isinstance(source, dict)]
    if not sources:
        sources = [source for source in evidence.get("source_list", []) if isinstance(source, dict)][:2]
    parts = []
    for source in sources[:3]:
        title = str(source.get("title") or source.get("publisher") or "source")
        url = str(source.get("url") or "")
        if url:
            parts.append(f"{title} - {url}")
        else:
            parts.append(title)
    return "; ".join(parts)


def source_urls_from_params(params: dict[str, Any]) -> list[str]:
    urls = text_list_param(params.get("urls"))
    for key in ("search_results", "results"):
        value = params.get(key)
        if isinstance(value, dict):
            value = value.get("results")
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    url = str(item.get("url") or "").strip()
                    if url:
                        urls.append(url)
                elif isinstance(item, str) and item.strip():
                    urls.append(item.strip())
    unique: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url not in seen:
            seen.add(url)
            unique.append(url)
    return unique


def source_metadata_from_params(params: dict[str, Any]) -> dict[str, dict[str, str]]:
    metadata: dict[str, dict[str, str]] = {}
    for key in ("search_results", "results"):
        value = params.get(key)
        if isinstance(value, dict):
            value = value.get("results")
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            metadata[url] = {
                "title": str(item.get("title") or ""),
                "snippet": str(item.get("snippet") or ""),
                "published_date": str(item.get("published_date") or ""),
            }
    return metadata


def apply_search_metadata(source: dict[str, Any], metadata: dict[str, str]) -> dict[str, Any]:
    if not metadata:
        return source
    updated = dict(source)
    if metadata.get("title") and not str(updated.get("title") or "").strip():
        updated["title"] = metadata["title"]
    if metadata.get("published_date") and not str(updated.get("published_date") or "").strip():
        updated["published_date"] = metadata["published_date"]
    if metadata.get("snippet"):
        updated["search_snippet"] = metadata["snippet"]
    return updated


def source_text_for_claims(source: dict[str, Any]) -> str:
    parts = []
    snippet = str(source.get("search_snippet") or "").strip()
    if snippet:
        parts.append(snippet)
    body = str(source.get("text") or "").strip()
    if body:
        parts.append(body)
    return "\n".join(parts)


def source_items(params: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("ranked_sources", "sources"):
        value = params.get(key)
        if isinstance(value, dict):
            value = value.get(key) or value.get("sources") or value.get("ranked_sources")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def claim_items(params: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("claims", "verified_claims"):
        value = params.get(key)
        if isinstance(value, dict):
            value = value.get(key) or value.get("claims") or value.get("verified_claims")
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def verified_claim_items(params: dict[str, Any]) -> list[dict[str, Any]]:
    claims = claim_items(params)
    return sorted(claims, key=lambda item: item.get("confidence_score", 0), reverse=True)


def query_items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("queries")
    items: list[dict[str, Any]] = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                query = str(item.get("query") or "").strip()
                if query:
                    items.append(item)
            elif isinstance(item, str) and item.strip():
                items.append({"type": "query", "query": item.strip()})
    return items


def object_param(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text_list_param(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def bounded_float(value: Any, fallback: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = fallback
    return max(minimum, min(maximum, parsed))


def resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def load_json_file(path: Path, fallback: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(fallback)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        return dict(fallback)
    return data if isinstance(data, dict) else dict(fallback)


def save_json_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def watchlist_path(config: dict[str, Any]) -> Path:
    return resolve_path(str(config.get("watchlist_path") or "memory/research/watchlists.json"))


def append_run_log(config: dict[str, Any], entry: dict[str, Any]) -> None:
    path = resolve_path(str(config.get("run_log_path") or "memory/research/runs.jsonl"))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def merge_dicts(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def publisher_from_url(url: str) -> str:
    domain = urllib.parse.urlparse(url).netloc.casefold()
    if domain.startswith("www."):
        domain = domain[4:]
    return domain


def domain_matches_any(domain: str, candidates: list[str]) -> bool:
    clean_domain = domain.casefold()
    for candidate in candidates:
        clean_candidate = candidate.casefold()
        if clean_domain == clean_candidate or clean_domain.endswith("." + clean_candidate):
            return True
    return False


def recency_score(date_text: str) -> float:
    parsed = parse_date(date_text)
    if parsed is None:
        return 0.0
    age_days = max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)
    if age_days <= 1:
        return 1.0
    if age_days <= 7:
        return 0.85
    if age_days <= 30:
        return 0.65
    if age_days <= 180:
        return 0.35
    return 0.12


def apply_time_window_to_sources(sources: list[dict[str, Any]], time_window: str, minimum: int) -> list[dict[str, Any]]:
    days = days_from_time_window(time_window)
    if days <= 0:
        return sources
    fresh: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for source in sources:
        parsed = parse_date(str(source.get("published_date") or source.get("fetched_at") or ""))
        if parsed is None:
            fresh.append(source)
            continue
        age_days = max(0.0, (now - parsed).total_seconds() / 86400)
        if age_days <= days + 1:
            fresh.append(source)
    return fresh if len(fresh) >= minimum else sources


def days_from_time_window(text: str) -> int:
    value = text.casefold()
    number = first_integer(value)
    if "hour" in value:
        return max(1, (number + 23) // 24) if number else 1
    if "week" in value:
        return (number or 1) * 7
    if "month" in value:
        return (number or 1) * 30
    if "day" in value:
        return number or 1
    return number if number and number <= 90 else 0


def first_integer(text: str) -> int:
    digits = []
    for char in text:
        if char.isdigit():
            digits.append(char)
            continue
        if digits:
            break
    if not digits:
        return 0
    try:
        return int("".join(digits))
    except ValueError:
        return 0


def parse_date(text: str) -> datetime | None:
    value = text.strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def first_date(metadata: dict[str, str], header_date: str, config: dict[str, Any]) -> str:
    fields = text_list_param(config.get("published_date_fields"))
    for field in fields:
        value = metadata.get(field.casefold(), "")
        if value:
            return value
    return header_date


def first_metadata_value(metadata: dict[str, str], keys: list[str]) -> str:
    for key in keys:
        value = metadata.get(key.casefold(), "")
        if value:
            return value
    return ""


def first_nonempty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def normalized_key(text: str) -> str:
    return " ".join("".join(char.casefold() if char.isalnum() or char.isspace() else " " for char in text).split())


def token_similarity(left: str, right: str) -> float:
    left_tokens = set(normalized_key(left).split())
    right_tokens = set(normalized_key(right).split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens)


def token_overlap_count(left: str, right: str) -> int:
    left_tokens = set(normalized_key(left).split())
    right_tokens = set(normalized_key(right).split())
    return len(left_tokens & right_tokens)


def average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def slug_text(text: str) -> str:
    slug = "-".join("".join(char.casefold() if char.isalnum() else " " for char in text).split())
    return slug[:80] if slug else "research"


def timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]
