"""
Utility to read/write .env files for gateway configuration.
"""

import os


def _get_env_path() -> str:
    """Get .env path — data dir (container) > db dir > cwd."""
    # Container: persistent volume
    data_dir = os.environ.get("GATEWAY_DATA_DIR")
    if data_dir and os.path.isdir(data_dir):
        return os.path.join(data_dir, ".env")
    # Next to the DB file (if GATEWAY_DB_PATH is set and directory exists)
    db_path = os.environ.get("GATEWAY_DB_PATH")
    if db_path:
        db_dir = os.path.dirname(os.path.abspath(db_path))
        if os.path.isdir(db_dir):
            return os.path.join(db_dir, ".env")
    # Fallback: current working directory
    return os.path.join(os.getcwd(), ".env")


def write_env_values(values: dict[str, str]) -> str:
    """Write or update values in .env file. Returns path written."""
    env_path = _get_env_path()

    env_lines: list[str] = []
    if os.path.exists(env_path):
        with open(env_path) as f:
            env_lines = f.readlines()

    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in env_lines:
        key = line.split("=")[0].strip() if "=" in line else ""
        if key in values:
            new_lines.append(f"{key}={values[key]}\n")
            updated_keys.add(key)
        else:
            new_lines.append(line)

    for key, val in values.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={val}\n")

    os.makedirs(os.path.dirname(env_path) or ".", exist_ok=True)
    with open(env_path, "w") as f:
        f.writelines(new_lines)

    return env_path
