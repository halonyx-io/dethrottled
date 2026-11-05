"""Keep existing Python import paths usable after extracting shared modules."""
import subprocess
import sys

import pytest

from dethrottled import api_models, fetch, server, urls


@pytest.mark.parametrize("name", [
    "SearchBody", "FetchBody", "SearchFetchBody", "ResearchBody", "DocumentReadBody",
    "DocumentImageBody", "FetchJobBody", "JobReadBody", "StructureBody", "SiteBody",
    "DriveStep", "DriveBody",
])
def test_server_keeps_request_model_imports(name):
    assert getattr(server, name) is getattr(api_models, name)


def test_fetch_keeps_url_helper_import():
    assert fetch.canonical_url is urls.canonical_url


def test_url_identity_does_not_load_fetch_or_server():
    subprocess.run([
        sys.executable, "-c",
        "import sys; from dethrottled.urls import canonical_url; "
        "assert canonical_url('https://www.example.com/a') == 'https://example.com/a'; "
        "assert 'dethrottled.fetch' not in sys.modules; "
        "assert 'dethrottled.server' not in sys.modules",
    ], check=True)
