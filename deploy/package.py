"""只打包部署需要的文件；实际 .env 通过 SSH 单独上传。"""

import hashlib
import json
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def package(destination, include_xiucai=True):
    destination.parent.mkdir(parents=True, exist_ok=True)
    files = [(path, path.name) for path in ROOT.glob("*.py")]
    for name in ("requirements.txt", "README.md"):
        files.append((ROOT / name, name))
    for name in ("pvp-info", "秀才", "tests", "deploy"):
        if name == "秀才" and not include_xiucai:
            continue
        files.extend((path, path.relative_to(ROOT).as_posix()) for path in (ROOT / name).rglob("*")
                     if path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts)
    for source, archive_name in ((ROOT / ".cache" / "markdown-images.json", "seed/markdown-images.json"),):
        if source.is_file():
            files.append((source, archive_name))
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest() for path, name in files}

    def metadata(entry):
        entry.uid = entry.gid = 0
        entry.uname = entry.gname = "root"
        entry.mode = 0o644
        return entry

    with tarfile.open(destination, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        for path, name in files:
            archive.add(path, arcname=name, recursive=False, filter=metadata)
    destination.with_suffix(destination.suffix + ".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Packaged {len(files)} files; archive bytes: {destination.stat().st_size}")
    print(f"SHA256: {hashlib.sha256(destination.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    package(Path(sys.argv[1]).resolve(), include_xiucai="--without-xiucai" not in sys.argv)
