"""Same bounded navigation fixtures against the released/candidate crawler."""
import argparse
import json

from dethrottled.site import crawl


def navigation(url):
    if url.endswith('/index'):
        return {'quality': 'thin', 'html': '<a href="/report">Read report</a>',
                'warnings': ['Short index; evidence coverage unverified']}
    return {'quality': 'ok', 'content': 'The report records 47 items.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    result = crawl(['https://fixture.example/index'], navigation, max_pages=3)
    failed = crawl(['https://fixture.example/'], lambda _: {
        'quality': 'failed', 'failure_reason': 'controlled_network_failure'})
    print(json.dumps({'label': args.label, 'thin_navigation': result,
                      'failed_seed': failed}, indent=2))
