#!/usr/bin/env python3
"""Manage a hash registry without accepting plaintext tokens in process args."""
import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry', default='/etc/dethrottled-access/tokens.json')
    parser.add_argument('action', choices=['list', 'add', 'revoke', 'restore'])
    parser.add_argument('label', nargs='?')
    parser.add_argument('--scopes', default='web', help='comma-separated web,drive,corpus')
    args = parser.parse_args()
    path = Path(args.registry)
    data = json.loads(path.read_text()) if path.exists() else {'tokens': []}
    if args.action == 'list':
        for item in data['tokens']:
            print(item.get('label', 'client'), 'revoked' if item.get('revoked') else 'active',
                  ','.join(item.get('scopes', [])))
        return
    if not args.label:
        parser.error('label is required')
    matches = [item for item in data['tokens'] if item.get('label') == args.label]
    if args.action == 'add':
        scopes = args.scopes.split(',')
        if matches or not set(scopes) <= {'web', 'drive', 'corpus'}:
            parser.error('label must be unique and scopes must be web,drive,corpus')
        token = sys.stdin.readline().strip()
        if len(token) < 24:
            parser.error('provide a token of at least 24 characters through stdin')
        digest = hashlib.sha256(token.encode()).hexdigest()
        if any(item['sha256'] == digest for item in data['tokens']):
            parser.error('token already registered')
        data['tokens'].append({'label': args.label, 'sha256': digest, 'scopes': scopes})
    else:
        if not matches:
            parser.error('unknown label')
        for item in matches:
            item['revoked'] = args.action == 'revoke'
    # Administrators serialize edits. Preserve the service group's read access.
    info = path.stat() if path.exists() else None
    fd, name = tempfile.mkstemp(prefix='.tokens-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), 0o640)
            if info:
                os.fchown(output.fileno(), info.st_uid, info.st_gid)
            json.dump(data, output, indent=2)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    print(args.label, args.action)


if __name__ == '__main__':
    main()
