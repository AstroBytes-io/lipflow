"""About Mouthpiece: the standard macOS About panel with version, copyright and attributions (see NOTICE)."""
from __future__ import annotations

CREDITS = (
    "Mouthpiece is derived from Lipflow by Amy Zhou (MIT License).\n\n"
    "It includes code from ESPnet (Apache License 2.0), Auto-AVSR by Pingchuan Ma et al. "
    "(Apache License 2.0) and Chaplin by Amanvir Parhar (MIT License).\n\n"
    "Model weights: the Auto-AVSR models trained on the LRS3 dataset, which is licensed for "
    "non-commercial research use. They're downloaded from their public source on first run and "
    "aren't distributed with Mouthpiece."
)


def version() -> str:
    from importlib.metadata import PackageNotFoundError, version as v
    try:
        return v("mouthpiece")
    except PackageNotFoundError:
        return "dev"


def options() -> dict:
    from AppKit import (NSAttributedString, NSBundle, NSColor, NSFont, NSFontAttributeName,
                        NSForegroundColorAttributeName)
    from .hud import symbol
    credits = NSAttributedString.alloc().initWithString_attributes_(CREDITS, {
        NSFontAttributeName: NSFont.systemFontOfSize_(NSFont.smallSystemFontSize()),
        NSForegroundColorAttributeName: NSColor.secondaryLabelColor()})
    opts = {"ApplicationName": "Mouthpiece", "ApplicationVersion": version(), "Version": "",
            "Copyright": "© 2026 AstroBytes", "Credits": credits}
    if not str(NSBundle.mainBundle().bundlePath()).endswith(".app"):  # not the bundle: no app icon to show
        opts["ApplicationIcon"] = symbol("mouth", 48)
    return opts


def show_about():
    from AppKit import NSApplication
    app = NSApplication.sharedApplication()
    app.activate() if hasattr(app, "activate") else app.activateIgnoringOtherApps_(True)
    app.orderFrontStandardAboutPanelWithOptions_(options())
