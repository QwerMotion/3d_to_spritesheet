#!/usr/bin/env python3
"""
Build index-offline.html: a copy of index.html with every dependency inlined, so the
tool runs from file:// with no network access at all.

It downloads the pinned library versions (three.js r160 + JSZip 3.10.1), rewrites their
ES-module syntax so all of it can live inside one plain <script>, and injects the result
into a copy of index.html.

The script is deliberately *not* `type="module"`: no browser has to fetch a module, so
opening the file directly from disk (file://, double-click) cannot hit module CORS rules.
Module semantics are preserved by wrapping the bundle in a `'use strict'` IIFE (module
top-level `this` is undefined, and the IIFE scopes identifiers the same way).

  * three.module.js            -> export {...}  becomes  const THREE = {...}
  * GLTFLoader.js              -> import {...} from 'three' becomes destructuring from THREE,
                                  wrapped in a private IIFE that publishes THREE.GLTFLoader
  * BufferGeometryUtils.js     -> same treatment (GLTFLoader needs toTrianglesDrawMode)
  * OrbitControls.js           -> same treatment, publishes THREE.OrbitControls
  * jszip.min.js               -> inlined verbatim as a classic <script>
  * the app's own module code  -> wrapped in an IIFE so its identifiers can never collide
                                  with three.js' internal top-level names, all inside one
                                  outer 'use strict' IIFE that replaces module scope

Usage:  python build-offline.py        (needs network the first time; caches under
                                        .offline-build/vendor/)
Running the generated tool needs neither Python nor a network connection.
"""
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "index.html"
OUT = HERE / "index-offline.html"
CACHE = HERE / ".offline-build" / "vendor"

THREE_VER = "0.160.0"
JSZIP_VER = "3.10.1"

LIBS = {
    "three.module.js": f"https://cdn.jsdelivr.net/npm/three@{THREE_VER}/build/three.module.js",
    "GLTFLoader.js": f"https://cdn.jsdelivr.net/npm/three@{THREE_VER}/examples/jsm/loaders/GLTFLoader.js",
    "OrbitControls.js": f"https://cdn.jsdelivr.net/npm/three@{THREE_VER}/examples/jsm/controls/OrbitControls.js",
    "BufferGeometryUtils.js": f"https://cdn.jsdelivr.net/npm/three@{THREE_VER}/examples/jsm/utils/BufferGeometryUtils.js",
    "jszip.min.js": f"https://cdn.jsdelivr.net/npm/jszip@{JSZIP_VER}/dist/jszip.min.js",
}


def die(msg):
    sys.exit(f"build-offline: {msg}")


def vendor(name):
    """Return the text of a vendored library, downloading it into the cache on first use."""
    path = CACHE / name
    if not path.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        print(f"  downloading {name}")
        try:
            with urllib.request.urlopen(LIBS[name]) as r:
                path.write_bytes(r.read())
        except Exception as e:
            die(f"could not download {LIBS[name]}: {e}")
    text = path.read_bytes().decode("utf-8")   # no newline translation
    if "</script" in text:
        die(f"{name} contains a literal </script sequence and cannot be inlined as-is")
    return text


IMPORT_RE = re.compile(r"^import\s*\{([^}]*)\}\s*from\s*'([^']+)';\s*$", re.M)
INLINE_EXPORT_RE = re.compile(r"^export\s+(function|class|const|let|var)\s+([A-Za-z_$][\w$]*)", re.M)
FINAL_EXPORT_RE = re.compile(r"^export\s*\{", re.M)


def addon_imports(src, label):
    """Names a module imports from bare specifiers (e.g. 'three'), keyed by specifier."""
    imports = {}
    for m in IMPORT_RE.finditer(src):
        names = [n.strip() for n in m.group(1).replace("\n", " ").split(",") if n.strip()]
        imports.setdefault(m.group(2), []).extend(names)
    if not imports:
        die(f"{label}: no imports found — did the library change shape?")
    return imports


def addon_body(src, label):
    """Strip imports/exports and return (namespace body, inline-exported names)."""
    body = IMPORT_RE.sub("", src)
    inline = [m.group(2) for m in INLINE_EXPORT_RE.finditer(body)]
    body = INLINE_EXPORT_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", body)

    finals = list(FINAL_EXPORT_RE.finditer(body))
    if len(finals) != 1:
        die(f"{label}: expected exactly one `export {{ ... }}` block, found {len(finals)}")
    body = FINAL_EXPORT_RE.sub("__ns = {", body, count=1)

    # module-level only: these files are tab-indented, so real statements start at column 0
    if re.search(r"^export\b", body, re.M):
        die(f"{label}: unhandled export syntax left over")
    if re.search(r"^import\b", body, re.M):
        die(f"{label}: unhandled import syntax left over")
    return body, inline


def wrap_addon(var, src, label, provide=None):
    """Wrap an addon module in an IIFE that destructures its 'three' imports from THREE.

    provide maps a relative specifier to (namespace var, source label) for the sibling
    addons that were inlined earlier — GLTFLoader pulls toTrianglesDrawMode from one.
    """
    imports = addon_imports(src, label)
    three_names = imports.pop("three", None)
    if three_names is None:
        die(f"{label}: expected an import from 'three'")

    extra = ""
    for spec, names in imports.items():
        if not spec.startswith("."):
            die(f"{label}: unexpected bare import {spec!r}")
        if not provide or spec not in provide:
            die(f"{label}: relative import {spec!r} is not provided by the bundle")
        ns_var, _ = provide[spec]
        extra += f"\tconst {{ {', '.join(names)} }} = {ns_var};\n"

    body, inline = addon_body(src, label)
    tail = f"\tObject.assign(__ns, {{ {', '.join(inline)} }});\n" if inline else ""
    return (
        f"const {var} = (function () {{\n"
        f"\tconst {{ {', '.join(three_names)} }} = THREE;\n"
        f"{extra}"
        f"\tlet __ns;\n"
        f"{body}\n"
        f"{tail}"
        f"\treturn __ns;\n"
        f"}})();\n"
    )


def build_lib_block():
    """Everything the page needs, as one module-scope block."""
    print("vendoring libraries:")
    three = vendor("three.module.js")

    # three's single trailing `export { ... };` list becomes a namespace object literal
    if three.count(" as ") and re.search(r"export\s*\{[^}]*\bas\b[^}]*\}", three):
        die("three.module.js export list uses aliases — the conversion would be wrong")
    matches = list(FINAL_EXPORT_RE.finditer(three))
    if len(matches) != 1:
        die(f"three.module.js: expected one export block, found {len(matches)}")
    if re.search(r"^export\b", three[: matches[0].start()], re.M):
        die("three.module.js: unexpected export statements before the final block")
    three = FINAL_EXPORT_RE.sub("const THREE = {", three, count=1)

    bgu = wrap_addon("__bgu", vendor("BufferGeometryUtils.js"), "BufferGeometryUtils.js")
    gltf = wrap_addon(
        "__gltf",
        vendor("GLTFLoader.js"),
        "GLTFLoader.js",
        provide={"../utils/BufferGeometryUtils.js": ("__bgu", "BufferGeometryUtils.js")},
    )
    orbit = wrap_addon("__orbit", vendor("OrbitControls.js"), "OrbitControls.js")

    return (
        "/* ==== three.js r" + THREE_VER + " (MIT) — inlined, `export` rewritten to a namespace object ==== */\n"
        + three
        + "\n/* ==== three.js addons (MIT) — inlined ==== */\n"
        + bgu
        + gltf
        + orbit
        + "THREE.GLTFLoader = __gltf.GLTFLoader;\n"
        + "THREE.OrbitControls = __orbit.OrbitControls;\n"
    )


APP_IMPORTS = re.compile(
    r"import \* as THREE from 'three';\n"
    r"import \{ GLTFLoader \} from 'three/addons/loaders/GLTFLoader\.js';\n"
    r"import \{ OrbitControls \} from 'three/addons/controls/OrbitControls\.js';\n"
)

IMPORTMAP_RE = re.compile(r'\n<script type="importmap">\n[\s\S]*?\n</script>\n')
JSZIP_TAG_RE = re.compile(r'<script src="https://cdn\.jsdelivr\.net/npm/jszip@[\d.]+/dist/jszip\.min\.js"></script>')
MODULE_RE = re.compile(r'<script type="module">\n([\s\S]*?)\n</script>')

# things that must not survive into the offline file (each implies a network fetch, a
# module fetch, or a fetch a browser may refuse from file://)
FORBIDDEN = [
    (r'<script[^>]*\ssrc=', "an external <script src> tag"),
    (r'<script[^>]*type="module"', "a <script type=\"module\"> tag"),
    (r'<script[^>]*type="importmap"', "a <script type=\"importmap\"> tag"),
    (r"\bimport\s*\(", "a dynamic import() call"),
    (r"\bimport\.meta\b", "an import.meta reference"),
    (r"\nimport\s[\w$*{]", "a leftover import statement"),
    (r"\nexport\s[\w${*]", "a leftover export statement"),
    (r"\x00", "a NUL byte"),
]


def patch_once(pattern, repl, text, what):
    # a lambda keeps re.sub from interpreting backslash escapes in the replacement
    # (library sources contain things like "\x00", which would become a real NUL byte)
    new, n = pattern.subn(lambda _m: repl, text, count=1)
    if n != 1:
        die(f"could not patch {what} in index.html (found {n} matches) — update build-offline.py")
    return new


def main():
    if not SRC.exists():
        die(f"{SRC} not found")
    html = SRC.read_text(encoding="utf-8")

    lib_block = build_lib_block()
    jszip = vendor("jszip.min.js")

    print("assembling index-offline.html:")

    # 1. drop the importmap, inline JSZip instead of the CDN tag
    html = patch_once(IMPORTMAP_RE, "\n", html, "the importmap block")
    html = patch_once(
        JSZIP_TAG_RE,
        "<script>\n/* ==== JSZip " + JSZIP_VER + " (MIT) — inlined ==== */\n" + jszip + "\n</script>",
        html,
        "the JSZip <script src> tag",
    )

    # 2. the app's module: libraries first, then the app code in its own IIFE
    m = MODULE_RE.search(html)
    if not m:
        die("could not find the app module script")
    app = APP_IMPORTS.sub("const { GLTFLoader, OrbitControls } = THREE;\n", m.group(1), count=1)
    if "from 'three'" in app:
        die("the app module still imports from 'three' — update build-offline.py")
    wrapped = (
        "\n// One classic script, no modules: nothing here is fetched, so file:// works.\n"
        "(function () {\n'use strict';\n\n"
        + lib_block
        + "\n/* ==== application (index.html) ==== */\n(function () {\n"
        + app
        + "\n})();\n\n})();\n"
    )
    html = html[: m.start()] + "<script>" + wrapped + "</script>" + html[m.end():]

    # 3. the failure hints no longer talk about a CDN
    html = patch_once(
        re.compile(
            r"\n// Watchdog: if the module script never ran \(CDN blocked / offline / file:// restrictions\), say so\."
        ),
        "\n// Watchdog: if the inline script never ran (e.g. no WebGL, or a very old browser), say so.",
        html,
        "the watchdog comment",
    )
    html = patch_once(
        re.compile(r"'three\.js could not be loaded from the CDN \(network blocked, offline, or ES modules are disabled for file:// URLs in this browser\)\.'"),
        "'The bundled renderer failed to start — this browser may lack WebGL, or be blocking canvas access.'",
        html,
        "the watchdog message",
    )
    html = patch_once(
        re.compile(r'<p class="hint">This tool loads <code>three\.js</code> and <code>JSZip</code> from a CDN[\s\S]*?</p>'),
        '<p class="hint">Everything is included in this one file (three.js r'
        + THREE_VER
        + " and JSZip "
        + JSZIP_VER
        + ', MIT) — it needs no server and no network connection.</p>',
        html,
        "the fatal-box note",
    )
    html = patch_once(
        re.compile(r'<p class="hint">If you are offline or the CDN is blocked[\s\S]*?</p>'),
        "",
        html,
        "the CDN fallback note",
    )

    html = html.replace(
        "<title>Blockbench → Spritesheet Renderer</title>",
        "<title>Blockbench → Spritesheet Renderer (offline)</title>\n"
        "<!-- Generated by build-offline.py from index.html — edit index.html and rebuild. -->",
        1,
    )

    # 4. refuse to ship a bundle that still has a fetch in it — the whole point is file://
    print("self-checks:")
    for pattern, what in FORBIDDEN:
        hit = re.search(pattern, html)
        if hit:
            line = html[: hit.start()].count("\n") + 1
            die(f"the generated file still contains {what} (line {line}) — inlining is incomplete")
    print("  no external scripts, modules, importmaps, dynamic imports or NUL bytes")
    if "'use strict';" not in html:
        die("the bundle is not wrapped in a 'use strict' IIFE — module semantics would be lost")

    # binary write: keep LF endings and the inlined sources byte-exact
    OUT.write_bytes(html.encode("utf-8"))
    size = OUT.stat().st_size
    print(f"  wrote {OUT.name} ({size/1048576:.2f} MB, self-contained)")


if __name__ == "__main__":
    main()
