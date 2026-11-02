# Releasing Mouthpiece (macOS)

Ships as a Developer ID–signed, notarized `.dmg` for direct download (not the Mac App Store, no sandbox).

```bash
scripts/release.sh   # → dist/Mouthpiece-<version>.dmg
```

Without any setup it builds an **ad-hoc** signed app: fine on this Mac, blocked by Gatekeeper anywhere else.
The version comes from `pyproject.toml`. Model weights are **not** in the bundle (non-commercial license);
the app downloads them on first run into `~/Library/Application Support/Mouthpiece/weights`.

## One-time setup

1. Enroll in the Apple Developer Program (developer.apple.com/programs, $99/yr, as AstroBytes).
2. Create a **Developer ID Application** certificate (Xcode → Settings → Accounts → Manage Certificates → +,
   or developer.apple.com → Certificates). Check it is in the login keychain:
   `security find-identity -v -p codesigning`
3. Store notarization credentials (app-specific password from appleid.apple.com):
   ```bash
   xcrun notarytool store-credentials mouthpiece-notary \
     --apple-id <apple-id> --team-id <TEAMID> --password <app-specific-password>
   ```

## Each release

```bash
export MOUTHPIECE_SIGN_ID="Developer ID Application: AstroBytes (TEAMID)"
export MOUTHPIECE_NOTARY_PROFILE=mouthpiece-notary
scripts/release.sh
```

It builds `dist/Mouthpiece.app` (`scripts/make_app.py --release`), signs every Mach-O inside-out with
`--options runtime --timestamp`, smoke-imports every native module under that signature, notarizes and
staples the app, builds the DMG (`hdiutil`, with an Applications link), signs, notarizes and staples it.

Afterwards, on the DMG and on the app copied out of it:

```bash
spctl -a -vv -t install dist/Mouthpiece-*.dmg      # source=Notarized Developer ID
xcrun stapler validate dist/Mouthpiece-*.dmg
spctl -a -vv /Applications/Mouthpiece.app           # accepted, source=Notarized Developer ID
xcrun stapler validate /Applications/Mouthpiece.app
codesign -dv --verbose=4 /Applications/Mouthpiece.app  # flags=0x10000(runtime), TeamIdentifier set
```

Then on a second Mac (or a fresh user): open the DMG, drag to Applications, launch, and walk through
Camera / Input Monitoring / Accessibility and the weights download.

## Entitlements (`scripts/Mouthpiece.entitlements`)

Hardened runtime with only:

- `com.apple.security.device.camera`: lip reading. Without it the hardened runtime denies the camera with no prompt.
- `com.apple.security.device.audio-input`: whisper mode's microphone, same rule.

Deliberately **not** included:

- `cs.allow-jit`, `cs.allow-unsigned-executable-memory`: tested by signing with `--options runtime` and running
  `mouthpiece file … --cleanup local` (torch on MPS, MediaPipe, MLX) plus the menu-bar app. Everything ran.
- `cs.disable-library-validation`: every dylib/.so is signed with our own Team ID, so validation should pass.
  This could not be tested ad-hoc: ad-hoc signatures have no Team ID, so dyld refuses even libpython.
  `release.sh` imports every native module under the real signature. If that fails with "different Team IDs",
  add this entitlement and note why here.

## Not done yet

- Auto-update (Sparkle, with an EdDSA-signed appcast).
- Licensing / payments.
