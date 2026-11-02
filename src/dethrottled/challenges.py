"""Recognize interstitials without treating vendor mentions as blocked content."""

import re

from .content import short_text

VENDORS = {
    "cloudflare": ("cf-challenge", "cf-chl-", "challenge-platform", "just a moment"),
    "datadome": ("datadome", "captcha-delivery.com", "ddm-"),
    "perimeterx": ("px-captcha", "captcha.px-cdn.net", "press & hold"),
    "akamai": ("sec-if-cpt-container", "reference #"),
    "imperva": ("incapsula", "_incap_", "incident id"),
}
PROMPTS = (
    "verification required",
    "prove your humanity",
    "please wait while we verify",
    "verify you are human",
    "verifying you are human",
    "performing security verification",
    "checking your browser",
    "enable javascript and cookies to continue",
    "enable js and disable any ad blocker",
    "complete the security check",
    "we must verify your session before you can proceed",
    "access to this page has been denied",
    "press & hold",
)


def classify(body, headers=None):
    try:
        if "challenge" in str((headers or {}).get("cf-mitigated", "")).lower():
            return "cloudflare"
    except (AttributeError, TypeError):
        pass
    head = (body or "")[:30000]
    lower = head.lower()
    visible = short_text(head) if "<" in head else head
    visible = " ".join(visible.split()).lower()
    title = re.search(r"<title[^>]*>(.*?)</title>", lower, re.S)
    title = " ".join(title[1].split()) if title else ""
    # A specific observed login gate, not login links embedded in a real page.
    plain = re.sub(r"\[[^\]]*\]\([^)]*\)", " ", visible)
    plain = re.sub(r"[\s#]+", " ", plain).strip()
    if (len(visible) < 3000
            and (plain.startswith(("log in to use old reddit",
                                   "skip to main content log in to use old reddit"))
                 or (title == "welcome to reddit"
                     and "log in to use old reddit" in plain[:400]))
            and "accounts are required to access old reddit" in plain[:700]):
        return "login_required"
    # Active challenge markup plus a small interstitial, not ordinary JS detection
    # scripts embedded in full articles or documentation about bot defenses.
    brief = len(visible) < 1000
    prompt = any(p in visible for p in PROMPTS)
    active = bool(
        re.search(
            r"<(?:script|iframe)[^>]+(?:captcha|orchestrate|anomaly)|"
            r"(?:id|class)=[\"'][^\"']*captcha",
            lower,
        )
    )
    starts_prompt = visible.startswith(PROMPTS)
    titled = title.startswith(("just a moment", "verification required", "security check",
                                  "reddit - prove your humanity"))
    # Observed Expedia wall: neither HTTP 429 nor "human side" alone suffices.
    if (brief and visible.startswith("show us your human side")
            and "can't tell if you're a human or a bot" in visible):
        return "generic"
    for vendor, markers in VENDORS.items():
        if (
            any(marker in lower for marker in markers)
            and brief
            and (titled or starts_prompt or (active and prompt))
        ):
            return vendor
    if brief and (titled or visible.startswith(PROMPTS)):
        return "generic"
    if brief and ("anomaly.js" in lower or 'id="px-captcha"' in lower):
        return "generic"
    return ""
