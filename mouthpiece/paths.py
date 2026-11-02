"""Where each person's data lives. Shared model weights stay in the repo's models/; everything
learned from *you* (clips, phrases, personal models, settings) goes here.

Override with MOUTHPIECE_HOME (tests use a temp dir so they never touch your real data)."""
import os
import sys

WINDOWS = sys.platform == "win32"
LINUX = sys.platform == "linux"
DESKTOP_TRAY = WINDOWS or LINUX

if WINDOWS:  # %APPDATA%\Mouthpiece
    _DEFAULT_HOME = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Mouthpiece")
elif LINUX:
    _DEFAULT_HOME = os.path.join(
        os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")),
        "Mouthpiece",
    )
else:
    _DEFAULT_HOME = os.path.expanduser("~/Library/Application Support/Mouthpiece")
HOME = os.environ.get("MOUTHPIECE_HOME") or _DEFAULT_HOME
PERSONAL_MODELS = os.path.join(HOME, "models")
PERSONAL_VSR = os.path.join(PERSONAL_MODELS, "vsr_face.pth")
PERSONAL_LM = os.path.join(PERSONAL_MODELS, "lm_phrasing.pth")

# The app bundle's launcher sets MOUTHPIECE_APP=1: permissions then belong to "Mouthpiece", not the terminal.
# On Windows nothing is granted per app, so the name only shows up in messages.
IN_APP = bool(os.environ.get("MOUTHPIECE_APP")) or ".app/Contents/" in sys.executable
WHO = "Mouthpiece" if IN_APP or DESKTOP_TRAY else "your terminal"  # "your terminal" only in a dev checkout

# Shared model weights (lip reader, LM, face landmarker, AV model). A dev checkout keeps them in the
# repo's models/ (scripts/download-models.sh); the shipped app has no repo, so they download on first
# run into the user's data folder. MOUTHPIECE_MODELS overrides both.
_REPO_MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models")
MODELS = os.environ.get("MOUTHPIECE_MODELS") or (
    _REPO_MODELS if os.path.isdir(_REPO_MODELS) else os.path.join(HOME, "weights"))
