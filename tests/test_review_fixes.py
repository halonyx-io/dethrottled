"""Invalid URL handling, truthful version identity and bounded tier defaults."""
import pathlib

import pytest

from dethrottled import __version__, server
from dethrottled import fetch as f

# ── a mistyped URL is not a robots decision ──────────────────────────────────

@pytest.mark.parametrize("bad", [
    "not a url", "https://", "htp:/broken", "", "   ", "ftp://files.example/x",
    "javascript:alert(1)", "file:///etc/passwd",
])
def test_unfetchable_urls_are_rejected_as_invalid(bad):
    assert f.valid_url(bad) is False


@pytest.mark.parametrize("good", [
    "https://example.com/", "http://example.com/a?b=c",
    "https://sub.example.co.uk/path#frag",
])
def test_real_urls_pass(good):
    assert f.valid_url(good) is True


def test_a_malformed_url_says_so():
    result = f.fetch_and_extract("not a url")
    assert result["ok"] is False
    assert result["reason"] == "invalid_url"


# ── one version, not three ───────────────────────────────────────────────────

def test_the_api_reports_the_real_version():
    """server.py hardcoded 0.1.0 while the package said 0.1.2, so /health and
    /v2/capabilities advertised a version the software had not been for two
    releases -- and a reviewer duly wrote it up as early-stage."""
    assert server.VERSION == __version__


def test_the_version_is_declared_in_exactly_one_place():
    import re
    src = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    assert not re.search(r'VERSION\s*=\s*[\'"]\d+\.\d+', src), \
        "the version must be imported, never restated"



def test_no_module_hardcodes_a_version_number():
    """The check above only guarded server.py, so the identical mistake sat in
    fetch.py the whole time: the User-Agent said "dethrottled/0.1" while the
    package was 0.2.0. Guard every module, not the one that was caught."""
    import re
    pkg = pathlib.Path(server.__file__).parent
    offenders = []
    for path in sorted(pkg.glob("*.py")):
        if path.name == "__init__.py":
            continue          # the one legitimate home for the number
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            code = line.split("#", 1)[0]
            if "version" not in code.lower() and "dethrottled/" not in code:
                continue
            if re.search(r'["\'][^"\']*\b\d+\.\d+\.?\d*', code):
                offenders.append("%s:%d %s" % (path.name, number, line.strip()))
    assert not offenders, (
        "version restated instead of imported:\n" + "\n".join(offenders))


def test_the_user_agent_is_actually_contactable():
    """It shipped with the templating placeholder still in it, so every request
    we made announced a URL that 404s. An unreachable contact address is not a
    contact address, and this is the string that asks to be told to stop."""
    assert "DETHROTTLED_GITHUB_USER" not in f.PROJECT_URL
    assert f.PROJECT_URL.startswith("https://github.com/")
    assert __version__ in f.USER_AGENT


def test_an_empty_user_agent_setting_uses_the_default():
    """Compose passes DETHROTTLED_USER_AGENT="" when the operator sets nothing.
    That must mean the versioned default, not an anonymous request; a
    hard-coded Compose default went stale on every release."""
    import os
    import subprocess
    import sys
    env = {**os.environ, "DETHROTTLED_USER_AGENT": ""}
    agent = subprocess.run(
        [sys.executable, "-c", "from dethrottled import fetch; print(fetch.USER_AGENT)"],
        env=env, capture_output=True, text=True, check=True).stdout.strip()
    assert agent.startswith(f"dethrottled/{__version__} (+https://")
