"""Build Mouthpiece.app.

Why a bundle: macOS grants Camera / Input Monitoring / Accessibility per app. Run from a
terminal, Mouthpiece borrows the terminal's permissions (and asks for them in the terminal's name);
as an app it gets its own entries called "Mouthpiece", starts from Launchpad/Spotlight, and can be
added to Login Items.

    uv run python scripts/make_app.py [--dest /Applications]          # dev: launches this checkout's .venv
    uv run python scripts/make_app.py --release --dest dist [--sign ID] # self-contained, for the .dmg

--release embeds a relocatable Python (uv's python-build-standalone) and a --no-dev install of the
project in Contents/Resources/python, then signs every Mach-O inside-out (see RELEASING.md).
scripts/release.sh wraps it with the DMG and notarization.
"""
from __future__ import annotations

import argparse
import glob
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import tomllib

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def draw_icon(path_png: str, size: int = 1024):
    """Pink squircle with a white SF Symbols mouth."""
    from AppKit import (NSBezierPath, NSBitmapImageRep, NSCalibratedRGBColorSpace, NSColor, NSGradient,
                        NSGraphicsContext, NSImage, NSImageSymbolConfiguration, NSMakeRect, NSPNGFileType)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, NSCalibratedRGBColorSpace, 0, 0)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep))
    inset = size * 0.1
    r = NSMakeRect(inset, inset, size - 2 * inset, size - 2 * inset)
    shape = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, size * 0.18, size * 0.18)
    NSGradient.alloc().initWithStartingColor_endingColor_(
        NSColor.colorWithSRGBRed_green_blue_alpha_(1.0, 0.45, 0.55, 1),
        NSColor.colorWithSRGBRed_green_blue_alpha_(0.78, 0.16, 0.38, 1)).drawInBezierPath_angle_(shape, -90)
    NSColor.colorWithWhite_alpha_(1, 0.25).setStroke()
    shape.setLineWidth_(size * 0.006)
    shape.stroke()
    cfg = NSImageSymbolConfiguration.configurationWithPointSize_weight_(size * 0.36, 6)  # semibold
    sym = NSImage.imageWithSystemSymbolName_accessibilityDescription_("mouth.fill", None).imageWithSymbolConfiguration_(cfg)
    tinted = NSImage.alloc().initWithSize_(sym.size())
    tinted.lockFocus()
    sym.drawInRect_(NSMakeRect(0, 0, sym.size().width, sym.size().height))
    NSColor.whiteColor().set()
    from AppKit import NSCompositingOperationSourceAtop, NSRectFillUsingOperation
    NSRectFillUsingOperation(NSMakeRect(0, 0, sym.size().width, sym.size().height), NSCompositingOperationSourceAtop)
    tinted.unlockFocus()
    w, h = tinted.size().width, tinted.size().height
    tinted.drawInRect_(NSMakeRect((size - w) / 2, (size - h) / 2, w, h))
    NSGraphicsContext.restoreGraphicsState()
    rep.representationUsingType_properties_(NSPNGFileType, None).writeToFile_atomically_(path_png, True)


def make_icns(dest_icns: str):
    tmp = tempfile.mkdtemp()
    base = os.path.join(tmp, "base.png")
    draw_icon(base)
    iconset = os.path.join(tmp, "Mouthpiece.iconset")
    os.makedirs(iconset)
    for s in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            px = s * scale
            name = f"icon_{s}x{s}{'@2x' if scale == 2 else ''}.png"
            subprocess.run(["sips", "-z", str(px), str(px), base, "--out", os.path.join(iconset, name)],
                           check=True, capture_output=True)
    subprocess.run(["iconutil", "-c", "icns", iconset, "-o", dest_icns], check=True)
    shutil.rmtree(tmp)


ENTITLEMENTS = os.path.join(os.path.dirname(__file__), "Mouthpiece.entitlements")
BUILD = os.path.join(ROOT, "build")  # scratch: the release venv


def version() -> str:
    return tomllib.load(open(os.path.join(ROOT, "pyproject.toml"), "rb"))["project"]["version"]


def build(dest_dir: str = "/Applications", release: bool = False, sign_id: str | None = None) -> str:
    app = os.path.join(os.path.expanduser(dest_dir), "Mouthpiece.app")
    if os.path.exists(app):
        shutil.rmtree(app)
    macos = os.path.join(app, "Contents", "MacOS")
    res = os.path.join(app, "Contents", "Resources")
    os.makedirs(macos)
    os.makedirs(res)
    make_icns(os.path.join(res, "Mouthpiece.icns"))
    launcher = os.path.join(macos, "Mouthpiece")
    if release:
        pyhome = os.path.join(res, "python")
        base = _embed_python(pyhome)
        _compile_launcher(launcher, include_from=base)
        min_os = _min_macos(app)
    else:
        _compile_launcher(launcher)
        min_os = "13.0"
    ver = version()
    plistlib.dump({
        "CFBundleName": "Mouthpiece",
        "CFBundleDisplayName": "Mouthpiece",
        "CFBundleIdentifier": "io.astrobytes.mouthpiece",
        "CFBundleVersion": ver,
        "CFBundleShortVersionString": ver,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "Mouthpiece",
        "CFBundleIconFile": "Mouthpiece",
        "LSUIElement": True,  # menu-bar app (NSApplicationActivationPolicyAccessory): no Dock icon
        "LSMinimumSystemVersion": min_os,
        "LSApplicationCategoryType": "public.app-category.productivity",
        "NSHumanReadableCopyright": "© 2026 AstroBytes",
        "NSCameraUsageDescription": "Mouthpiece reads your lips from the camera to type what you mouth. "
                                    "Video never leaves this Mac.",
        "NSMicrophoneUsageDescription": "Whisper mode listens to a soft whisper while you hold the key, "
                                        "to read your lips more accurately. Audio never leaves this Mac.",
        "NSHighResolutionCapable": True,
    }, open(os.path.join(app, "Contents", "Info.plist"), "wb"))
    if release:
        sign(app, sign_id)
    else:
        # Ad-hoc signature so Accessibility / Input Monitoring bind to this app, not to
        # whatever Python the old shell launcher exec'd. Unsigned bundles record a grant
        # the running process can never satisfy, and setup's Continue button stays off.
        subprocess.run(["codesign", "--force", "--sign", "-", "--identifier", "io.astrobytes.mouthpiece", app],
                       check=True)
    subprocess.run(["touch", app])
    return app


def _embed_python(pyhome: str) -> str:
    """Copy uv's standalone CPython + a --no-dev, non-editable install of this project into pyhome.
    Returns the source Python prefix (for headers)."""
    venv = os.path.join(BUILD, "venv")
    # --link-mode copy: codesign rewrites files in place, so never hardlink into uv's cache.
    # Pick wheels for the oldest macOS we can, not for this Mac: mlx ships 14/15/26 builds and the
    # 26 one would make the whole app 26-only. The real floor is computed from the binaries (_min_macos).
    subprocess.run(["uv", "sync", "--frozen", "--no-dev", "--no-editable", "--link-mode", "copy",
                    "--python-platform", "aarch64-apple-darwin"], cwd=ROOT, check=True,
                   env={k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"} | {"UV_PROJECT_ENVIRONMENT": venv, "MACOSX_DEPLOYMENT_TARGET": "14.0"})
    base = os.path.realpath(os.path.join(venv, "bin", "python"))
    base = os.path.dirname(os.path.dirname(base))  # .../cpython-3.12.x-macos-aarch64-none
    pyver = f"python{sys.version_info.major}.{sys.version_info.minor}"
    stdlib_skip = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3",
                   f"config-{sys.version_info.major}.{sys.version_info.minor}-darwin"}
    shutil.copytree(os.path.join(base, "lib", pyver), os.path.join(pyhome, "lib", pyver), symlinks=True,
                    ignore=lambda d, names: [n for n in names if n in stdlib_skip or n == "__pycache__"])
    shutil.copy2(os.path.join(base, "lib", f"lib{pyver}.dylib"), os.path.join(pyhome, "lib"))
    lib = os.path.join(pyhome, "lib", f"lib{pyver}.dylib")
    os.chmod(lib, 0o755)
    subprocess.run(["install_name_tool", "-id", f"@rpath/lib{pyver}.dylib", lib], check=True)
    os.makedirs(os.path.join(pyhome, "bin"))
    shutil.copy2(os.path.join(base, "bin", pyver), os.path.join(pyhome, "bin", pyver))  # for sys.executable users
    site = os.path.join(pyhome, "lib", pyver, "site-packages")
    shutil.copytree(os.path.join(venv, "lib", pyver, "site-packages"), site, symlinks=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_virtualenv.*", "*.a", "*.h", "*.hpp",
                                                  "*.cuh", "include", "tests", "PyObjCTest",
                                                  "direct_url.json"))  # holds the build path
    # torch/share: cmake files. jax, jaxlib, scipy (~330 MB):
    # only mediapipe requires them, for model-maker code the face landmarker never imports.
    junk = ["torch/share", *glob.glob("jax*", root_dir=site), *glob.glob("scipy*", root_dir=site)]
    for j in junk:
        p = os.path.join(site, j)
        shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)
    # Precompile (+~190 MB, launch ~5 s → ~2 s). unchecked-hash: valid whatever the mtimes after
    # copying/DMG, and the launcher never writes .pyc into the signed bundle. A few files in deps
    # are not valid Python 3.12 (templates, py2 leftovers), hence no check=True.
    subprocess.run([os.path.join(pyhome, "bin", pyver), "-I", "-m", "compileall", "-q", "-j0",
                    "--invalidation-mode", "unchecked-hash", os.path.join(pyhome, "lib")], capture_output=True)
    return base


def _macho(path: str) -> bool:
    with open(path, "rb") as f:
        return f.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def _machos(root: str) -> list[str]:
    out = []
    for d, _, files in os.walk(root):
        for n in files:
            p = os.path.join(d, n)
            if not os.path.islink(p) and _macho(p):
                out.append(p)
    return out


def _min_macos(app: str) -> str:
    """Highest LC_BUILD_VERSION minos among the bundle's binaries: the oldest macOS that can load them all."""
    best = (0,)
    for p in _machos(app):
        out = subprocess.run(["otool", "-l", p], capture_output=True, text=True).stdout.split()
        for i, tok in enumerate(out):
            if tok == "minos":  # LC_BUILD_VERSION (LC_VERSION_MIN_MACOSX binaries are older still)
                best = max(best, tuple(int(x) for x in out[i + 1].split(".")))
    return ".".join(map(str, best[:2] if len(best) > 1 else (*best, 0)))


def sign(app: str, identity: str | None) -> None:
    """Sign inside-out: every nested Mach-O, then the bundle (which seals Resources).
    No identity = ad-hoc: runs locally, not distributable. No hardened runtime then: library
    validation needs a Team ID, which ad-hoc signatures lack, so dyld would refuse libpython."""
    if identity:
        flags = ["--force", "--sign", identity, "--options", "runtime", "--timestamp",
                 "--entitlements", ENTITLEMENTS]
    else:
        flags = ["--force", "--sign", "-"]
    main_exe = os.path.join(app, "Contents", "MacOS", "Mouthpiece")
    nested = [p for p in _machos(app) if p != main_exe]
    for i in range(0, len(nested), 200):  # one codesign per batch, not per file
        subprocess.run(["codesign", *flags, *nested[i:i + 200]], check=True, capture_output=True)
    subprocess.run(["codesign", *flags, "--identifier", "io.astrobytes.mouthpiece", app], check=True)


def _compile_launcher(dest: str, include_from: str | None = None) -> None:
    """Mach-O main executable that runs `python -m mouthpiece` in-process. See mouthpiece_launcher.c.
    Release (include_from set): links @rpath libpython inside the bundle. Dev: bakes in this checkout."""
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    src = os.path.join(os.path.dirname(__file__), "mouthpiece_launcher.c")
    if include_from:
        include = os.path.join(include_from, "include", version)
        args = [f"-L{os.path.join(include_from, 'lib')}", f"-l{version}",
                "-Wl,-rpath,@executable_path/../Resources/python/lib"]
    else:
        venv_py = os.path.join(ROOT, ".venv", "bin", "python")
        if not os.path.exists(venv_py):
            raise SystemExit(f"no venv at {venv_py}; run ./setup.sh first")
        pyhome = os.path.dirname(os.path.dirname(os.path.realpath(venv_py)))
        include = os.path.join(pyhome, "include", version)
        lib = os.path.join(pyhome, "lib")
        args = [f"-DMOUTHPIECE_ROOT={root_c(ROOT)}", f"-DMOUTHPIECE_VENV_PYTHON={root_c(venv_py)}",
                f"-L{lib}", f"-l{version}", f"-Wl,-rpath,{lib}"]
    if not os.path.isfile(os.path.join(include, "Python.h")):
        raise SystemExit(f"no Python headers at {include}; run ./setup.sh first")
    subprocess.run(["clang", "-O2", "-arch", "arm64", "-mmacosx-version-min=13.0", f"-I{include}",
                    src, *args, "-o", dest], check=True)
    if include_from:  # the build links against the source prefix; make sure only the rpath remains
        subprocess.run(["install_name_tool", "-change",
                        os.path.join(include_from, "lib", f"lib{version}.dylib"),
                        f"@rpath/lib{version}.dylib", dest], check=True)


def root_c(path: str) -> str:
    """A C string literal, including the quotes clang expects in -DNAME=value."""
    return '"' + path.replace("\\", "\\\\").replace('"', '\\"') + '"'


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="/Applications")
    ap.add_argument("--release", action="store_true", help="self-contained bundle with its own Python")
    ap.add_argument("--sign", default=os.environ.get("MOUTHPIECE_SIGN_ID") or None,
                    help="codesign identity (default $MOUTHPIECE_SIGN_ID; unset = ad-hoc)")
    a = ap.parse_args()
    print(build(a.dest, a.release, a.sign))
