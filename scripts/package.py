"""Build a source-only Windows ZIP from the explicit project file allowlist."""

import hashlib
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
files = [root / name for name in ("README.md", "START-HERE.md", "pyproject.toml",
         "setup-windows.cmd", "start.cmd", "start-claude.cmd", "demo.cmd", ".gitignore")]
for directory, suffixes in (("gpt64", {".py", ".lua", ".html", ".js", ".css"}),
                            ("docs", {".md"}), ("examples", {".json"}),
                            ("tests", {".py"}), ("scripts", {".py"})):
    files += [p for p in (root / directory).rglob("*") if p.is_file() and not p.is_symlink()
              and p.suffix in suffixes and "__pycache__" not in p.parts]
target = root / "dist/gpt64-windows-0.4.2.zip"
target.parent.mkdir(exist_ok=True)
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        if path.suffix == ".cmd":
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        item = zipfile.ZipInfo("project/" + relative, date_time=(2026, 10, 4, 0, 0, 0))
        item.compress_type = zipfile.ZIP_DEFLATED
        item.external_attr = 0o100644 << 16
        archive.writestr(item, data)
with zipfile.ZipFile(target) as archive:
    if archive.testzip() is not None:
        raise RuntimeError("ZIP verification failed")
digest = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix(".zip.sha256").write_text(f"{digest}  {target.name}\n")
print(f"{target}\n{len(files)} project files; no emulator, ROM, logs or credentials.\nSHA256: {digest}")
