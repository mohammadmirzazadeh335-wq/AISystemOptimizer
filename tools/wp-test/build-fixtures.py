#!/usr/bin/env python3
"""
Build REAL WooCommerce + Elementor plugin fixtures for AIWC integration tests.

Network note: this sandbox allows github.com / codeload.github.com / api.github.com
but blocks release-asset CDNs (objects.githubusercontent.com) and wordpress.org.
So we assemble:

  * WooCommerce <tag> from the official monorepo source (codeload) PLUS its 20
    composer dependencies fetched from the exact dist URLs recorded in
    plugins/woocommerce/composer.lock (api.github.com zipballs -> codeload), and a
    generated composer-compatible autoloader (vendor/autoload_packages.php +
    vendor/composer/*) that follows the contract expected by WooCommerce's
    src/Autoloader.php. The two monorepo-local "path" packages (blueprint,
    email-editor) are copied from the monorepo's packages/php/ directory.

  * Elementor <tag> from the official plugin repo source (codeload).

Output: tools/wp-test/fixtures/plugins/{woocommerce,elementor} — mounted into
Playground by the test server command (gitignored; rebuild with this script).
"""
import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(ROOT, "fixtures", "plugins")
TMP = os.path.join(ROOT, "fixtures", ".tmp")

WC_TAG = "11.3.0"
EL_TAG = "4.5.0-latest-1794994087"
COMPOSER_TAG = "2.8.12"

WC_ZIP = f"https://codeload.github.com/woocommerce/woocommerce/zip/refs/tags/{WC_TAG}"
EL_ZIP = f"https://codeload.github.com/elementor/elementor/zip/refs/tags/{EL_TAG}"
COMPOSER_ZIP = f"https://codeload.github.com/composer/composer/zip/refs/tags/{COMPOSER_TAG}"

WC_SKIP_DIRS = {
    "tests", "client", "bin", "php-stubs", "node_modules", ".github",
    ".wordpress-org", ".git", ".gitattributes",
}
EL_SKIP_DIRS = {"tests", "node_modules", ".github", ".git", "assets/js", "assets/css"}


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def fetch_api_file(repo, ref, path, dest):
    """Fetch one file via api.github.com contents API (handles export-ignore)."""
    import base64 as _b64
    import urllib.request as _u

    url = f"https://api.github.com/repos/{repo}/contents/{path}?ref={ref}"
    print(f"  [api ] {path}")
    req = _u.Request(url, headers={"User-Agent": "aiwc-test-build", "Accept": "application/vnd.github+json"})
    with _u.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    if "content" not in data:
        raise RuntimeError(f"no content for {path}: {data.get('message')}")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as fh:
        fh.write(_b64.b64decode(data["content"]))


def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        print(f"  [skip] {os.path.basename(dest)}")
        return
    print(f"  [get ] {url[:100]}")
    sh(["curl", "-sfL", "--retry", "3", "--max-time", "300", "-o", dest, url])


def extract(zip_path, dest, single_root_strip=True, skip_dirs=frozenset()):
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            parts = name.split("/")
            if any(p in skip_dirs for p in parts):
                continue
            if single_root_strip and len(parts) > 1:
                rel = "/".join(parts[1:])
            else:
                rel = name
            if not rel or rel.endswith("/"):
                continue
            out = os.path.join(dest, rel)
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with zf.open(info) as src, open(out, "wb") as dst:
                shutil.copyfileobj(src, dst)


def copy_tree(src, dest, skip_dirs=frozenset()):
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = os.path.relpath(root, src)
        out_root = dest if rel == "." else os.path.join(dest, rel)
        os.makedirs(out_root, exist_ok=True)
        for f in files:
            shutil.copy2(os.path.join(root, f), os.path.join(out_root, f))


# ---------------------------------------------------------------- classmap scan
DECL_RE = re.compile(
    r"^\s*(?:final\s+|abstract\s+|readonly\s+)*(?:class|interface|trait|enum)\s+(\w+)",
    re.MULTILINE,
)
NS_RE = re.compile(r"^\s*namespace\s+([^;{\s]+)\s*[;{]", re.MULTILINE)


def scan_classmap(paths, base):
    """Return {FQCN: abs_path} for classmap-style autoload entries."""
    out = {}
    for rel in paths:
        target = os.path.join(base, rel)
        files = []
        if os.path.isdir(target):
            for root, _dirs, fs in os.walk(target):
                files += [os.path.join(root, f) for f in fs if f.endswith(".php")]
        elif os.path.isfile(target):
            files = [target]
        for f in files:
            try:
                text = open(f, encoding="utf-8", errors="replace").read()
            except OSError:
                continue
            ns_m = NS_RE.search(text)
            ns = ns_m.group(1) + "\\" if ns_m else ""
            for decl in DECL_RE.finditer(text):
                out[ns + decl.group(1)] = f
    return out


class PhpExpr(str):
    """Marker for raw PHP expressions (e.g. $vendorDir . '/x')."""


def php_export(obj, indent=0):
    """Minimal PHP array/var exporter."""
    pad = "    " * (indent + 1)
    if isinstance(obj, PhpExpr):
        return str(obj)
    if isinstance(obj, str):
        return "'" + obj.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(obj, dict):
        if not obj:
            return "array()"
        items = ",\n".join(f"{pad}{php_export(k)} => {php_export(v, indent + 1)}" for k, v in obj.items())
        return "array(\n" + items + "\n" + "    " * indent + ")"
    if isinstance(obj, list):
        if not obj:
            return "array()"
        items = ",\n".join(f"{pad}{php_export(v, indent + 1)}" for v in obj)
        return "array(\n" + items + "\n" + "    " * indent + ")"
    raise TypeError(type(obj))


def generate_autoloader(vendor, packages, root_dir):
    vdir = os.path.join(vendor)
    cdir = os.path.join(vdir, "composer")
    os.makedirs(cdir, exist_ok=True)

    # Paths must be runtime-relative: inside Playground the plugin lives at a
    # different absolute path than at build time. We emit composer-style
    # `$vendorDir . '/…'` / `$baseDir . '/…'` expressions.
    psr4, psr0, files, classmap = {}, {}, [], {}

    def merge_autoload(al, kind, base_rel):
        def p(path):
            return (kind, os.path.join(base_rel, path).replace("\\", "/").lstrip("/"))

        def as_list(v):
            return [v] if isinstance(v, str) else list(v)

        for ns, paths in al.get("psr-4", {}).items():
            psr4.setdefault(ns, []).extend([p(x) for x in as_list(paths)])
        for ns, paths in al.get("psr-0", {}).items():
            psr0.setdefault(ns, []).extend([p(x) for x in as_list(paths)])
        for f in al.get("files", []):
            files.append(p(f))
        cm = al.get("classmap", [])
        if cm:
            abs_base = os.path.join(vdir, base_rel) if kind == "vendor" else os.path.join(root_dir, base_rel)
            for fqcn, abspath in scan_classmap(cm, abs_base).items():
                rel = os.path.relpath(abspath, abs_base).replace("\\", "/")
                classmap[fqcn] = p(rel)

    # Root package (the WooCommerce plugin itself).
    root_al = json.load(open(os.path.join(root_dir, "composer.json"), encoding="utf-8")).get("autoload", {})
    merge_autoload(root_al, "base", "")

    for pkg in packages:
        merge_autoload(pkg.get("autoload", {}), "vendor", pkg["name"])

    def expr_one(path_tuple):
        kind, rel = path_tuple
        var = "$vendorDir" if kind == "vendor" else "$baseDir"
        return PhpExpr(f"{var} . '/{rel}'" if rel else var)

    def expr_map(d):
        return {k: [expr_one(x) for x in v] for k, v in d.items()}

    def expr_list(a):
        return [expr_one(x) for x in a]

    header = (
        "<?php\n// generated by build-fixtures.py\n"
        "$vendorDir = dirname( __DIR__ );\n$baseDir = dirname( $vendorDir );\nreturn "
    )
    with open(os.path.join(cdir, "autoload_psr4.php"), "w", encoding="utf-8") as fh:
        fh.write(header + php_export(expr_map(psr4)) + ";\n")
    with open(os.path.join(cdir, "autoload_namespaces.php"), "w", encoding="utf-8") as fh:
        fh.write(header + php_export(expr_map(psr0)) + ";\n")
    with open(os.path.join(cdir, "autoload_classmap.php"), "w", encoding="utf-8") as fh:
        fh.write(header + php_export({k: expr_one(v) for k, v in classmap.items()}) + ";\n")
    with open(os.path.join(cdir, "autoload_files.php"), "w", encoding="utf-8") as fh:
        fh.write(header + php_export(expr_list(files)) + ";\n")
    print(f"  [auto] psr4={len(psr4)} classmap={len(classmap)} files={len(files)}")

    with open(os.path.join(vdir, "autoload_packages.php"), "w", encoding="utf-8") as fh:
        fh.write(
            """<?php
/**
 * Composer-compatible autoloader bootstrap (generated by build-fixtures.py).
 * Implements the contract expected by WooCommerce's src/Autoloader.php:
 *   - vendor/autoload_packages.php must return a truthy value
 *   - vendor/composer/autoload_psr4.php must return the PSR-4 map
 *   - vendor/composer/ClassLoader.php must exist
 */
if ( ! class_exists( 'Composer\\\\Autoload\\\\ClassLoader', false ) ) {
    require __DIR__ . '/composer/ClassLoader.php';
}
$loader = new \\Composer\\Autoload\\ClassLoader();
foreach ( require __DIR__ . '/composer/autoload_psr4.php' as $ns => $paths ) {
    $loader->setPsr4( $ns, $paths );
}
foreach ( require __DIR__ . '/composer/autoload_namespaces.php' as $ns => $paths ) {
    $loader->set( $ns, $paths );
}
$loader->addClassMap( require __DIR__ . '/composer/autoload_classmap.php' );
$loader->register( true );
foreach ( require __DIR__ . '/composer/autoload_files.php' as $file ) {
    if ( file_exists( $file ) ) {
        require_once $file;
    }
}
return true;
"""
        )
    print(f"  [auto] psr4={len(psr4)} classmap={len(classmap)} files={len(files)}")


def main():
    force = "--force" in sys.argv
    os.makedirs(TMP, exist_ok=True)
    if force and os.path.isdir(os.path.join(ROOT, "fixtures")):
        shutil.rmtree(os.path.join(ROOT, "fixtures"))
        os.makedirs(TMP, exist_ok=True)

    # ---------------------------------------------------------- WooCommerce
    wc_dir = os.path.join(FIX, "woocommerce")
    if not os.path.isdir(wc_dir):
        print("== WooCommerce source (monorepo tag) ==")
        z = os.path.join(TMP, "wc.zip")
        fetch(WC_ZIP, z)
        extract(z, os.path.join(TMP, "wc-extract"))
        src_root = os.path.join(TMP, "wc-extract", "plugins", "woocommerce")
        copy_tree(src_root, wc_dir, WC_SKIP_DIRS)
        # monorepo-local composer "path" packages live at packages/php/*.
        mono_root = os.path.join(TMP, "wc-extract")
        for name in ("blueprint", "email-editor"):
            src = os.path.join(mono_root, "packages", "php", name)
            dest = os.path.join(wc_dir, "vendor", "woocommerce", name)
            if os.path.isdir(src):
                copy_tree(src, dest)

    # The real WC build generates includes/react-admin/feature-config.php from
    # client/admin/config/core.json (bin/generate-feature-config.php, phase=core).
    fc_dest = os.path.join(wc_dir, "includes", "react-admin", "feature-config.php")
    if not os.path.exists(fc_dest):
        src_json = os.path.join(TMP, "wc-extract", "plugins", "woocommerce", "client", "admin", "config", "core.json")
        if not os.path.exists(src_json):
            fetch_api_file("woocommerce/woocommerce", WC_TAG, "plugins/woocommerce/client/admin/config/core.json", src_json)
        features = json.load(open(src_json, encoding="utf-8")).get("features", {})
        with open(fc_dest, "w", encoding="utf-8") as fh:
            fh.write("<?php\n// WARNING: Do not directly edit this file.\n// Generated by build-fixtures.py (mirrors bin/generate-feature-config.php, phase=core).\nif ( ! function_exists( 'wc_admin_get_feature_config' ) ) {\n\tfunction wc_admin_get_feature_config() {\n\t\treturn array(\n")
            for feat, on in features.items():
                fh.write(f"\t\t\t'{feat}' => {'true' if on else 'false'},\n")
            fh.write("\t\t);\n\t}\n}\n")
        print(f"  [feat] feature-config.php ({len(features)} features)")

    # The real WC build copies action-scheduler into packages/ (loaded via
    # WC_ABSPATH . 'packages/action-scheduler/action-scheduler.php').
    as_src = os.path.join(wc_dir, "vendor", "woocommerce", "action-scheduler")
    as_dst = os.path.join(wc_dir, "packages", "action-scheduler")
    if os.path.isdir(as_src) and not os.path.exists(os.path.join(as_dst, "action-scheduler.php")):
        copy_tree(as_src, as_dst)

    # composer.json / composer.lock are export-ignored in the tag zip; get via API.
    for fname in ("composer.json", "composer.lock"):
        if not os.path.exists(os.path.join(wc_dir, fname)):
            fetch_api_file("woocommerce/woocommerce", WC_TAG, f"plugins/woocommerce/{fname}", os.path.join(wc_dir, fname))

    # ---------------------------------------------------------- vendor deps
    lock_path = os.path.join(wc_dir, "composer.lock")
    lock = json.load(open(lock_path, encoding="utf-8"))
    packages = lock.get("packages", [])
    print(f"== Vendor packages ({len(packages)}) ==")
    for pkg in packages:
        name, dist = pkg["name"], pkg.get("dist", {})
        pdir = os.path.join(wc_dir, "vendor", name)
        if os.path.isdir(pdir) and os.listdir(pdir):
            continue
        if dist.get("type") == "zip":
            z = os.path.join(TMP, name.replace("/", "_") + ".zip")
            fetch(dist["url"], z)
            extract(z, pdir)
        elif dist.get("type") == "path":
            # already copied from the monorepo above
            if not os.path.isdir(pdir):
                print(f"  [WARN] path package missing: {name}")
        else:
            print(f"  [WARN] unhandled dist type for {name}: {dist.get('type')}")

    # -------------------------------------------------- composer runtime bits
    print("== Composer ClassLoader ==")
    z = os.path.join(TMP, "composer-src.zip")
    fetch(COMPOSER_ZIP, z)
    with zipfile.ZipFile(z) as zf:
        for member in ("ClassLoader.php", "InstalledVersions.php"):
            src = f"composer-{COMPOSER_TAG}/src/Composer/Autoload/{member}"
            if member == "InstalledVersions.php":
                src = f"composer-{COMPOSER_TAG}/src/Composer/InstalledVersions.php"
            dest = os.path.join(wc_dir, "vendor", "composer", member)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with zf.open(src) as s, open(dest, "wb") as d:
                shutil.copyfileobj(s, d)

    print("== Autoloader ==")
    generate_autoloader(os.path.join(wc_dir, "vendor"), packages, wc_dir)

    # ------------------------------------------------------------ Elementor
    el_dir = os.path.join(FIX, "elementor")
    if not os.path.isdir(el_dir):
        print("== Elementor source ==")
        z = os.path.join(TMP, "elementor.zip")
        fetch(EL_ZIP, z)
        extract(z, el_dir, skip_dirs=EL_SKIP_DIRS)

    print("== Sizes ==")
    for name in ("woocommerce", "elementor"):
        d = os.path.join(FIX, name)
        if os.path.isdir(d):
            out = subprocess.run(["du", "-sh", d], capture_output=True, text=True).stdout.strip()
            print(" ", out)
    print("DONE")


if __name__ == "__main__":
    main()
