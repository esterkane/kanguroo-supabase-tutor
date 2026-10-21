#!/usr/bin/env python3
"""Local dev learner for the tutor: sign up (once) and sign in against the LOCAL Supabase Auth.

Credentials are generated on first use and kept only in .env (gitignored) as TUTOR_DEV_EMAIL /
TUTOR_DEV_PASSWORD. Refuses any non-local API_URL. Email confirmation is off in supabase/config.toml.

Usage:
  uv run python scripts/dev_user.py                 # ensure the user exists, print its id
  uv run python scripts/dev_user.py --print-token   # print a fresh access token (for curl)
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def ensure_credentials() -> tuple[str, str]:
    email, password = os.environ.get("TUTOR_DEV_EMAIL"), os.environ.get("TUTOR_DEV_PASSWORD")
    if email and password:
        return email, password
    email = "dev-learner@example.test"
    password = secrets.token_urlsafe(18)
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    lines = [ln for ln in lines if not ln.startswith(("TUTOR_DEV_EMAIL=", "TUTOR_DEV_PASSWORD="))]
    lines += ["# local dev learner for scripts/dev_user.py (local Supabase only)",
              f"TUTOR_DEV_EMAIL={email}", f"TUTOR_DEV_PASSWORD={password}"]
    ENV.write_text("\n".join(lines) + "\n")
    print(f"generated dev learner credentials in {ENV.name} (gitignored)", file=sys.stderr)
    return email, password


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--print-token", action="store_true", help="print a fresh access token to stdout")
    args = ap.parse_args()

    api_url = os.environ.get("API_URL") or sys.exit("API_URL missing: run `make env` and source .env.local")
    if urlparse(api_url).hostname not in LOCAL_HOSTS:
        sys.exit(f"refusing non-local Supabase Auth at {api_url}")
    apikey = os.environ.get("PUBLISHABLE_KEY") or os.environ["ANON_KEY"]
    headers = {"apikey": apikey, "Content-Type": "application/json"}
    email, password = ensure_credentials()

    with httpx.Client(base_url=f"{api_url}/auth/v1", headers=headers, timeout=10) as auth:
        res = auth.post("/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        if res.status_code == 400:  # unknown user: sign up once, then sign in
            auth.post("/signup", json={"email": email, "password": password}).raise_for_status()
            res = auth.post("/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        res.raise_for_status()
        session = res.json()
    if args.print_token:
        print(session["access_token"])
    else:
        print(f"dev learner ready: {session['user']['id']} ({email})")


if __name__ == "__main__":
    main()
