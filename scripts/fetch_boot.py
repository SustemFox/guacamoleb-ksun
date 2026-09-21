#!/usr/bin/env python3
"""
Fetch the official LineageOS boot.img for guacamoleb.

Usage:
    fetch_boot.py <lineageos-api-url-or-direct-boot-url> <output.img>

If given a LineageOS v2 device API endpoint
(https://download.lineageos.org/api/v2/devices/guacamoleb/builds), the newest
build is selected and its `boot.img` file is downloaded.

A direct URL ending in .img is downloaded as-is.
"""
import json
import ssl
import sys
import urllib.request


UA = {'User-Agent': 'guacamoleb-ci/1.0'}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=120, context=ctx) as r:
        return r.read()


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    src, out = sys.argv[1], sys.argv[2]

    if src.endswith('.img'):
        boot_url = src
    else:
        data = json.loads(get(src))
        if not isinstance(data, list) or not data:
            print('ERROR: unexpected API response', file=sys.stderr)
            return 1
        build = data[0]
        boot_url = None
        for f in build.get('files', []):
            if f.get('filename') == 'boot.img':
                # The API returns relative paths under `url`.
                boot_url = f.get('url') or f.get('path')
                break
        if not boot_url:
            print('ERROR: boot.img not found in build %s' % build.get('date'),
                  file=sys.stderr)
            return 1
        if boot_url.startswith('/'):
            boot_url = 'https://download.lineageos.org' + boot_url
        elif not boot_url.startswith('http'):
            boot_url = 'https://download.lineageos.org/' + boot_url.lstrip('/')
        print('build date: %s' % build.get('date'))

    print('downloading %s' % boot_url)
    blob = get(boot_url)
    with open(out, 'wb') as f:
        f.write(blob)
    print('wrote %s (%d bytes)' % (out, len(blob)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
