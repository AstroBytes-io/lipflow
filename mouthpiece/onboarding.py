"""First-run setup: download the models (if missing) → permissions → import Wispr Flow → optional Claude
key → mouth ~24 sentences → train on your face.

The practice step uses the normal push-to-talk key, so onboarding is also the tutorial. Clips are
saved with their known text under ~/Library/Application Support/Mouthpiece/clips/onboarding. Training
holds 6 of them out and only keeps the face model if it reads those better than the stock model.
"""
from __future__ import annotations

import glob
import os
import random
import re
import shlex
import subprocess
import threading
import time

import numpy as np
import objc
import Quartz
from AppKit import (
    NSApp, NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSFontWeightBold,
    NSFontWeightMedium, NSFontWeightRegular, NSFontWeightSemibold, NSImageScaleProportionallyUpOrDown,
    NSImageView, NSMakeRect, NSProgressIndicator, NSTextAlignmentCenter, NSTextField, NSView, NSWindow,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskClosable, NSWindowStyleMaskFullSizeContentView, NSWindowStyleMaskTitled,
    NSAttributedString, NSFontAttributeName, NSForegroundColorAttributeName, NSMutableParagraphStyle,
    NSParagraphStyleAttributeName, NSAppearance,
)
from Foundation import NSObject, NSTimer
from PyObjCTools import AppHelper

from .hud import ACCENT, AMBER, GREEN, _glass, _nsimage, _rgb, open_privacy, symbol

from .paths import HOME as DIR
from .practice import CLIPS, N_HELD_OUT, N_SENTENCES, practice_sentences, save_clip, saved_clips  # noqa: F401

WW, WH = 620, 600


def _text(parent, frame, text, size, weight=NSFontWeightRegular, alpha=0.95, center=False, color=None):
    t = NSTextField.wrappingLabelWithString_(text)
    t.setFrame_(frame)
    t.setFont_(NSFont.systemFontOfSize_weight_(size, weight))
    t.setTextColor_(color or _rgb((1, 1, 1), alpha))
    t.setSelectable_(False)
    if center:
        t.setAlignment_(NSTextAlignmentCenter)
    parent.addSubview_(t)
    return t


class GlassWindow(NSWindow):
    """Borderless so the rounded glass is the whole window (a titled window's square frame and
    traffic lights show behind rounded glass); borderless windows need opting in to key status."""

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class Onboarding(NSObject):
    """Owns the setup window. `app` is the running Mouthpiece controller."""

    def initWithApp_(self, app):
        self = objc.super(Onboarding, self).init()
        if self is None:
            return None
        self.app = app
        self.sentences = []
        self.i = 0
        self.timer = None
        self.win = GlassWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WW, WH), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.win.setTitle_("Set up Mouthpiece")
        self.win.setMovableByWindowBackground_(True)
        self.win.setHasShadow_(True)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setReleasedWhenClosed_(False)
        self.win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        outer, self.root = _glass(NSMakeRect(0, 0, WW, WH), 26, scrim=0.72)
        self.win.setContentView_(outer)
        self.win.center()
        close = NSButton.buttonWithTitle_target_action_("", self, "close:")
        close.setBordered_(False)
        close.setImage_(symbol("xmark", 11))
        close.setContentTintColor_(_rgb((1, 1, 1), 0.7))
        close.setFrame_(NSMakeRect(WW - 44, WH - 44, 26, 26))
        close.setWantsLayer_(True)
        close.layer().setCornerRadius_(13)
        close.layer().setBackgroundColor_(Quartz.CGColorCreateSRGB(1, 1, 1, 0.1))
        close.setToolTip_("Close setup (you can reopen it from the menu)")
        self.root.addSubview_(close)
        self.page = None
        return self

    # -- window --------------------------------------------------------------------
    @objc.python_method
    def show(self, download: bool = False):
        if self.page is None and not download:
            self.welcome()
        if not hasattr(self, "_shown"):
            self._shown = True
        self.app.hud.hide()  # drop the "Loading…" pill
        from AppKit import NSApplication, NSFloatingWindowLevel
        app = NSApplication.sharedApplication()
        # A menu-bar-only app isn't frontmost, so makeKeyAndOrderFront alone leaves the window hidden
        # on macOS 26. Float it, force it on screen, then activate.
        self.win.setLevel_(NSFloatingWindowLevel)
        self.win.center()
        self.win.orderFrontRegardless()
        self.win.makeKeyWindow()
        if hasattr(app, "activate"):
            app.activate()
        else:
            app.activateIgnoringOtherApps_(True)

    @objc.python_method
    def _new_page(self, icon, title, subtitle):
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        if self.page is not None:
            self.page.removeFromSuperview()
        self.page = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, WW, WH))
        self.root.addSubview_positioned_relativeTo_(self.page, -1, None)  # below the close button
        badge = NSView.alloc().initWithFrame_(NSMakeRect((WW - 64) / 2, WH - 130, 64, 64))
        badge.setWantsLayer_(True)
        badge.layer().setCornerRadius_(32)
        badge.layer().setBackgroundColor_(Quartz.CGColorCreateSRGB(*ACCENT, 0.18))
        iv = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 64, 64))
        iv.setImageScaling_(0)
        iv.setImage_(symbol(icon, 26))
        iv.setContentTintColor_(_rgb(ACCENT))
        badge.addSubview_(iv)
        self.page.addSubview_(badge)
        self.page_icon = iv
        self.page_title = _text(self.page, NSMakeRect(40, WH - 180, WW - 80, 34), title, 24, NSFontWeightBold,
                                center=True)
        self.page_sub = _text(self.page, NSMakeRect(60, WH - 240, WW - 120, 56), subtitle, 13.5, alpha=0.65,
                              center=True)
        return self.page

    @objc.python_method
    def _button(self, title, action, x, y, w=180, primary=False, h=40, parent=None):
        """Capsule button drawn by hand: system glass buttons don't render on a glass surface."""
        b = NSButton.buttonWithTitle_target_action_(title, self, action)
        b.setBordered_(False)
        b.setFrame_(NSMakeRect(x, y, w, h))
        b.setWantsLayer_(True)
        b.layer().setCornerRadius_(h / 2)
        b.layer().setBackgroundColor_(Quartz.CGColorCreateSRGB(*ACCENT, 1.0) if primary
                                      else Quartz.CGColorCreateSRGB(1, 1, 1, 0.12))
        b.layer().setBorderWidth_(0 if primary else 0.5)
        b.layer().setBorderColor_(Quartz.CGColorCreateSRGB(1, 1, 1, 0.18))
        para = NSMutableParagraphStyle.alloc().init()
        para.setAlignment_(NSTextAlignmentCenter)
        b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, {
            NSFontAttributeName: NSFont.systemFontOfSize_weight_(14, NSFontWeightSemibold),
            NSForegroundColorAttributeName: _rgb((1, 1, 1), 1.0 if primary else 0.9),
            NSParagraphStyleAttributeName: para}))
        if primary:
            b.setKeyEquivalent_("\r")
        (parent or self.page).addSubview_(b)
        return b

    @objc.python_method
    def _steps(self, n):
        labels = ["Permissions", "Your words", "Claude", "Practice", "Train"]
        w = 110
        x0 = (WW - w * len(labels)) / 2
        for k, lab in enumerate(labels):
            done, cur = k < n, k == n
            c = _rgb(ACCENT) if cur else _rgb(GREEN, 0.9) if done else _rgb((1, 1, 1), 0.35)
            _text(self.page, NSMakeRect(x0 + k * w, 28, w, 18), ("✓ " if done else "") + lab, 11.5,
                  NSFontWeightSemibold, center=True, color=c)

    @objc.python_method
    def _key(self):
        return self.app.opts.key.replace("_", " ").title()

    # -- 1. welcome -----------------------------------------------------------------
    @objc.python_method
    def welcome(self):
        p = self._new_page("mouth", "Mouthpiece reads your lips",
                           "Hold a key, mouth what you want to say without making a sound, let go, and the "
                           "text appears wherever you're typing. Setup takes about 8 minutes: it learns your "
                           "words and your face.")
        _text(p, NSMakeRect(90, 230, WW - 180, 60),
              "The camera video, your practice clips and the models trained on them never leave this Mac. "
              "Only the text you dictate is sent out, and only if you turn on Claude cleanup.",
              13, alpha=0.55, center=True)
        self._button("Get started", "goPermissions:", (WW - 200) / 2, 130, 200, primary=True)

    # -- 2. permissions -------------------------------------------------------------
    def goPermissions_(self, sender):
        p = self._new_page("lock.shield", "Three permissions",
                           "macOS asks for these once. Grant each one, then come back here.")
        self._steps(0)
        self.perm_rows = []
        rows = [("camera.fill", "Camera", "to see your mouth", "askCamera:"),
                ("keyboard", "Input Monitoring", "to notice the push-to-talk key", "askInput:"),
                ("text.cursor", "Accessibility", "to paste into the app you're using", "askAccess:")]
        for k, (icon, name, why, action) in enumerate(rows):
            y = WH - 320 - k * 64
            iv = NSImageView.alloc().initWithFrame_(NSMakeRect(80, y + 6, 28, 28))
            iv.setImage_(symbol(icon, 18))
            iv.setContentTintColor_(_rgb((1, 1, 1), 0.85))
            p.addSubview_(iv)
            _text(p, NSMakeRect(120, y + 16, 280, 20), name, 14, NSFontWeightSemibold)
            _text(p, NSMakeRect(120, y - 2, 280, 18), why, 12, alpha=0.55)
            status = NSImageView.alloc().initWithFrame_(NSMakeRect(WW - 212, y + 8, 24, 24))
            p.addSubview_(status)
            btn = self._button("Allow", action, WW - 180, y + 3, 96, h=32)
            self.perm_rows.append((status, btn))
        self.perm_next = self._button("Continue", "goWords:", (WW - 200) / 2, 90, 200, primary=True)
        # macOS keeps a denial for the life of the process, so a switch turned on in Settings
        # may not show up until Mouthpiece restarts. Offer that once an Allow has been clicked.
        self.perm_restart = self._button("Turned them on? Restart Mouthpiece", "restartForPerms:",
                                         (WW - 260) / 2, 46, 260, h=30)
        self.perm_restart.setHidden_(True)
        self._asked_perms = False
        self.refreshPerms_(None)
        self.timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0, self, "refreshPerms:", None, True)

    @objc.python_method
    def _perm_state(self):
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
        return [AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo) == 3,
                bool(Quartz.CGPreflightListenEventAccess()), bool(Quartz.CGPreflightPostEventAccess())]

    def refreshPerms_(self, timer):
        states = self._perm_state()
        for (status, btn), ok in zip(self.perm_rows, states):
            status.setImage_(symbol("checkmark.circle.fill" if ok else "circle.dashed", 18))
            status.setContentTintColor_(_rgb(GREEN) if ok else _rgb((1, 1, 1), 0.35))
            btn.setHidden_(ok)
        ready = all(states)
        self.perm_next.setEnabled_(ready)
        self.perm_next.layer().setOpacity_(1.0 if ready else 0.35)
        self.perm_restart.setHidden_(ready or not self._asked_perms)

    def restartForPerms_(self, sender):
        from AppKit import NSApplication, NSBundle
        app = str(NSBundle.mainBundle().bundlePath())
        if not app.endswith(".app"):  # not running as the app bundle: nothing to reopen
            return
        # Detach so quitting this process does not kill the delayed reopen.
        subprocess.Popen(["/bin/bash", "-c", f"sleep 0.6; open {shlex.quote(app)}"], start_new_session=True)
        NSApplication.sharedApplication().terminate_(None)

    def askCamera_(self, sender):
        from AVFoundation import AVCaptureDevice, AVMediaTypeVideo
        if AVCaptureDevice.authorizationStatusForMediaType_(AVMediaTypeVideo) == 0:
            AVCaptureDevice.requestAccessForMediaType_completionHandler_(AVMediaTypeVideo, lambda ok: None)
        else:
            open_privacy("camera")

    def askInput_(self, sender):
        self._asked_perms = True
        if not Quartz.CGRequestListenEventAccess():
            open_privacy("input")

    def askAccess_(self, sender):
        self._asked_perms = True
        if not Quartz.CGRequestPostEventAccess():
            open_privacy("accessibility")

    # -- 3. your words (Wispr import) -------------------------------------------------
    def goWords_(self, sender):
        from .personal import PHRASES, WISPR_DIR
        have = os.path.exists(PHRASES)
        p = self._new_page("text.book.closed", "Teach it your words",
                           "Most of what you'll mouth is stuff you already say. If you use Wispr Flow, Mouthpiece "
                           "can learn your phrasing and names from the dictation history Wispr Flow keeps on this "
                           "Mac. It's read here and never uploaded.")
        self._steps(1)
        self.words_status = _text(p, NSMakeRect(80, 250, WW - 160, 60), "", 13.5, alpha=0.8, center=True)
        if have:
            n = sum(1 for _ in open(PHRASES))
            self.words_status.setStringValue_(f"Already imported: {n:,} of your phrases.")
        elif not os.path.isdir(WISPR_DIR):
            self.words_status.setStringValue_("Wispr Flow isn't installed on this Mac. You can skip this.")
        can = os.path.isdir(WISPR_DIR)
        if can:
            self._button("Re-import Wispr Flow" if have else "Import Wispr Flow", "importWispr:",
                         WW / 2 - 190, 110, 180, primary=not have)
        self._button("Continue" if have else "Skip", "goClaude:", WW / 2 + (10 if can else -90), 110, 180,
                     primary=have or not can)

    def importWispr_(self, sender):
        from .personal import import_wispr
        self.words_status.setStringValue_("Reading your Wispr Flow history…")

        def work():
            try:
                st = import_wispr()
                msg = f"Imported {st['phrases']:,} phrases."
                if st["new_names"]:
                    msg += f" Found {len(st['new_names'])} names and terms (menu → Edit custom words)."
                msg += " Mouthpiece will learn your phrasing during training."
            except Exception as e:
                msg = f"Couldn't import: {e}"
            AppHelper.callAfter(self.words_status.setStringValue_, msg)
            AppHelper.callAfter(self.app.cleaner.personal.__init__)

        threading.Thread(target=work, daemon=True).start()

    # -- optional: Claude key ------------------------------------------------------------
    def goClaude_(self, sender):
        from .cleanup import api_key
        p = self._new_page("sparkles", "Sharper text with Claude",
                           "Optional. Lip reading mixes up words that look alike on the lips. A small on-device "
                           "model fixes most of that. With your own Anthropic API key, Claude does it noticeably "
                           "better, and only the dictated text is sent to Anthropic.")
        self._steps(2)
        have = bool(api_key())
        self.key_status = _text(p, NSMakeRect(80, 300, WW - 160, 40),
                                "A Claude API key is already set up." if have else
                                "Paste a key from console.anthropic.com. It's stored in your Mac's Keychain.",
                                12.5, alpha=0.6, center=True)
        if not have:
            from AppKit import NSSecureTextField
            self.key_field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(110, 250, WW - 220, 28))
            self.key_field.setPlaceholderString_("sk-ant-…")
            self.key_field.setFont_(NSFont.systemFontOfSize_(13))
            p.addSubview_(self.key_field)
            self._button("Save key", "saveKey:", WW / 2 - 190, 110, 180, primary=True)
        self._button("Continue" if have else "Skip", "goPractice:", WW / 2 + (10 if not have else -90), 110, 180,
                     primary=have)

    def saveKey_(self, sender):
        from .cleanup import save_api_key
        try:
            save_api_key(str(self.key_field.stringValue()))
        except Exception as e:
            self.key_status.setTextColor_(_rgb(AMBER))
            self.key_status.setStringValue_(f"{e}. Check it and try again, or skip.")
            return
        self.key_field.setStringValue_("")
        self.app.refresh_cleanup()
        self.goPractice_(None)

    # -- first run: model download ----------------------------------------------------
    @objc.python_method
    def goDownload(self, note: str = ""):
        from . import weights
        if getattr(self, "downloading", False):
            return  # already on it; the page shows progress
        p = self._new_page("arrow.down.circle", "Download the lip-reading models",
                           note or "Mouthpiece needs its models before it can start: the lip reader (1 GB), a "
                           "language model (215 MB), its word list and a face tracker. About 1.2 GB, one time.")
        _text(p, NSMakeRect(70, 236, WW - 140, 108),
              "About these models: they are the Auto-AVSR lip-reading models, trained on the LRS3 dataset, "
              "which is licensed for non-commercial research use only. Mouthpiece downloads them straight from "
              "their public source (Hugging Face, GitHub and Google). They aren't part of Mouthpiece and we don't "
              "redistribute them. Choosing Accept & Download means you accept those terms.",
              12, alpha=0.6, center=True)
        self.dl_bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(100, 204, WW - 200, 12))
        self.dl_bar.setIndeterminate_(False)
        self.dl_bar.setMaxValue_(weights.TOTAL)
        self.dl_bar.setHidden_(True)
        p.addSubview_(self.dl_bar)
        self.dl_status = _text(p, NSMakeRect(60, 150, WW - 120, 40), "", 12.5, alpha=0.75, center=True)
        self.dl_btn = self._button("Accept & Download", "startDownload:", (WW - 220) / 2, 90, 220, primary=True)

    def startDownload_(self, sender):
        from . import weights
        from .paths import MODELS
        self.downloading = True
        self.dl_btn.setHidden_(True)
        self.dl_bar.setHidden_(False)
        self.dl_status.setTextColor_(_rgb((1, 1, 1), 0.75))
        self.dl_status.setStringValue_("Starting…")
        last = [0.0]

        def progress(done, total):
            if time.time() - last[0] > 0.2 or done == total:
                last[0] = time.time()
                AppHelper.callAfter(self._dl_progress, done, total)

        def work():
            try:
                weights.download_all(MODELS, progress=progress)
                AppHelper.callAfter(self._dl_done, None)
            except Exception as e:
                print(f"[mouthpiece] model download failed: {e!r}")
                msg = str(e) if isinstance(e, weights.DownloadError) else f"The download stopped ({e})."
                AppHelper.callAfter(self._dl_done, msg)

        threading.Thread(target=work, name="mouthpiece-download", daemon=True).start()

    @objc.python_method
    def _dl_progress(self, done, total):
        self.dl_bar.setMaxValue_(total)
        self.dl_bar.setDoubleValue_(done)
        self.dl_status.setStringValue_(f"{done / 1e6:,.0f} of {total / 1e6:,.0f} MB")

    @objc.python_method
    def _dl_done(self, error):
        self.downloading = False
        if error:
            self.dl_status.setTextColor_(_rgb(AMBER))
            self.dl_status.setStringValue_(error)
            self.dl_btn.removeFromSuperview()
            self.dl_btn = self._button("Try again", "startDownload:", (WW - 220) / 2, 90, 220, primary=True)
            return
        self.app.weights_ready()
        if self.app.settings.get("onboarded"):
            self.close_(None)
        else:
            self.welcome()

    # -- 4. practice -----------------------------------------------------------------
    def goPractice_(self, sender):
        os.makedirs(CLIPS, exist_ok=True)
        # Every visit is a fresh round of new sentences; clips from earlier rounds are kept and the
        # model retrains on all of them, so practising again keeps improving it.
        done = {c["text"] for c in saved_clips()}
        self.sentences = [x for x in practice_sentences(N_SENTENCES * 2) if x not in done][:N_SENTENCES]
        self.i = 0
        prior = len(done)
        p = self._new_page("quote.bubble", "Mouth each sentence",
                           f"Hold {self._key()}, silently mouth the sentence at your normal pace, then let go. "
                           "Face the camera with your mouth in good light."
                           + (f" You have {prior} clips from before; these add to them." if prior else ""))
        self._steps(3)
        self.count = _text(p, NSMakeRect(40, 318, WW - 80, 18), "", 12, NSFontWeightSemibold,
                           center=True, color=_rgb(ACCENT))
        self.prompt = _text(p, NSMakeRect(50, 250, WW - 100, 64), "", 23, NSFontWeightMedium, center=True)
        self.video = NSImageView.alloc().initWithFrame_(NSMakeRect((WW - 192) / 2, 124, 192, 120))
        self.video.setImageScaling_(NSImageScaleProportionallyUpOrDown)
        self.video.setWantsLayer_(True)
        self.video.layer().setCornerRadius_(16)
        self.video.layer().setMasksToBounds_(True)
        self.video.layer().setBackgroundColor_(Quartz.CGColorCreateSRGB(0, 0, 0, 0.35))
        p.addSubview_(self.video)
        self.feedback = _text(p, NSMakeRect(60, 98, WW - 120, 20), "", 12.5, alpha=0.65, center=True)
        self._button("Redo last", "redo:", WW / 2 - 170, 56, 160, h=34)
        self._button("Skip sentence", "skip:", WW / 2 + 10, 56, 160, h=34)
        self.app.camera.ensure_open()
        self.app.onboarding = self
        self._show_sentence()

    @objc.python_method
    def _show_sentence(self):
        self.count.setStringValue_(f"SENTENCE {self.i + 1} OF {N_SENTENCES}")
        self.prompt.setStringValue_(self.sentences[self.i % len(self.sentences)])
        self.app.onboarding_text = self.sentences[self.i % len(self.sentences)]

    @objc.python_method
    def set_frame(self, video_bgr):
        if self.app.onboarding is self and video_bgr is not None:
            self.video.setImage_(_nsimage(video_bgr))

    @objc.python_method
    def clip_done(self, rec_ok: bool, message: str, rois=None, text=None, raw=None):
        """Called by the app (main thread) after each practice recording."""
        if not rec_ok:
            self.feedback.setTextColor_(_rgb(AMBER))
            self.feedback.setStringValue_(message)
            return
        path = save_clip(rois, text, raw)
        self.round_clips = getattr(self, "round_clips", []) + [path]
        self.feedback.setTextColor_(_rgb((1, 1, 1), 0.6))
        self.feedback.setStringValue_(f"Saved. The model read: \"{(raw or '').lower()}\"")
        self.i += 1
        if self.i >= N_SENTENCES:
            self.app.onboarding = None
            return self.goTrain_(None)
        self._show_sentence()

    def redo_(self, sender):
        mine = getattr(self, "round_clips", [])
        if mine and self.i > 0:
            os.remove(mine.pop())
            self.i -= 1
            self.feedback.setStringValue_("Removed the last clip. Try it again.")
            self._show_sentence()

    def skip_(self, sender):
        self.sentences.append(self.sentences.pop(self.i % len(self.sentences)))
        self._show_sentence()

    # -- 5. train ----------------------------------------------------------------------
    def goTrain_(self, sender):
        self.app.onboarding = None
        p = self._new_page("cpu", "Learning your face",
                           "Training runs on this Mac's GPU and takes about 5 minutes. You can keep working. "
                           "Mouthpiece is paused until it's done.")
        self._steps(4)
        self.progress = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(100, 300, WW - 200, 12))
        self.progress.setIndeterminate_(False)
        self.progress.setMinValue_(0)
        self.progress.setMaxValue_(100)
        p.addSubview_(self.progress)
        self.train_status = _text(p, NSMakeRect(60, 220, WW - 120, 56), "Starting…", 13.5, alpha=0.8, center=True)
        self.result = _text(p, NSMakeRect(60, 150, WW - 120, 60), "", 15, NSFontWeightSemibold, center=True)
        self.done_btn = self._button("Start using Mouthpiece", "finish:", (WW - 220) / 2, 80, 220, primary=True)
        self.done_btn.setHidden_(True)
        self.app.jobs.put(("train", self))

    @objc.python_method
    def report(self, pct: float, text: str):
        AppHelper.callAfter(self.progress.setDoubleValue_, pct)
        AppHelper.callAfter(self.train_status.setStringValue_, text)

    @objc.python_method
    def finished(self, before: float, after: "float | None", kept: bool, note: str):
        def ui():
            self.progress.setDoubleValue_(100)
            self.page_title.setStringValue_("You're all set" if (after is None or kept) else "Setup finished")
            self.page_sub.setStringValue_(f"Hold {self._key()} anywhere and mouth your words. You can retrain any time "
                                          "from the menu: more practice sentences make it better.")
            self.page_icon.setImage_(symbol("checkmark", 26))
            self.page_icon.setContentTintColor_(_rgb(GREEN))
            if after is None:
                self.result.setStringValue_(note)
            else:
                self.result.setTextColor_(_rgb(GREEN) if kept else _rgb(AMBER))
                self.result.setStringValue_(
                    f"Words read correctly on sentences it didn't train on: {1 - before:.0%} → {1 - after:.0%}"
                    + ("" if kept else "\nNo improvement, so the standard model stays."))
            self.train_status.setStringValue_(note if after is not None else "")
            self.done_btn.setHidden_(False)
        AppHelper.callAfter(ui)

    def close_(self, sender):
        self.app.onboarding = None
        self.app.camera.track_always = False
        self.win.orderOut_(None)

    def finish_(self, sender):
        from .app import load_settings, save_settings
        s = load_settings()
        s["onboarded"] = True
        save_settings(s)
        self.app.settings["onboarded"] = True  # or the next settings change writes it back out
        self.win.orderOut_(None)
        self.app.camera.track_always = False
        self.app.hud.show("done", "Mouthpiece is ready", f"Hold {self._key()} and mouth your words", 3.0)
