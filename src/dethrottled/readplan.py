"""Observed-gap recovery: acquire, inspect, act, reassess, retain evidence."""

import json
import os
import time
from urllib.parse import urlsplit

from . import extract
from .access import automatic_session, read_session_alias
from .challenges import classify
from .content import annotate_content, page_details, passage_excerpt, short_text
from .identity import origin


def gap(row):
    if row.get("quality") in {"failed", "thin", "suspect"}:
        return row["quality"]
    if row.get("content_status") in {"navigation_only", "image_content"}:
        return row["content_status"]
    if row.get("source_partial"):
        return "partial_capture"
    if row.get("focus_status") == "no_term_matches":
        return "focus_not_found"
    return ""


def rank(row, focus=""):
    text = row.get("_index_text", row.get("content", ""))
    matched = passage_excerpt(text, focus, min(max(len(text), 1), 120000))[1] if focus else []
    terms = len({term for e in matched for term in e.get("matched_terms", [])})
    return (bool(text) and row.get("quality") != "failed",
            row.get("content_status") not in {"navigation_only", "image_content"},
            row.get("quality") != "suspect", terms, len(text))


def article_json(text, requested):
    """Accept a primary same-document body, never arbitrary JSON or oEmbed metadata."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("link", "").rstrip("/") != requested.rstrip("/"):
        return None
    content = data.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("rendered"), str):
        return None
    parsed = extract.extract(content["rendered"], url=requested, max_chars=1000000)
    return parsed.get("text") if parsed.get("ok") else None


def recovery_budget():
    try:
        budget = float(os.getenv("DETHROTTLED_READ_PLAN_SECONDS", "30"))
    except ValueError:
        budget = 30
    return min(120, max(0, budget))


def run(url, initial, *, read, drive, options, browser_available, allow_assets=True):
    """Callbacks isolate transport/storage from this bounded policy state machine."""
    started = time.monotonic()
    budget = recovery_budget()
    deadline = started + budget
    decisions, best, seen = [], initial, set()
    focus = options.get("focus", "")

    # Another transport must not retry malformed targets or override a public
    # network-policy refusal. DNS/connect timeouts are deliberately excluded:
    # a worker may have a different resolver or a working acquisition path.
    if initial.get("failure_reason") in {
            "invalid_url", "public_target_required", "redirect_target_not_public"}:
        initial["read_plan"] = dict(
            revision=1, decisions=[], initial_gap=gap(initial), final_gap=gap(initial),
            answer_verified=False, stop_reason="terminal_target_refusal",
            render_allowed=options.get("allow_render", True), browser_configured=browser_available,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2), budget_seconds=budget)
        return initial

    # A successfully acquired document is not an HTML loading gap. Its bounded
    # parser/range/OCR continuation is exposed by workflow.guidance; navigating
    # Chromium's PDF viewer cannot recover the missing source pages or rows.
    document_read = (initial.get("quality") != "failed"
                     and initial.get("content_type") not in {None, "", "html", "text/html"}
                     and bool(initial.get("extraction")))
    if document_read:
        initial["read_plan"] = dict(
            revision=1, decisions=[], initial_gap=gap(initial), final_gap=gap(initial),
            answer_verified=False,
            stop_reason="document_continuation_required" if gap(initial) else "evidence_available",
            render_allowed=options.get("allow_render", True), browser_configured=browser_available,
            elapsed_ms=round((time.monotonic() - started) * 1000, 2), budget_seconds=budget)
        return initial

    def available():
        return time.monotonic() < deadline and len(decisions) < 6

    def attempt(action, reason, operation):
        nonlocal best
        if not available():
            return None
        at = time.monotonic()
        record = dict(action=action, reason=reason, before_quality=best.get("quality"))
        try:
            candidate = operation()
            if candidate:
                if focus:
                    canonical = candidate.get("_index_text", candidate.get("content", ""))
                    candidate["focus_status"] = ("term_matches" if passage_excerpt(
                        canonical, focus, max(1, min(len(canonical), 120000)))[1]
                        else "no_term_matches")
                adopted = rank(candidate, focus) > rank(best, focus)
                record.update(quality=candidate.get("quality"), adopted=adopted)
                record["acquisition_url"] = candidate.get("acquisition_url",
                                                           candidate.get("url"))
                if candidate.get("acquisition_attempts"):
                    record["acquisition_attempts"] = candidate["acquisition_attempts"]
                if adopted:
                    best = candidate
            else:
                record.update(adopted=False, outcome="no_eligible_evidence")
        except Exception as exc:
            # Recovery failure preserves the original evidence. No response bodies,
            # cookie values or arbitrary exception strings enter the public trace.
            candidate = None
            record.update(adopted=False, outcome="failed", error=type(exc).__name__)
        record["elapsed_ms"] = round((time.monotonic() - at) * 1000, 2)
        decisions.append(record)
        return candidate

    # Feed/oEmbed declarations remain visible, but summary/metadata is never
    # silently promoted into a complete read of the requested document.
    if gap(best):
        for alternate in initial.get("source_alternatives", [])[:8]:
            target, kind = alternate.get("url", ""), alternate.get("type", "")
            if (target in seen or target == url or origin(target) != origin(url)
                    or kind not in {"text/markdown", "application/json"}
                    or (kind == "text/markdown" and urlsplit(target).path != urlsplit(url).path)):
                continue
            seen.add(target)
            if len(seen) > 2 or not gap(best):
                break

            def publisher(target=target, kind=kind):
                candidate = read(target, dict(options, focus="", allow_render=False))
                if candidate.get("quality") == "failed":
                    return None
                if kind == "application/json":
                    text = article_json(candidate.get("_index_text", candidate.get("content")), url)
                    if not text:
                        return None
                    candidate.update(content=text, _index_text=text, content_chars=len(text),
                                     quality="ok", content_type="text/html",
                                     truncated=bool(candidate.get("source_partial")))
                    candidate["extraction"] = {**candidate.get("extraction", {}),
                                               "method": "publisher_json_content.rendered"}
                    annotated = annotate_content({"text": text})
                    candidate.update({k: v for k, v in annotated.items() if k != "text"})
                else:
                    text = candidate.get("_index_text", candidate.get("content", ""))
                    annotated = annotate_content({"text": text})
                    candidate.update({k: v for k, v in annotated.items() if k != "text"})
                candidate.update(requested_url=url,
                                 acquisition_url=candidate.get("final_url", target),
                                 url=url, parent_document_id=initial.get("document_id"),
                                 representation_relationship="publisher_declared_alternate")
                return candidate
            attempt("publisher_alternate", gap(best), publisher)

    # Existing renderer recovery is a distinct strategy; never repeat it blindly.
    if (gap(best) == "navigation_only" and options.get("allow_render", True)
            and not best.get("acquisition", {}).get("rendered")):
        attempt("render", "navigation_only", lambda: read(
            url, dict(options, render_first=True, headed_fallback=True)))

    # Asset readers retain their existing format/OCR policy and range semantics.
    if gap(best) == "image_content" and allow_assets:
        for asset in best.get("assets", [])[:2]:
            if asset.get("kind") not in {"image", "document"}:
                continue
            def asset_read(asset=asset):
                child_options = {k: v for k, v in options.items() if k not in {
                    "wait_for", "render_first", "page_start", "page_end", "row_start",
                    "row_end", "sheet", "max_cell_chars"}}
                child = read(asset["url"], child_options)
                child.update(parent_url=url, parent_document_id=initial.get("document_id"))
                return child
            attempt("read_asset", "image_content", asset_read)
            if not gap(best):
                break

    hard_wall = any(a.get("tier") == "headed" and a.get("outcome") in {"challenge", "failed"}
                    for a in initial.get("acquisition_attempts", []))
    if (gap(best) and gap(best) != "image_content" and available() and browser_available
            and options.get("allow_render", True) and not hard_wall):
        from .research import browser_public
        public = browser_public(url, options.get("public_only", False))
        alias = read_session_alias(url, public)
        session = automatic_session(str(options.get("evidence_namespace", "local")), alias)
        body = dict(session=session, allowed_hosts=[urlsplit(url).hostname],
                    public_only=public, screenshot="never",
                    navigation_wait="commit")
        state = {}

        def observe(steps, navigate=False):
            remaining = max(1, deadline - time.monotonic())
            payload = dict(body, steps=[*steps, {"action": "read_state"},
                {"action": "html", "selector": state.get("main_selector", "html"),
                 "max_chars": 120000}], timeout_ms=max(1000, int(min(remaining, 12) * 1000)))
            if navigate:
                payload["url"] = url
            result = drive(payload, timeout=min(remaining + 1, 14))
            if not result.get("ok"):
                return None
            navigation = next((s.get("data") or {} for s in result.get("steps", [])
                               if s.get("action") == "goto"), {})
            if navigation.get("status", 200) >= 400:
                state.update(challenge=True, http_status=navigation["status"])
                return None
            for step in result.get("steps", []):
                if step.get("action") == "read_state" and isinstance(step.get("data"), dict):
                    state.update(step["data"])
            html = next((s.get("data") for s in reversed(result.get("steps", []))
                         if s.get("action") == "html" and isinstance(s.get("data"), str)), "")
            html_partial = any(s.get("truncated") for s in result.get("steps", [])
                               if s.get("action") == "html")
            if classify(html):
                state["challenge"] = True
                return None
            parsed = extract.extract(html, url=url, max_chars=1000000)
            text = parsed.get("text", "") or short_text(html).strip()
            method = 'browser_read_plan'
            partial = any(s.get("truncated") for s in result.get("steps", []))
            if (partial or len(text) < 600) and available():
                remaining = max(1, deadline - time.monotonic())
                try:
                    rendered = drive(dict(body, steps=[{'action': 'text', 'selector': 'body',
                        'max_chars': 120000}], timeout_ms=int(min(remaining, 5) * 1000)),
                        timeout=min(remaining + 1, 6))
                except Exception as exc:
                    rendered = {}
                    state['visible_text_error'] = type(exc).__name__
                snapshot = next((s for s in rendered.get('steps', [])
                    if s.get('action') == 'text' and s.get('ok')), {})
                visible = snapshot.get('data', '')
                if isinstance(visible, str) and len(visible) > len(text) and not classify(visible):
                    text, method = visible, 'browser_visible_text'
                    partial = bool(snapshot.get('truncated'))
            if not text:
                return None
            row = dict(url=url, final_url=result.get("final", {}).get("url", url),
                       content=text, _index_text=text, content_chars=len(text),
                       quality="ok" if len(text) >= 600 else "thin", tier="headed/read-plan",
                       title=parsed.get("title", ""), content_type="text/html", cached=False,
                       source_partial=partial, truncated=partial,
                       extraction={"partial": partial, "method": method,
                                   "completeness": (parsed.get("completeness", {})
                                       if method == "browser_read_plan" else
                                       {"status": "unverified", "assessment": "visible_text"})},
                       acquisition={"rendered": True, "method": "browser_read_plan"},
                       warnings=["Autonomous browser read; source completeness unverified.",
                                 *(parsed.get("warnings", [])
                                   if method == "browser_read_plan" else []),
                                 *(["Visible-text fallback failed: " + state["visible_text_error"]]
                                   if state.get("visible_text_error") else []),
                                 *(["Visible text may include navigation, ads and related content."]
                                   if method == "browser_visible_text" else [])],
                       **{k: v for k, v in page_details(html, url).items() if k != "warnings"})
            annotated = annotate_content({"text": text, "extraction": row["extraction"]}, html)
            row.update({k: v for k, v in annotated.items() if k != "text"})
            if options.get("retain_html"):
                row["_selector_html"] = html
                row["_selector_html_partial"] = html_partial
            if focus:
                row["focus_status"] = ("term_matches" if passage_excerpt(
                    text, focus, min(len(text), 120000))[1] else "no_term_matches")
            return row

        attempt("browser_inspect", gap(best), lambda: observe([], navigate=True))
        if state.get("challenge") and decisions:
            decisions[-1]["diagnosis"] = "challenge_or_http_refusal"
            if state.get("http_status"):
                decisions[-1]["http_status"] = state["http_status"]
        if state.get("loading") or state.get("ready_state") == "loading":
            attempt("wait_loading", "observed_loading", lambda: observe([
                {"action": "wait", "ms": 700}]))
        if not state.get("challenge") and gap(best) and state.get("expandable_details"):
            attempt("expand_details", "observed_closed_details", lambda: observe([
                {"action": "expand_details", "limit": 2, "ms": 1500},
                {"action": "wait", "ms": 300}]))
        if not state.get("challenge") and gap(best) and state.get("scroll_remaining", 0) > 0:
            attempt("scroll", "observed_scrollable_gap", lambda: observe([
                {"action": "scroll", "value": "down"}, {"action": "wait", "ms": 500}]))
        if state and not state.get("challenge") and gap(best) and available():
            def network_article():
                listing = drive(dict(body, steps=[{"action": "network", "limit": 3}],
                                     timeout_ms=2000), timeout=3)
                responses = next((s.get("data", {}).get("responses", [])
                                  for s in listing.get("steps", [])
                                  if s.get("action") == "network"), [])
                for response in responses[-3:]:
                    target = response.get("url", "")
                    if (origin(target) != origin(url) or response.get("status") != 200
                            or "json" not in response.get("content_type", "")):
                        continue
                    capture = drive(dict(body, steps=[{"action": "network", "name": "body",
                        "selector": response["response_id"], "max_chars": 120000}],
                        timeout_ms=2000), timeout=3)
                    data = next((s.get("data", {}) for s in capture.get("steps", [])
                                 if s.get("action") == "network" and s.get("ok")), {})
                    if data.get("truncated"):
                        continue
                    text = article_json(data.get("content", ""), url)
                    if not text:
                        continue
                    annotation = annotate_content({"text": text})
                    return dict(url=url, requested_url=url, acquisition_url=target,
                        content=text, _index_text=text, content_chars=len(text),
                        quality=annotation.get("quality", "ok"),
                        tier="headed/network-article", content_type="text/html", cached=False,
                        content_status="complete", source_partial=False, truncated=False,
                        extraction={"method": "observed_primary_json_body"},
                        acquisition={"rendered": True, "method": "observed_network_response"},
                        warnings=["Primary body from an observed same-origin JSON response; "
                                  "answer and source completeness unverified."],
                        content_assessment=annotation["content_assessment"])
                return None
            attempt("network_article", "unresolved_browser_gap", network_article)
        # Checkpoint is not a content strategy and does not replay mutations.
        if available() and state and not state.get("challenge"):
            try:
                drive(dict(body, steps=[{"action": "checkpoint"}], timeout_ms=2000), timeout=3)
            except Exception:
                pass
    if best is not initial and initial.get("document_id"):
        best["evidence_variants"] = [{k: initial[k] for k in (
            "document_id", "document_sha256", "url", "quality", "tier", "content_chars",
            "content_status", "source_partial") if k in initial}]
        best.setdefault("warnings", []).append(
            "Recovery selected another representation; the original extraction remains "
            "available through evidence_variants and may contain different material.")
    if best is not initial:
        best["acquisition_attempts"] = [
            *[dict(a, url=url) for a in initial.get("acquisition_attempts", [])],
            *best.get("acquisition_attempts", [])]
    best["read_plan"] = dict(revision=1, decisions=decisions, initial_gap=gap(initial),
        final_gap=gap(best), answer_verified=False,
        stop_reason=("budget_exhausted" if time.monotonic() >= deadline else
                     "action_limit" if len(decisions) >= 6 else
                     "unresolved_gap" if gap(best) else "evidence_available"),
        render_allowed=options.get("allow_render", True), browser_configured=browser_available,
        elapsed_ms=round((time.monotonic() - started) * 1000, 2), budget_seconds=budget)
    if (any(d["action"] == "browser_inspect" for d in decisions)
            or any(a.get("tier") == "headed" for a in initial.get("acquisition_attempts", []))):
        from .research import browser_public
        best["read_plan"]["browser_session"] = {
            "id": read_session_alias(url, browser_public(url, options.get("public_only", False))),
            "allowed_hosts": [urlsplit(url).hostname], "url": url}
    if decisions:
        best["recovery_attempts"] = decisions
    return best
