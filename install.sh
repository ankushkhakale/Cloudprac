#!/usr/bin/env bash
# ==============================================================================
# CloudPrac — One-Command Installer and Launcher for AWS CloudShell
#
# Usage:
#   In AWS CloudShell:
#     git clone https://github.com/ankushkhakale/Cloudprac.git && cd Cloudprac && ./install.sh
#   Or one-liner:
#     bash <(curl -sSL https://raw.githubusercontent.com/ankushkhakale/Cloudprac/main/install.sh)
# ==============================================================================

set -euo pipefail

BOLD_CYAN="\033[1;36m"
BOLD_GREEN="\033[1;32m"
BOLD_YELLOW="\033[1;33m"
BOLD_RED="\033[1;31m"
DIM="\033[2m"
RESET="\033[0m"

echo -e "${BOLD_CYAN}======================================================================${RESET}"
echo -e "${BOLD_CYAN}  ☁  CloudPrac — AWS Cloud Computing Practical Automation Engine      ${RESET}"
echo -e "${BOLD_CYAN}======================================================================${RESET}"
echo ""

# 1. Environment Detection
if [ -n "${AWS_EXECUTION_ENV:-}" ] && [[ "${AWS_EXECUTION_ENV}" =~ CloudShell ]] || [ "${CLOUDSHELL:-}" = "true" ] || [ -f "/usr/bin/cloudshell-main" ]; then
    echo -e "${BOLD_GREEN}✔ Detected AWS CloudShell environment.${RESET}"
else
    echo -e "${DIM}ℹ Running in standard terminal / local environment.${RESET}"
fi

# 2. Check Python 3.10+
PYTHON_BIN=""
for candidate in python3 python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
        if "$candidate" -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" 2>/dev/null; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${BOLD_RED}✘ Error: Python 3.10 or newer is required.${RESET}"
    echo "Please install Python 3.10+ or use AWS CloudShell (AL2023)."
    exit 1
fi

PY_VER=$($PYTHON_BIN -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')")
echo -e "${BOLD_GREEN}✔ Found Python ${PY_VER}${RESET} (${PYTHON_BIN})"

# 3. Determine installation source
TARGET_DIR="${PWD}"
if [ ! -f "${TARGET_DIR}/pyproject.toml" ]; then
    REPO_DIR="${HOME}/Cloudprac"
    if [ ! -d "$REPO_DIR" ]; then
        echo -e "${DIM}Fetching CloudPrac repository into ${REPO_DIR}...${RESET}"
        git clone --depth 1 https://github.com/ankushkhakale/Cloudprac.git "$REPO_DIR"
    fi
    TARGET_DIR="$REPO_DIR"
fi

# 4. Install CloudPrac package
echo -e "${DIM}Installing CloudPrac using ${PYTHON_BIN}...${RESET}"
if ! "$PYTHON_BIN" -m pip --version >/dev/null 2>&1; then
    echo -e "${DIM}Bootstrapping pip via ensurepip...${RESET}"
    "$PYTHON_BIN" -m ensurepip --user 2>/dev/null || true
fi
"$PYTHON_BIN" -m pip install --user --upgrade --quiet --no-warn-script-location "$TARGET_DIR"

# 5. Ensure PATH includes ~/.local/bin
LOCAL_BIN="${HOME}/.local/bin"
if [[ ":$PATH:" != *":$LOCAL_BIN:"* ]]; then
    export PATH="${LOCAL_BIN}:${PATH}"
    if [ -f "${HOME}/.bashrc" ] && ! grep -q "export PATH=\"${LOCAL_BIN}:\$PATH\"" "${HOME}/.bashrc"; then
        echo "export PATH=\"${LOCAL_BIN}:\$PATH\"" >> "${HOME}/.bashrc"
    fi
fi

# 6. Verify installation
if ! command -v cloudprac >/dev/null 2>&1; then
    CLOUDPRAC_BIN="${LOCAL_BIN}/cloudprac"
    if [ -f "$CLOUDPRAC_BIN" ] || [ -x "$CLOUDPRAC_BIN" ]; then
        CLOUDPRAC_CMD="$CLOUDPRAC_BIN"
    else
        echo -e "${BOLD_RED}✘ Error: cloudprac executable not found in PATH or ~/.local/bin.${RESET}"
        exit 1
    fi
else
    CLOUDPRAC_CMD="cloudprac"
fi

echo -e "${BOLD_GREEN}✔ CloudPrac successfully installed!${RESET}"
echo ""

# 7. Launch CloudPrac
# When run via pipe (e.g. curl ... | bash), re-attach to controlling terminal (/dev/tty)
if [ -c /dev/tty ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
    echo -e "${BOLD_CYAN}Launching CloudPrac interactive menu...${RESET}"
    exec "$CLOUDPRAC_CMD" < /dev/tty > /dev/tty 2>&1
elif [ -t 0 ]; then
    echo -e "${BOLD_CYAN}Launching CloudPrac interactive menu...${RESET}"
    exec "$CLOUDPRAC_CMD"
else
    echo -e "${BOLD_GREEN}Installation complete. Run '${CLOUDPRAC_CMD}' to begin.${RESET}"
fi
