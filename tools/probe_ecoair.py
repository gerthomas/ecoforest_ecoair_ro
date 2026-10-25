#!/usr/bin/env python3
"""Read-only probe for an Ecoforest Easynet gateway. Standard library only.

Sends only the whitelisted block reads (and one address read used to recognise ecoGEO
controllers) and prints the raw replies, so you can check what your unit returns before
installing the integration. Nothing here can write to the heat pump.

    ECOFOREST_URL=http://192.168.1.200 ECOFOREST_USER=<serial> ECOFOREST_PASSWORD=<8 chars> \
        python3 tools/probe_ecoair.py

Sensitive values are not printed; the password and serial number are never echoed.
"""
import base64
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

BLOCK_OPERATIONS = (2125, 2148, 2149, 2150, 2151, 2103, 2104, 2108)
GEO_MODEL_READ = {"idOperacion": 2002, "dir": 5323, "num": 6}


def post(base, auth, data):
    allowed = [{"idOperacion": op} for op in BLOCK_OPERATIONS] + [GEO_MODEL_READ]
    if data not in allowed:
        raise SystemExit(f"refusing to send {data!r}")
    request = urllib.request.Request(
        base.rstrip("/") + "/recepcion_datos_4.cgi",
        data=urllib.parse.urlencode(data).encode(),
        headers={"Authorization": "Basic " + auth},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode(errors="replace")
    except urllib.error.HTTPError as err:
        return err.code, err.read().decode(errors="replace")
    except OSError as err:
        return None, f"connection failed: {err}"


def main():
    try:
        base = os.environ["ECOFOREST_URL"]
        user = os.environ["ECOFOREST_USER"]
        password = os.environ["ECOFOREST_PASSWORD"]
    except KeyError as err:
        sys.exit(f"set {err.args[0]} (see the docstring)")
    auth = base64.b64encode(f"{user}:{password}".encode()).decode()
    for data in [GEO_MODEL_READ] + [{"idOperacion": op} for op in BLOCK_OPERATIONS]:
        status, text = post(base, auth, data)
        print(f"--- {data} -> HTTP {status}")
        print(text.strip() or "(empty)")
        if status in (401, 403):
            sys.exit("authentication failed; check the serial number and password")
        if status is None:
            sys.exit(1)


if __name__ == "__main__":
    main()
