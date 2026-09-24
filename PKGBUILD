# Maintainer: Aditya Sharma <https://github.com/AGIQdev-Aditya>
pkgname=ollux
pkgver=0.1.0
pkgrel=1
pkgdesc="Ultra-lightweight native Linux desktop client for Ollama with reasoning controls and live benchmarks"
arch=('any')
url="https://github.com/AGIQdev-Aditya/ollux"
license=('MIT')
depends=(
    'python>=3.10'
    'python-pywebview'
    'python-requests'
    'python-pypdf'
    'webkit2gtk-4.1'
)
optdepends=(
    'ollama: Local LLM runner daemon'
    'python-ddgs: Privacy-first web search integration'
)
source=("$pkgname-$pkgver.tar.gz::$url/archive/refs/tags/v$pkgver.tar.gz")
sha256sums=('SKIP')

package() {
    install -d "$pkgdir/usr/share/$pkgname"
    cp -r "$srcdir/$pkgname-$pkgver/src" "$pkgdir/usr/share/$pkgname/"
    cp -r "$srcdir/$pkgname-$pkgver/assets" "$pkgdir/usr/share/$pkgname/"

    # Launcher wrapper
    install -d "$pkgdir/usr/bin"
    cat << 'SH' > "$pkgdir/usr/bin/ollux"
#!/usr/bin/env bash
exec python3 /usr/share/ollux/src/main.py "$@"
SH
    chmod 755 "$pkgdir/usr/bin/ollux"

    # Desktop entry & Icon
    install -Dm644 "$srcdir/$pkgname-$pkgver/ollux.desktop" "$pkgdir/usr/share/applications/ollux.desktop"
    install -Dm644 "$srcdir/$pkgname-$pkgver/assets/ollux.svg" "$pkgdir/usr/share/icons/hicolor/scalable/apps/ollux.svg"
}
