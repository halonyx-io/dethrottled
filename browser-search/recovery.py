"""Small observed navigation recipes; no credentials or cross-origin cookie transfer."""
import re
from urllib.parse import urlsplit


def navigation_recipe(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if parsed.scheme not in {'http', 'https'} or parsed.username or not (
            host == 'reddit.com' or host.endswith('.reddit.com')):
        return None
    # Crawl4AI sets this preference before HTTP navigation. Controlled ablation
    # recovered the native Patchright browser without changing its fingerprint.
    return {'name': 'reddit_cookie_preference',
            'cookie': {'name': 'cookiesEnabled', 'value': 'true',
                       'url': f'{parsed.scheme}://{parsed.netloc}/'},
            'settle_ms': 5000}


def assess_access(text, title='', url=''):
    visible = ' '.join(text.split()).lower()
    title = title.lower().strip()
    status, reason = 'unknown', 'no_clear_content_signal'
    if (len(visible) < 3000 and (
            title.startswith(('just a moment', 'reddit - prove your humanity',
                              'verification required', 'security check')) or
            visible.startswith(('prove your humanity', 'verify you are human',
                                'verifying you are human', 'checking your browser',
                                'show us your human side', 'access denied')))):
        status, reason = 'challenge', 'observed_verification_interstitial'
    elif ('log in to use old reddit' in visible[:300]
          and 'accounts are required to access old reddit' in visible[:700]
          and (urlsplit(url).path.startswith('/login') or title == 'welcome to reddit')):
        status, reason = 'login_required', 'observed_login_interstitial'
    elif (urlsplit(url).path.rstrip('/').endswith(('/login', '/signin'))
          and re.match(r'^(?:skip to main content )?(?:log in|sign in)\b', visible)
          and len(visible) < 1500 and 'password' in visible):
        status, reason = 'login_required', 'observed_login_form'
    elif len(visible) >= 200:
        status, reason = 'content_observed', 'visible_text_present'
    return {'status': status, 'reason': reason, 'answer_verified': False,
            'source_complete': False}
