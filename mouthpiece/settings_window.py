"""Settings: keep training when you want to, plus the few options Mouthpiece has."""
from __future__ import annotations

import os
import time

import objc
import Quartz
from AppKit import (
    NSAttributedString, NSBackingStoreBuffered, NSButton, NSColor, NSFont, NSFontAttributeName,
    NSFontWeightBold, NSFontWeightSemibold, NSForegroundColorAttributeName, NSMakeRect,
    NSMutableParagraphStyle, NSParagraphStyleAttributeName, NSPopUpButton, NSSwitch, NSTextAlignmentCenter,
    NSView, NSWindowStyleMaskBorderless, NSAppearance,
)
from Foundation import NSObject

from .hud import ACCENT, AMBER, GREEN, _glass, _rgb, symbol
from .onboarding import GlassWindow, _text
from .paths import HOME, PERSONAL_VSR

SW, SH = 560, 700


def _capsule(target, title, action, frame, primary=False):
    b = NSButton.buttonWithTitle_target_action_(title, target, action)
    b.setBordered_(False)
    b.setFrame_(frame)
    b.setWantsLayer_(True)
    b.layer().setCornerRadius_(frame.size.height / 2)
    b.layer().setBackgroundColor_(Quartz.CGColorCreateSRGB(*ACCENT, 1.0) if primary
                                  else Quartz.CGColorCreateSRGB(1, 1, 1, 0.12))
    para = NSMutableParagraphStyle.alloc().init()
    para.setAlignment_(NSTextAlignmentCenter)
    b.setAttributedTitle_(NSAttributedString.alloc().initWithString_attributes_(title, {
        NSFontAttributeName: NSFont.systemFontOfSize_weight_(13, NSFontWeightSemibold),
        NSForegroundColorAttributeName: _rgb((1, 1, 1), 1.0), NSParagraphStyleAttributeName: para}))
    return b


class Settings(NSObject):
    def initWithApp_(self, app):
        self = objc.super(Settings, self).init()
        if self is None:
            return None
        self.app = app
        self.win = GlassWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, SW, SH), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        self.win.setTitle_("Mouthpiece Settings")
        self.win.setMovableByWindowBackground_(True)
        self.win.setOpaque_(False)
        self.win.setBackgroundColor_(NSColor.clearColor())
        self.win.setHasShadow_(True)
        self.win.setReleasedWhenClosed_(False)
        self.win.setAppearance_(NSAppearance.appearanceNamed_("NSAppearanceNameDarkAqua"))
        outer, self.root = _glass(NSMakeRect(0, 0, SW, SH), 26, scrim=0.72)
        self.win.setContentView_(outer)
        self.page = None
        return self

    @objc.python_method
    def show(self):
        self.build()
        from AppKit import NSApplication, NSFloatingWindowLevel
        self.win.setLevel_(NSFloatingWindowLevel)
        self.win.center()
        self.win.orderFrontRegardless()
        self.win.makeKeyWindow()
        app = NSApplication.sharedApplication()
        app.activate() if hasattr(app, "activate") else app.activateIgnoringOtherApps_(True)

    @objc.python_method
    def build(self):
        from .onboarding import saved_clips
        if self.page is not None:
            self.page.removeFromSuperview()
        p = self.page = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, SW, SH))
        self.root.addSubview_(p)
        s = self.app.settings
        close = NSButton.buttonWithTitle_target_action_("", self, "close:")
        close.setBordered_(False)
        close.setImage_(symbol("xmark", 11))
        close.setContentTintColor_(_rgb((1, 1, 1), 0.7))
        close.setFrame_(NSMakeRect(SW - 44, SH - 44, 26, 26))
        p.addSubview_(close)
        _text(p, NSMakeRect(36, SH - 64, 300, 30), "Settings", 22, NSFontWeightBold)

        # -- training ------------------------------------------------------------------
        y = SH - 96
        _text(p, NSMakeRect(36, y, 400, 18), "TRAINING ON YOUR FACE", 11, NSFontWeightSemibold, color=_rgb(ACCENT))
        n = len(saved_clips())
        t = s.get("training")
        if t:
            line = (f"{t['clips']} practice clips. Last training ({time.strftime('%b %-d', time.localtime(t['at']))}): "
                    f"words read correctly on held-out sentences {1 - t['before']:.0%} → {1 - t['after']:.0%}"
                    + ("" if t["kept"] else ", not better, so the standard model is used."))
        else:
            line = f"{n} practice clips so far." + (" Not trained yet." if not os.path.exists(PERSONAL_VSR) else "")
        from . import corrections
        nc = corrections.count()
        if nc:
            line += f" Plus {nc} learned from your corrections."
        _text(p, NSMakeRect(36, y - 42, SW - 72, 38), line, 13, alpha=0.8)
        _text(p, NSMakeRect(36, y - 76, SW - 72, 32),
              "Each round is 24 new sentences (about 5 minutes) and it retrains on everything you've recorded. "
              "More rounds keep improving it.", 12, alpha=0.55)
        p.addSubview_(_capsule(self, "Practice & train more", "trainMore:", NSMakeRect(36, y - 118, 220, 34), True))
        if os.path.exists(PERSONAL_VSR):
            p.addSubview_(_capsule(self, "Reset face model", "resetFace:", NSMakeRect(270, y - 118, 170, 34)))

        # -- general (rows 34 pt apart) ---------------------------------------------------
        y = SH - 256
        _text(p, NSMakeRect(36, y, 400, 18), "GENERAL", 11, NSFontWeightSemibold, color=_rgb(ACCENT))
        from .hotkey import KEYS
        self.key_popup = self._popup(p, y - 38, "Push-to-talk key",
                                     [k.replace("_", " ").title() for k in KEYS],
                                     self.app.opts.key.replace("_", " ").title(), "pickKey:")
        from .camera import list_cameras
        cams = list_cameras()
        cur = s.get("camera", "auto")
        cur_name = next((c["name"] for c in cams if c["id"] == cur), "Automatic (built-in)")
        self.cam_popup = self._popup(p, y - 72, "Camera", ["Automatic (built-in)"] + [c["name"] for c in cams],
                                     cur_name, "pickCam:")
        self.ctx_switch = self._switch(p, y - 106, "Use names from the app I'm typing in",
                                       s.get("use_context", True), "toggleContext:")
        self.clip_switch = self._switch(p, y - 140, "Keep my last 100 clips to measure accuracy",
                                        s.get("save_clips", True), "toggleClips:")
        self.learn_switch = self._switch(p, y - 174, "Learn from words I correct after pasting",
                                         s.get("learn_corrections", True), "toggleLearn:")
        self.whisper_switch = self._switch(p, y - 208, "Whisper mode: lips + a soft whisper (uses the mic)",
                                           s.get("whisper", False), "toggleWhisper:")
        from .mic import input_devices
        mic = self.app.mic
        self.mic_popup = self._popup(p, y - 242, "Whisper mic", ["Automatic (built-in)"] + input_devices(),
                                     mic.name or "Automatic (built-in)", "pickMic:")
        _text(p, NSMakeRect(36, y - 264, SW - 72, 18),
              f"Mic lag: {mic.lag * 1000:.0f} ms (learned as you whisper)"
              + ("" if mic.name is None or mic.name in input_devices() else f". {mic.name} isn't connected."),
              12, alpha=0.55)

        # -- cleanup: Claude API key ----------------------------------------------------
        y = SH - 560
        from .cleanup import api_key
        _text(p, NSMakeRect(36, y, 400, 18), "TEXT CLEANUP", 11, NSFontWeightSemibold, color=_rgb(ACCENT))
        in_env = bool(os.environ.get("ANTHROPIC_API_KEY"))
        have = bool(api_key())
        self.key_status = _text(p, NSMakeRect(36, y - 22, SW - 72, 18),
                                f"Using: {self.app.cleaner.label()}. "
                                + ("Claude key from the environment." if in_env else
                                   "Claude key saved in your Keychain." if have else
                                   "Add a Claude API key for sharper text."),
                                12, alpha=0.55)
        from AppKit import NSSecureTextField
        self.key_field = NSSecureTextField.alloc().initWithFrame_(NSMakeRect(36, y - 56, 270, 26))
        self.key_field.setPlaceholderString_("Claude API key (sk-ant-…)" if not have else "•••••••• saved")
        self.key_field.setFont_(NSFont.systemFontOfSize_(13))
        p.addSubview_(self.key_field)
        p.addSubview_(_capsule(self, "Save", "saveKey:", NSMakeRect(316, y - 57, 90, 28), True))
        if have and not in_env:
            p.addSubview_(_capsule(self, "Remove", "removeKey:", NSMakeRect(414, y - 57, 110, 28)))

        p.addSubview_(_capsule(self, "Open my data folder", "openData:", NSMakeRect(36, 28, 190, 32)))
        _text(p, NSMakeRect(240, 28, SW - 276, 32), "Your clips, phrases and trained models. Never uploaded.",
              11.5, alpha=0.5)

    @objc.python_method
    def _row_label(self, p, y, label, w=260):
        _text(p, NSMakeRect(36, y + 6, w, 20), label, 13.5)

    @objc.python_method
    def _popup(self, p, y, label, items, current, action):
        self._row_label(p, y, label)
        pop = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(SW - 256, y, 220, 30), False)
        pop.addItemsWithTitles_(items)
        pop.selectItemWithTitle_(current)
        pop.setTarget_(self)
        pop.setAction_(action)
        p.addSubview_(pop)
        return pop

    @objc.python_method
    def _switch(self, p, y, label, on, action):
        self._row_label(p, y, label, SW - 36 - 42 - 36 - 12)
        sw = NSSwitch.alloc().initWithFrame_(NSMakeRect(SW - 36 - 42, y + 4, 42, 24))
        sw.setState_(1 if on else 0)
        sw.setTarget_(self)
        sw.setAction_(action)
        p.addSubview_(sw)
        return sw

    # -- actions ------------------------------------------------------------------------
    @objc.python_method
    def _save(self):
        from .app import save_settings
        save_settings(self.app.settings)

    def close_(self, sender):
        self.win.orderOut_(None)

    def trainMore_(self, sender):
        self.win.orderOut_(None)
        self.app.show_setup(start_at="practice")

    def resetFace_(self, sender):
        if os.path.exists(PERSONAL_VSR):
            os.remove(PERSONAL_VSR)
        self.app.settings.pop("training", None)
        self._save()
        self.app.jobs.put(("reload",))
        self.build()

    def pickKey_(self, sender):
        from .hotkey import KEYS
        key = sender.titleOfSelectedItem().lower().replace(" ", "_")
        self.app.opts.key = key
        self.app.ptt.keycode, self.app.ptt.mask = KEYS[key]
        self.app.settings["key"] = key
        self._save()

    def pickCam_(self, sender):
        from .camera import list_cameras
        name = sender.titleOfSelectedItem()
        cam = next((c["id"] for c in list_cameras() if c["name"] == name), "auto")
        self.app.settings["camera"] = cam
        self.app.camera.set_source(cam)
        self._save()

    def toggleContext_(self, sender):
        self.app.settings["use_context"] = bool(sender.state())
        self._save()

    def toggleClips_(self, sender):
        self.app.settings["save_clips"] = bool(sender.state())
        self._save()

    def toggleWhisper_(self, sender):
        on = bool(sender.state())
        self.app.settings["whisper"] = on
        self._save()
        if on and self.app.av_reader is None:
            self.app.jobs.put(("whisper",))  # downloads the model the first time
        elif on and self.app.mic.keep_open:
            self.app.mic.open()
        elif not on:
            self.app.mic.close()  # lets AirPods drop back out of call mode

    def pickMic_(self, sender):
        name = sender.titleOfSelectedItem()
        name = None if name.startswith("Automatic") else name
        self.app.mic.close()
        self.app.mic = self.app.make_mic(name)
        self.app.settings["mic"] = name
        self._save()
        if self.app.whisper_on and self.app.mic.keep_open:
            self.app.mic.open()
        self.build()  # refresh the learned-lag line

    def toggleLearn_(self, sender):
        self.app.settings["learn_corrections"] = bool(sender.state())
        self._save()

    def saveKey_(self, sender):
        from .cleanup import save_api_key
        key = str(self.key_field.stringValue())
        if not key.strip():
            return
        try:
            save_api_key(key)
        except Exception as e:
            self.key_status.setTextColor_(_rgb(AMBER))
            self.key_status.setStringValue_(f"{e}. Check it and try again.")
            return
        self.app.refresh_cleanup()
        self.build()

    def removeKey_(self, sender):
        from .cleanup import forget_api_key
        forget_api_key()
        self.app.refresh_cleanup()
        self.build()

    def openData_(self, sender):
        os.system(f'open "{HOME}"')
