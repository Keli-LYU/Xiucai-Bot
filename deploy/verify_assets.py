"""校验并展开独立图片包，只允许写入发布目录的秀才子目录。"""

import hashlib
import json
import os
import sys
import tarfile
from pathlib import Path, PurePosixPath


def extract(release, incoming, manifest_path):
    release = release.resolve()
    if release.parent != Path("/opt/qq-bot/releases") or not release.is_dir():
        raise ValueError("Unexpected release directory")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for archive_name, expected in manifest.items():
        path = incoming / archive_name
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Checksum mismatch: {archive_name}")
    count = 0
    for archive_name in manifest:
        with tarfile.open(incoming / archive_name, "r:gz") as archive:
            for member in archive.getmembers():
                name = PurePosixPath(member.name)
                if (not member.isfile() or len(name.parts) != 2 or name.parts[0] != "秀才"
                        or name.name in {".", ".."}):
                    raise ValueError("Unexpected asset archive member")
                target = release.joinpath(*name.parts)
                target.parent.mkdir(mode=0o750, exist_ok=True)
                if target.is_symlink():
                    raise ValueError("Refusing to replace asset symlink")
                source = archive.extractfile(member)
                if source is None:
                    raise ValueError("Missing image data")
                target.write_bytes(source.read())
                os.chmod(target, 0o640)
                count += 1
    print(f"Verified and extracted {count} images from {len(manifest)} archives")


if __name__ == "__main__":
    extract(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
