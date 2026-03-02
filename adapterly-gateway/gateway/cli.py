"""
Gateway CLI — registration and management commands.

Usage:
    python -m gateway.cli register --token=<one-time-token> --url=<control-plane-url>
    python -m gateway.cli status
"""

import argparse
import json
import os
import sys

import httpx


def register(args):
    """Register this gateway with the control plane."""
    url = f"{args.url.rstrip('/')}/gateway-sync/v1/register"
    headers = {"Authorization": f"Bearer {args.token}"}
    body = {}
    if args.name:
        body["name"] = args.name

    print(f"Registering gateway with {args.url}...")

    try:
        response = httpx.post(url, json=body, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()

        gateway_id = data["gateway_id"]
        gateway_secret = data["gateway_secret"]

        print(f"\nRegistration successful!")
        print(f"  Gateway ID: {gateway_id}")
        print(f"  Gateway Secret: {gateway_secret}")
        print(f"\nIMPORTANT: Store the secret securely. It cannot be retrieved again.")

        # Write to .env file
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        env_lines = []
        if os.path.exists(env_path):
            with open(env_path) as f:
                env_lines = f.readlines()

        # Update or add values
        updated = {"GATEWAY_GATEWAY_ID": False, "GATEWAY_GATEWAY_SECRET": False, "GATEWAY_CONTROL_PLANE_URL": False}
        new_lines = []
        for line in env_lines:
            key = line.split("=")[0].strip() if "=" in line else ""
            if key == "GATEWAY_GATEWAY_ID":
                new_lines.append(f"GATEWAY_GATEWAY_ID={gateway_id}\n")
                updated["GATEWAY_GATEWAY_ID"] = True
            elif key == "GATEWAY_GATEWAY_SECRET":
                new_lines.append(f"GATEWAY_GATEWAY_SECRET={gateway_secret}\n")
                updated["GATEWAY_GATEWAY_SECRET"] = True
            elif key == "GATEWAY_CONTROL_PLANE_URL":
                new_lines.append(f"GATEWAY_CONTROL_PLANE_URL={args.url}\n")
                updated["GATEWAY_CONTROL_PLANE_URL"] = True
            else:
                new_lines.append(line)

        for key, val in [
            ("GATEWAY_GATEWAY_ID", gateway_id),
            ("GATEWAY_GATEWAY_SECRET", gateway_secret),
            ("GATEWAY_CONTROL_PLANE_URL", args.url),
        ]:
            if not updated[key]:
                new_lines.append(f"{key}={val}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)

        print(f"\nConfiguration saved to {env_path}")
        print("Restart the gateway to apply.")

    except httpx.HTTPStatusError as e:
        print(f"Error: HTTP {e.response.status_code}")
        try:
            print(f"  {e.response.json()}")
        except Exception:
            print(f"  {e.response.text}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


def status(args):
    """Show gateway status."""
    print("Gateway Configuration:")
    print(f"  GATEWAY_ID: {os.environ.get('GATEWAY_GATEWAY_ID', '(not set)')}")
    print(f"  CONTROL_PLANE_URL: {os.environ.get('GATEWAY_CONTROL_PLANE_URL', '(not set)')}")
    print(f"  SECRET: {'***configured***' if os.environ.get('GATEWAY_GATEWAY_SECRET') else '(not set)'}")

    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    if os.path.exists(env_path):
        print(f"\n  .env file: {os.path.abspath(env_path)}")
    else:
        print(f"\n  .env file: not found")


def main():
    parser = argparse.ArgumentParser(description="Adapterly Gateway CLI")
    subparsers = parser.add_subparsers(dest="command")

    # register
    reg = subparsers.add_parser("register", help="Register this gateway with a control plane")
    reg.add_argument("--token", required=True, help="One-time registration token from control plane")
    reg.add_argument("--url", default="https://adapterly.ai", help="Control plane URL")
    reg.add_argument("--name", default="", help="Gateway display name")

    # status
    subparsers.add_parser("status", help="Show gateway configuration")

    args = parser.parse_args()

    if args.command == "register":
        register(args)
    elif args.command == "status":
        status(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
