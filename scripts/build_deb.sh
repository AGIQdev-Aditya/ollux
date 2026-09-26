#!/usr/bin/env bash
# ollux — Debian / Ubuntu (.deb) Automated Package Builder
# Builds a standalone .deb package conforming to Debian packaging standards.

set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)"
VERSION="0.1.0"
PKGNAME="ollux"
PKGDIR="/tmp/${PKGNAME}_deb_build"

echo "=========================================="
echo "📦 Building Debian/Ubuntu Package: ${PKGNAME}_${VERSION}_all.deb"
echo "=========================================="

rm -rf "$PKGDIR"
mkdir -p "$PKGDIR/DEBIAN"
mkdir -p "$PKGDIR/usr/share/ollux"
mkdir -p "$PKGDIR/usr/bin"
mkdir -p "$PKGDIR/usr/share/applications"
mkdir -p "$PKGDIR/usr/share/icons/hicolor/scalable/apps"

# Copy source tree and assets
cp -r "$DIR/src" "$PKGDIR/usr/share/ollux/"
cp -r "$DIR/assets" "$PKGDIR/usr/share/ollux/"
install -m 755 "$DIR/run.sh" "$PKGDIR/usr/bin/ollux"
install -m 644 "$DIR/ollux.desktop" "$PKGDIR/usr/share/applications/ollux.desktop"
install -m 644 "$DIR/assets/ollux.svg" "$PKGDIR/usr/share/icons/hicolor/scalable/apps/ollux.svg"

# Create Debian Control file
cat << EOF > "$PKGDIR/DEBIAN/control"
Package: ${PKGNAME}
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1 | gir1.2-webkit2-4.0, python3-requests, python3-pypdf
Recommends: ollama
Maintainer: Aditya Sharma <contact@ollux.org>
Description: Ultra-lightweight native Linux desktop client for Ollama
 Native WebKit2GTK desktop client providing reasoning controls,
 document attachments, and DuckDuckGo search integration.
EOF

# Build package using dpkg-deb if available
if command -v dpkg-deb >/dev/null 2>&1; then
    dpkg-deb --build "$PKGDIR" "$DIR/${PKGNAME}_${VERSION}_all.deb"
    echo "✓ Package successfully generated at: $DIR/${PKGNAME}_${VERSION}_all.deb"
else
    echo "⚠️ dpkg-deb not found on this system. Prepared staging tree at: $PKGDIR"
    echo "Run 'dpkg-deb --build $PKGDIR ${PKGNAME}_${VERSION}_all.deb' on a Debian/Ubuntu system."
fi

rm -rf "$PKGDIR"
