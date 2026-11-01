"""Windows x64 bootstrap; Python 3.10+ suffices, all tools stay inside this project."""

import hashlib
import io
import os
import platform
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

UV_VERSION = "0.9.7"
UV_WHEEL = (
    "https://files.pythonhosted.org/packages/de/7f/"
    "e3cdaffac70852f5ff933b04c7b8a06c0f91f41e563f04b689caa65b71bd/"
    "uv-0.9.7-py3-none-win_amd64.whl"
)
UV_SHA256 = "62b315f62669899076a1953fba6baf50bd2b57f66f656280491331dcedd7e6c6"


def main() -> None:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("This fallback bootstrap supports Windows x64 only; see README.")
    root = Path(__file__).resolve().parents[1]
    tool_dir = root / ".tools"
    tool_dir.mkdir(exist_ok=True)
    # Reverify on every bootstrap, including a preexisting executable.
    with urllib.request.urlopen(UV_WHEEL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != UV_SHA256:
        raise SystemExit("uv wheel SHA256 mismatch; nothing executed")
    with zipfile.ZipFile(io.BytesIO(data)) as wheel:
        names = [name for name in wheel.namelist() if name.endswith("/uv.exe")]
        if len(names) != 1:
            raise SystemExit("Unexpected uv wheel layout; nothing executed")
        executable = tool_dir / "uv.exe"
        executable.write_bytes(wheel.read(names[0]))
    env = os.environ.copy()
    env["UV_PYTHON_INSTALL_DIR"] = str(tool_dir / "python")
    env["UV_CACHE_DIR"] = str(tool_dir / "uv-cache")
    env["UV_PROJECT_ENVIRONMENT"] = str(root / ".venv")
    subprocess.run(
        [str(executable), "python", "install", "3.12.12", "--no-bin"],
        cwd=root,
        env=env,
        check=True,
    )
    subprocess.run(
        [str(executable), "sync", "--frozen", "--extra", "dev", "--no-python-downloads"],
        cwd=root,
        env=env,
        check=True,
    )
    print(f"Python 3.12.12 environment ready (uv {UV_VERSION}); no game connection.")


if __name__ == "__main__":
    main()
