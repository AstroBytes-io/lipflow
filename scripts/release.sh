#!/usr/bin/env bash
# Build dist/Mouthpiece-<version>.dmg: self-contained app, signed, notarized when configured.
#   MOUTHPIECE_SIGN_ID         "Developer ID Application: …"  (unset = ad-hoc, local use only)
#   MOUTHPIECE_NOTARY_PROFILE  notarytool keychain profile    (unset = skip notarization)
# See RELEASING.md.
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml | head -1)
APP=dist/Mouthpiece.app
DMG=dist/Mouthpiece-$VERSION.dmg
SIGN_ID=${MOUTHPIECE_SIGN_ID:-}
PROFILE=${MOUTHPIECE_NOTARY_PROFILE:-}

uv run python scripts/make_app.py --release --dest dist  # embeds Python, signs inside-out
# Every native module must load under the final signature (catches library-validation failures).
"$APP/Contents/Resources/python/bin/python3.12" -I -B -c \
  "import torch, mlx.core, mediapipe, cv2, av, objc, AppKit, AVFoundation, Quartz, sounddevice, sentencepiece"
codesign --verify --deep --strict "$APP"  # after the import: proves nothing wrote into the bundle
echo "✓ app signed ($([[ -n $SIGN_ID ]] && echo "$SIGN_ID" || echo ad-hoc)) and loads"

notarize() {  # $1 = .zip or .dmg
  xcrun notarytool submit "$1" --keychain-profile "$PROFILE" --wait
}

if [[ -n $PROFILE ]]; then
  [[ -n $SIGN_ID ]] || { echo "MOUTHPIECE_NOTARY_PROFILE needs MOUTHPIECE_SIGN_ID" >&2; exit 1; }
  ditto -c -k --keepParent "$APP" dist/Mouthpiece.zip
  notarize dist/Mouthpiece.zip
  rm dist/Mouthpiece.zip
  xcrun stapler staple "$APP"  # fails (and stops the script) if notarization was rejected
else
  echo "• MOUTHPIECE_NOTARY_PROFILE unset: skipping notarization (Gatekeeper will block this build elsewhere)"
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
ditto "$APP" "$STAGE/Mouthpiece.app"
ln -s /Applications "$STAGE/Applications"
rm -f "$DMG"
hdiutil create -volname "Mouthpiece $VERSION" -srcfolder "$STAGE" -fs HFS+ -format ULMO -quiet "$DMG"

if [[ -n $SIGN_ID ]]; then
  codesign --force --sign "$SIGN_ID" --timestamp "$DMG"
fi
if [[ -n $PROFILE ]]; then
  notarize "$DMG"
  xcrun stapler staple "$DMG"
fi

echo "✓ $DMG ($(du -h "$DMG" | cut -f1); app $(du -sh "$APP" | cut -f1))"
