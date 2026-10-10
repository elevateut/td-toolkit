#!/usr/bin/env python3
"""DGS (Disc Golf Scene) authentication script.

Logs into discgolfscene.com, captures Set-Cookie headers, and saves
the session cookies to ~/.dgs-cookies.json for use by dgs-tournament.py
and pdga.py.

This is the replacement for the old /tmp/dgs-grab-cookies.py grabber.
Re-run whenever cookies expire (DGS returns HTML instead of expected data).

Usage:
    # With env vars (DGS_EMAIL, DGS_PASSWORD in .env):
    python3 dgs-auth.py

    # With explicit credentials:
    python3 dgs-auth.py --email you@example.com --password yourpass

    # Show cookies without saving:
    python3 dgs-auth.py --dry-run

    # Save to a custom path:
    python3 dgs-auth.py --output /tmp/my-cookies.json

    # Also update .env file with new cookie values:
    python3 dgs-auth.py --update-env /path/to/.env

Dependencies: Python stdlib only (no pip installs).
"""

import argparse
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DGS_BASE = "https://www.discgolfscene.com"
DGS_SIGN_IN = f"{DGS_BASE}/auth/sign-in"
DEFAULT_COOKIE_PATH = Path(os.environ.get("DGS_COOKIE_FILE") or Path.home() / ".dgs-cookies.json").expanduser()
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def _error(msg):
    json.dump({"error": msg}, sys.stderr)
    sys.stderr.write("\n")
    sys.exit(1)


def _get_credentials(args):
    """Get DGS email and password from args or env vars."""
    email = args.email or os.environ.get("DGS_EMAIL", "")
    password = args.password or os.environ.get("DGS_PASSWORD", "")

    if not email:
        _error(
            "No email provided. Pass --email or set DGS_EMAIL in .env. "
            "Example: python3 dgs-auth.py --email you@example.com --password yourpass"
        )
    if not password:
        _error(
            "No password provided. Pass --password or set DGS_PASSWORD in .env. "
            "Example: python3 dgs-auth.py --email you@example.com --password yourpass"
        )

    return email, password


def _discover_login_form():
    """GET the sign-in page to discover any hidden form fields (CSRF tokens, etc.)."""
    req = urllib.request.Request(
        DGS_SIGN_IN,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="replace")
            # Capture any cookies set on the GET request
            get_cookies = {}
            for header_name, header_val in resp.headers.items():
                if header_name.lower() == "set-cookie":
                    # Parse cookie name=value from the header
                    match = re.match(r"([^=]+)=([^;]*)", header_val)
                    if match:
                        get_cookies[match.group(1).strip()] = match.group(2).strip()
            return html, get_cookies
    except urllib.error.HTTPError as e:
        _error(f"Failed to load sign-in page: {e.code} {e.reason}")
    except Exception as e:
        _error(f"Failed to load sign-in page: {e}")


def _extract_hidden_fields(html):
    """Extract hidden input fields from the login form."""
    fields = {}
    # Find all hidden inputs
    for match in re.finditer(
        r'<input[^>]+type=["\']hidden["\'][^>]*>', html, re.I
    ):
        tag = match.group(0)
        name_match = re.search(r'name=["\']([^"\']+)["\']', tag)
        value_match = re.search(r'value=["\']([^"\']*)["\']', tag)
        if name_match:
            fields[name_match.group(1)] = value_match.group(1) if value_match else ""
    return fields


def _do_login(email, password, pre_cookies=None, hidden_fields=None):
    """POST credentials to the sign-in endpoint and capture all cookies.

    Uses http.cookiejar to properly track cookies across redirects.
    Returns a dict of all cookies set during the auth flow.
    """
    cookie_jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cookie_jar),
        urllib.request.HTTPRedirectHandler(),
    )

    # Seed any pre-existing cookies from the GET request
    if pre_cookies:
        for name, value in pre_cookies.items():
            cookie = http.cookiejar.Cookie(
                version=0, name=name, value=value,
                port=None, port_specified=False,
                domain=".discgolfscene.com", domain_specified=True,
                domain_initial_dot=True,
                path="/", path_specified=True,
                secure=False, expires=None, discard=True,
                comment=None, comment_url=None,
                rest={}, rfc2109=False,
            )
            cookie_jar.set_cookie(cookie)

    # Build form data
    form_data = {}
    if hidden_fields:
        form_data.update(hidden_fields)
    form_data["auth_email"] = email
    form_data["auth_password"] = password

    encoded = urllib.parse.urlencode(form_data).encode("utf-8")

    req = urllib.request.Request(
        DGS_SIGN_IN,
        data=encoded,
        headers={
            "User-Agent": USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
            "Referer": DGS_SIGN_IN,
            "Origin": DGS_BASE,
        },
        method="POST",
    )

    try:
        resp = opener.open(req, timeout=30)
        final_url = resp.geturl()
        body = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    except urllib.error.HTTPError as e:
        # Some sites return 302/303 as "errors" in urllib — check cookies anyway
        final_url = str(e.url) if hasattr(e, "url") else DGS_SIGN_IN
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        status = e.code

    # Collect all cookies from the jar
    cookies = {}
    for cookie in cookie_jar:
        cookies[cookie.name] = cookie.value

    # Check for auth failure indicators
    auth_failed = False
    if "sign-in" in (final_url or "").lower() and status in (200, 302, 303):
        # Still on the sign-in page — check for error messages
        if re.search(r'(invalid|incorrect|wrong|failed|error)', body, re.I):
            auth_failed = True

    return {
        "cookies": cookies,
        "final_url": final_url,
        "status": status,
        "auth_failed": auth_failed,
        "body_snippet": body[:500] if body else "",
    }


def _validate_cookies(cookies):
    """Check if the login produced meaningful auth cookies beyond baseline."""
    # We expect DGS to set cookies like 'auth', 'c_r', 'c_m' or similar.
    # Any cookie beyond 'desktop', 'AWSELB', 'AWSELBCORS' is potentially an auth cookie.
    baseline = {"desktop", "AWSELB", "AWSELBCORS"}
    auth_cookies = {k: v for k, v in cookies.items() if k not in baseline}
    return auth_cookies


def _save_cookies(cookies, path):
    """Save cookies to a JSON file."""
    data = {
        "cookies": cookies,
        "cookie_header": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "note": "Generated by dgs-auth.py. Re-run when cookies expire.",
    }
    path = Path(path)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def _update_env_file(env_path, cookies):
    """Update .env file with new DGS cookie values.

    Maps discovered cookies to the DGS_COOKIE_* env var naming convention.
    Known mappings:
        auth  -> DGS_COOKIE_AUTH
        c_r   -> DGS_COOKIE_CR
        c_m   -> DGS_COOKIE_CM
    """
    # Cookie name -> env var name mapping
    known_mappings = {
        "auth": "DGS_COOKIE_AUTH",
        "c_r": "DGS_COOKIE_CR",
        "c_m": "DGS_COOKIE_CM",
    }

    env_path = Path(env_path)
    if not env_path.exists():
        sys.stderr.write(f"Warning: {env_path} not found, skipping .env update\n")
        return

    content = env_path.read_text()
    updated = False

    for cookie_name, env_var in known_mappings.items():
        if cookie_name in cookies:
            value = cookies[cookie_name]
            # Replace existing line or note if missing
            pattern = rf'^{re.escape(env_var)}="[^"]*"'
            replacement = f'{env_var}="{value}"'
            new_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            if new_content != content:
                content = new_content
                updated = True
                sys.stderr.write(f"  Updated {env_var} in {env_path}\n")
            else:
                sys.stderr.write(f"  {env_var} not found in {env_path} (add manually: {env_var}=\"{value}\")\n")

    if updated:
        env_path.write_text(content)


def main():
    parser = argparse.ArgumentParser(
        description="Authenticate with DiscGolfScene and save session cookies"
    )
    parser.add_argument("--email", default=None, help="DGS login email (or set DGS_EMAIL env var)")
    parser.add_argument("--password", default=None, help="DGS login password (or set DGS_PASSWORD env var)")
    parser.add_argument("--output", "-o", default=str(DEFAULT_COOKIE_PATH),
                        help=f"Path to save cookies JSON (default: {DEFAULT_COOKIE_PATH})")
    parser.add_argument("--dry-run", action="store_true", help="Print cookies without saving")
    parser.add_argument("--update-env", default=None, metavar="PATH",
                        help="Also update DGS_COOKIE_* vars in the specified .env file")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed login flow info")
    args = parser.parse_args()

    email, password = _get_credentials(args)

    # Step 1: GET the sign-in page to discover form structure
    sys.stderr.write("Step 1: Loading sign-in page...\n")
    html, pre_cookies = _discover_login_form()
    hidden_fields = _extract_hidden_fields(html)

    if args.verbose:
        sys.stderr.write(f"  Pre-login cookies: {list(pre_cookies.keys())}\n")
        sys.stderr.write(f"  Hidden form fields: {list(hidden_fields.keys())}\n")

    # Step 2: POST credentials
    sys.stderr.write("Step 2: Submitting credentials...\n")
    result = _do_login(email, password, pre_cookies, hidden_fields)

    if args.verbose:
        sys.stderr.write(f"  Final URL: {result['final_url']}\n")
        sys.stderr.write(f"  HTTP status: {result['status']}\n")
        sys.stderr.write(f"  All cookies: {list(result['cookies'].keys())}\n")

    if result["auth_failed"]:
        _error("Login appears to have failed — still on sign-in page with error indicators. Check credentials.")

    # Step 3: Identify auth cookies
    all_cookies = result["cookies"]
    auth_cookies = _validate_cookies(all_cookies)

    if not auth_cookies:
        sys.stderr.write("\nWarning: No auth-specific cookies found beyond baseline cookies.\n")
        sys.stderr.write("This might mean:\n")
        sys.stderr.write("  1. Credentials were wrong (DGS may not show explicit errors)\n")
        sys.stderr.write("  2. DGS uses a different auth mechanism than expected\n")
        sys.stderr.write(f"  3. All cookies received: {list(all_cookies.keys())}\n")
        if args.verbose:
            sys.stderr.write(f"\n  Response body snippet:\n  {result['body_snippet'][:300]}\n")

    # Step 4: Output results
    output = {
        "success": bool(auth_cookies),
        "all_cookies": all_cookies,
        "auth_cookies": auth_cookies,
        "cookie_header": "; ".join(f"{k}={v}" for k, v in all_cookies.items()),
        "env_var_mapping": {
            "DGS_COOKIE_AUTH": all_cookies.get("auth", ""),
            "DGS_COOKIE_CR": all_cookies.get("c_r", ""),
            "DGS_COOKIE_CM": all_cookies.get("c_m", ""),
        },
    }

    if not args.dry_run:
        saved_path = _save_cookies(all_cookies, args.output)
        output["saved_to"] = str(saved_path)
        sys.stderr.write(f"\nCookies saved to {saved_path}\n")

        if args.update_env:
            sys.stderr.write(f"\nUpdating {args.update_env}...\n")
            _update_env_file(args.update_env, all_cookies)

    # Print the full result to stdout (JSON)
    json.dump(output, sys.stdout, indent=2)
    print()

    # Print human-readable summary to stderr
    sys.stderr.write("\n--- Cookie Summary ---\n")
    for name, value in sorted(all_cookies.items()):
        marker = " (auth)" if name not in {"desktop", "AWSELB", "AWSELBCORS"} else ""
        sys.stderr.write(f"  {name} = {value[:40]}{'...' if len(value) > 40 else ''}{marker}\n")

    if auth_cookies:
        sys.stderr.write("\nTo update .env manually:\n")
        if "auth" in all_cookies:
            sys.stderr.write(f'  DGS_COOKIE_AUTH="{all_cookies["auth"]}"\n')
        if "c_r" in all_cookies:
            sys.stderr.write(f'  DGS_COOKIE_CR="{all_cookies["c_r"]}"\n')
        if "c_m" in all_cookies:
            sys.stderr.write(f'  DGS_COOKIE_CM="{all_cookies["c_m"]}"\n')

        # Show any unexpected cookie names for discovery
        known = {"auth", "c_r", "c_m", "desktop", "AWSELB", "AWSELBCORS"}
        unknown = {k: v for k, v in all_cookies.items() if k not in known}
        if unknown:
            sys.stderr.write("\n  Unknown cookies (may be needed — investigate):\n")
            for k, v in unknown.items():
                sys.stderr.write(f"    {k} = {v}\n")
    else:
        sys.stderr.write("\nNo auth cookies detected. Login may have failed silently.\n")


if __name__ == "__main__":
    main()
