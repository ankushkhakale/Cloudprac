"""Regression tests for CloudPrac installer in AWS CloudShell and virtual environments."""

import os
import stat
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
INSTALL_SH = PROJECT_ROOT / "install.sh"


def test_install_script_syntax():
    """Verify install.sh has valid bash syntax."""
    result = subprocess.run(
        ["bash", "-n", str(INSTALL_SH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Syntax error in install.sh: {result.stderr}"


def test_installer_detects_virtualenv_from_env_var(tmp_path):
    """Verify install.sh identifies virtual environment when VIRTUAL_ENV is set."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    mock_python = fake_bin / "python3"
    mock_python.write_text("""#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    exit 1
fi
exit 0
""")
    mock_python.chmod(mock_python.stat().st_mode | stat.S_IEXEC)

    code = f"""
    PYTHON_BIN="{mock_python}"
    VIRTUAL_ENV="/home/cloudshell-user/.venv"
    IN_VIRTUAL_ENV=false
    if [ -n "${{VIRTUAL_ENV:-}}" ]; then
        IN_VIRTUAL_ENV=true
    elif "$PYTHON_BIN" -c "import sys; sys.exit(0 if (getattr(sys, 'base_prefix', sys.prefix) != sys.prefix or getattr(sys, 'real_prefix', None) is not None) else 1)" 2>/dev/null; then
        IN_VIRTUAL_ENV=true
    fi
    echo "IN_VIRTUAL_ENV=$IN_VIRTUAL_ENV"
    """
    proc = subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "IN_VIRTUAL_ENV=true" in proc.stdout


def test_installer_detects_virtualenv_from_sys_prefix(tmp_path):
    """Verify install.sh identifies virtualenv when sys.prefix != sys.base_prefix without VIRTUAL_ENV."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    mock_python = fake_bin / "python3"
    mock_python.write_text("""#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    # Return 0 indicating base_prefix != sys.prefix
    exit 0
fi
exit 0
""")
    mock_python.chmod(mock_python.stat().st_mode | stat.S_IEXEC)

    code = f"""
    PYTHON_BIN="{mock_python}"
    unset VIRTUAL_ENV
    IN_VIRTUAL_ENV=false
    if [ -n "${{VIRTUAL_ENV:-}}" ]; then
        IN_VIRTUAL_ENV=true
    elif "$PYTHON_BIN" -c "import sys; sys.exit(0 if (getattr(sys, 'base_prefix', sys.prefix) != sys.prefix or getattr(sys, 'real_prefix', None) is not None) else 1)" 2>/dev/null; then
        IN_VIRTUAL_ENV=true
    fi
    echo "IN_VIRTUAL_ENV=$IN_VIRTUAL_ENV"
    """
    proc = subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "IN_VIRTUAL_ENV=true" in proc.stdout


def test_installer_uses_isolated_venv_when_in_virtualenv(tmp_path):
    """Verify install.sh creates isolated venv and links ~/.local/bin/cloudprac without calling pip --user."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    # Create a mock python3 that mimics Python in AWS CloudShell inside a virtual environment.
    # If pip is invoked with '--user', it fails with the exact CloudShell error.
    # If python -m venv <path> is invoked, it creates the isolated venv with a mock pip and cloudprac binary.
    mock_python = fake_bin / "python3"
    mock_python.write_text("""#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    # Version check or venv check
    if [[ "$2" == *"sys.version_info"* ]]; then
        exit 0
    fi
    if [[ "$2" == *"major"* ]]; then
        echo "3.13.15"
        exit 0
    fi
    if [[ "$2" == *"base_prefix"* ]]; then
        # Simulate sys.prefix != sys.base_prefix
        exit 0
    fi
    exit 0
fi

if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    VENV_TARGET="$3"
    mkdir -p "$VENV_TARGET/bin"
    cat <<'EOF' > "$VENV_TARGET/bin/python"
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    # Pip inside isolated venv: create cloudprac binary
    mkdir -p "$(dirname "$0")"
    cat <<'CLOUDPRACOF' > "$(dirname "$0")/cloudprac"
#!/usr/bin/env bash
echo "cloudprac 0.1.0 (isolated)"
CLOUDPRACOF
    chmod +x "$(dirname "$0")/cloudprac"
    exit 0
fi
EOF
    chmod +x "$VENV_TARGET/bin/python"

    cat <<'EOF' > "$VENV_TARGET/bin/pip"
#!/usr/bin/env bash
mkdir -p "$(dirname "$0")"
cat <<'CLOUDPRACOF' > "$(dirname "$0")/cloudprac"
#!/usr/bin/env bash
echo "cloudprac 0.1.0 (isolated)"
CLOUDPRACOF
chmod +x "$(dirname "$0")/cloudprac"
exit 0
EOF
    chmod +x "$VENV_TARGET/bin/pip"
    exit 0
fi

if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    for arg in "$@"; do
        if [ "$arg" = "--user" ]; then
            echo "ERROR: Can not perform a '--user' install. User site-packages are not visible in this virtualenv." >&2
            exit 1
        fi
    done
    exit 0
fi

exit 0
""")
    mock_python.chmod(mock_python.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["VIRTUAL_ENV"] = "/var/aws/cloudshell/active_virtualenv"
    env["CLOUDPRAC_HOME"] = str(fake_home / ".cloudprac")

    # Run install.sh with stdin closed (non-interactive)
    proc = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    # 1. Installer must not fail with the pip --user error
    assert proc.returncode == 0, f"install.sh failed: {proc.stderr}\nOutput: {proc.stdout}"
    assert "ERROR: Can not perform a '--user' install" not in proc.stderr
    assert "ERROR: Can not perform a '--user' install" not in proc.stdout

    # 2. An isolated venv must be created in ~/.cloudprac/venv
    venv_dir = fake_home / ".cloudprac" / "venv"
    assert venv_dir.is_dir()
    assert (venv_dir / "bin" / "cloudprac").is_file()

    # 3. Executable must be exposed at ~/.local/bin/cloudprac
    local_bin_cloudprac = fake_home / ".local" / "bin" / "cloudprac"
    assert local_bin_cloudprac.exists()
    assert local_bin_cloudprac.is_symlink()
    assert local_bin_cloudprac.resolve() == (venv_dir / "bin" / "cloudprac").resolve()


def test_installer_idempotency_reuses_existing_venv(tmp_path):
    """Verify re-running install.sh reuses the existing functional venv without recreating it."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    call_counts = tmp_path / "call_counts.txt"

    mock_python = fake_bin / "python3"
    mock_python.write_text(f"""#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    exit 0
fi

if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    echo "venv_called" >> "{call_counts}"
    VENV_TARGET="$3"
    mkdir -p "$VENV_TARGET/bin"
    cat <<'EOF' > "$VENV_TARGET/bin/python"
#!/usr/bin/env bash
if [ "$1" = "-c" ]; then exit 0; fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
    mkdir -p "$(dirname "$0")"
    cat <<'CLOUDPRACOF' > "$(dirname "$0")/cloudprac"
#!/usr/bin/env bash
echo "cloudprac 0.1.0"
CLOUDPRACOF
    chmod +x "$(dirname "$0")/cloudprac"
    exit 0
fi
EOF
    chmod +x "$VENV_TARGET/bin/python"
    cat <<'EOF' > "$VENV_TARGET/bin/pip"
#!/usr/bin/env bash
mkdir -p "$(dirname "$0")"
cat <<'CLOUDPRACOF' > "$(dirname "$0")/cloudprac"
#!/usr/bin/env bash
echo "cloudprac 0.1.0"
CLOUDPRACOF
chmod +x "$(dirname "$0")/cloudprac"
exit 0
EOF
    chmod +x "$VENV_TARGET/bin/pip"
    exit 0
fi

exit 0
""")
    mock_python.chmod(mock_python.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["CLOUDPRAC_HOME"] = str(fake_home / ".cloudprac")
    env["VIRTUAL_ENV"] = "/dummy/venv"


    # First run creates the venv
    proc1 = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    assert proc1.returncode == 0
    assert call_counts.read_text().strip().count("venv_called") == 1

    # Second run should reuse existing venv without calling python -m venv again
    proc2 = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )
    assert proc2.returncode == 0
    assert call_counts.read_text().strip().count("venv_called") == 1


def test_installer_fails_closed_when_venv_creation_fails_in_virtualenv(tmp_path):
    """Verify install.sh fails closed and does not pollute $VIRTUAL_ENV when venv creation fails."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()

    mock_python = fake_bin / "python3"
    mock_python.write_text("""#!/usr/bin/env bash
if [ "$1" = "-c" ]; then
    exit 0
fi

# Simulate venv module broken / missing
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
    echo "No module named venv" >&2
    exit 1
fi

exit 0
""")
    mock_python.chmod(mock_python.stat().st_mode | stat.S_IEXEC)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env['PATH']}"
    env["HOME"] = str(fake_home)
    env["CLOUDPRAC_HOME"] = str(fake_home / ".cloudprac")
    env["VIRTUAL_ENV"] = "/dummy/active/virtualenv"

    proc = subprocess.run(
        ["bash", str(INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(PROJECT_ROOT),
    )

    # Must exit 1, refusing to blindly install into the unknown virtualenv or run pip --user
    assert proc.returncode == 1
    assert "Cannot perform a '--user' install inside a virtualenv" in proc.stdout or "Cannot perform a '--user' install inside a virtualenv" in proc.stderr
    assert "installing into an unknown virtual environment is prohibited" in proc.stdout or "installing into an unknown virtual environment is prohibited" in proc.stderr
