#!/usr/bin/env python3
"""Read-only probe for an Ecoforest Easynet gateway (standard library only).

Usage:
    ECOFOREST_URL=http://192.168.1.200 ECOFOREST_USER=<serial> ECOFOREST_PASSWORD=<first 8 chars> \
        python3 tools/probe.py

Sends only read requests: the ecoAIR block reads (2103, 2104, 2108, 2125, 2148-2151) and one
ecoGEO register read (2002, address 5323, 6 registers = model code). Prints the raw replies so
the register layout can be checked against your unit. Credentials are never printed.
"""
import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ECOAIR_OPS = (2125, 2148, 2149, 2150, 2151, 2103, 2104, 2108)
ALLOWED = [{'idOperacion': op} for op in ECOAIR_OPS] + [{'idOperacion': 2002, 'dir': 5323, 'num': 6}]


def post(base, auth, data):
    if data not in ALLOWED:
        raise SystemExit(f'refusing to send {data!r}: not a whitelisted read')
    req = urllib.request.Request(
        base.rstrip('/') + '/recepcion_datos_4.cgi',
        data=urllib.parse.urlencode(data).encode(),
        headers={'Authorization': 'Basic ' + auth})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.read().decode(errors='replace')
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors='replace')
    except (urllib.error.URLError, OSError) as err:
        return None, f'connection failed: {err}'


def main():
    try:
        base, user, password = (os.environ[k] for k in ('ECOFOREST_URL', 'ECOFOREST_USER', 'ECOFOREST_PASSWORD'))
    except KeyError as err:
        raise SystemExit(f'set {err.args[0]} (see the docstring)')
    auth = base64.b64encode(f'{user}:{password}'.encode()).decode()
    for data in ALLOWED:
        status, text = post(base, auth, data)
        print(f'=== request {data} -> HTTP {status}')
        print(text.strip() or '(empty)')
        print()
        if status in (401, 403):
            raise SystemExit('authentication rejected; check serial number and password')


if __name__ == '__main__':
    sys.exit(main())
