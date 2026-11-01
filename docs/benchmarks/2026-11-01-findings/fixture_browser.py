# Evaluation-only exact fixture policy; never deploy this wrapper.
from urllib.parse import urlsplit

import service

original = service._public_network_target


async def fixture_public(url):
    host = urlsplit(url).hostname
    if host in {"dethrottled-findings-fixture", "dethrottled-findings-frame"}:
        return True
    return await original(url)


service._public_network_target = fixture_public
app = service.app
