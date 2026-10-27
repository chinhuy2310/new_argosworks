"""
webhook_dispatcher.py — Enterprise Outgoing Webhook Dispatcher
Dispatches notifications asynchronously to Slack, Microsoft Teams, Discord, Telegram, or custom webhook URLs.
"""

import os
import json
import threading
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

from utils.ssrf import validate_external_url

_ALLOWED_SCHEMES = ("http", "https")


def validate_webhook_target(url: str):
    """
    Validates an outgoing webhook target BEFORE any request is made.

    Returns (ok, reason):
      * "invalid_url"    — empty / not a string
      * "invalid_scheme" — file://, ftp://, javascript: ... (urllib would accept file://)
      * "blocked_host"   — loopback / private / link-local (169.254.169.254) / multicast
      * ""               — allowed

    SSRF note: ``urllib.request`` supports ``file://`` and silently follows redirects.
    The check therefore runs here and again on every redirect target
    (``_ValidatedRedirectHandler``). The webhook URL is admin-configurable at runtime
    through /api/settings (which validates it too), so this is the last line of
    defense for values injected straight into .env / the process environment.
    """
    if not url or not isinstance(url, str) or not url.strip():
        return False, "invalid_url"

    candidate = url.strip()
    scheme = (urllib.parse.urlsplit(candidate).scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False, "invalid_scheme"

    try:
        validate_external_url(candidate, allow_private=False, require_https=False)
    except ValueError:
        return False, "blocked_host"
    return True, ""


class _ValidatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validates every redirect target so an allowed host cannot 302 to an internal IP."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        ok, _reason = validate_webhook_target(newurl)
        if not ok:
            return None  # -> urllib raises HTTPError; the new target is never contacted
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_ValidatedRedirectHandler())


def _send_http_post(url: str, payload: Dict[str, Any], timeout: int = 5) -> Optional[str]:
    # SSRF / scheme gate: never fall through to urlopen for a rejected target.
    ok, reason = validate_webhook_target(url)
    if not ok:
        print(f"[Webhook] Skipped webhook target ({reason})")
        return reason
    try:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json; charset=utf-8",
                "User-Agent": "ARGOS-WORKS-Webhook/2.0"
            },
            method="POST"
        )
        with _OPENER.open(req, timeout=timeout) as resp:
            pass
        return None
    except Exception as e:
        # Non-blocking: never crash application if external webhook fails
        # Mask webhook URL in logs to prevent token/secret leakage
        try:
            parsed_u = urllib.parse.urlsplit(url)
            masked_url = f"{parsed_u.scheme}://{parsed_u.netloc}/***"
        except Exception:
            masked_url = "***"
        print(f"[Webhook] Dispatch to {masked_url} failed: {e}")
        return str(e)

def format_slack_payload(title: str, content: str, sender: str, link_id: str = "", tag: str = "") -> Dict[str, Any]:
    """Formats payload for Slack Incoming Webhook."""
    color = "#3b82f6"  # Blue default
    if tag in ("지연", "urgent"):
        color = "#ef4444"  # Red
    elif tag in ("D-Day", "마감"):
        color = "#f59e0b"  # Amber
    elif tag in ("완료", "done"):
        color = "#10b981"  # Green

    return {
        "text": f"*{title}*\n{content}",
        "attachments": [
            {
                "color": color,
                "fields": [
                    {"title": "Sender", "value": sender, "short": True},
                    {"title": "Tag", "value": tag or "Info", "short": True},
                    {"title": "Task ID", "value": str(link_id), "short": True}
                ]
            }
        ]
    }

def format_teams_payload(title: str, content: str, sender: str, link_id: str = "", tag: str = "") -> Dict[str, Any]:
    """Formats payload for Microsoft Teams Office 365 Connector Webhook."""
    theme_color = "0076D7"
    if tag in ("지연", "urgent"):
        theme_color = "D83B01"
    elif tag in ("D-Day", "마감"):
        theme_color = "FFB900"
    elif tag in ("완료", "done"):
        theme_color = "107C41"

    return {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": theme_color,
        "summary": title,
        "sections": [{
            "activityTitle": f"🔔 {title}",
            "activitySubtitle": f"From: {sender} | Tag: {tag or 'Notice'}",
            "text": content,
            "facts": [
                {"name": "Task ID:", "value": str(link_id)}
            ]
        }]
    }

def dispatch_notification_webhook(title: str, content: str, sender: str = "ARGOS", link_id: str = "", tag: str = ""):
    """
    Checks environment for webhook URLs and dispatches event in a background thread.
    Supported env vars:
      - SLACK_WEBHOOK_URL
      - TEAMS_WEBHOOK_URL
      - GENERIC_WEBHOOK_URL
    """
    slack_url = os.environ.get("SLACK_WEBHOOK_URL")
    teams_url = os.environ.get("TEAMS_WEBHOOK_URL")
    generic_url = os.environ.get("GENERIC_WEBHOOK_URL")

    if not (slack_url or teams_url or generic_url):
        return

    def _worker():
        if slack_url:
            _send_http_post(slack_url, format_slack_payload(title, content, sender, link_id, tag))
        if teams_url:
            _send_http_post(teams_url, format_teams_payload(title, content, sender, link_id, tag))
        if generic_url:
            _send_http_post(generic_url, {
                "event": "notification.created",
                "title": title,
                "content": content,
                "sender": sender,
                "link_id": link_id,
                "tag": tag
            })

    threading.Thread(target=_worker, daemon=True, name="WebhookDispatch").start()
