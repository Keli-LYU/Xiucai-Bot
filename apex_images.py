"""为超过 QQ 5 MB 上传限制的静态地图生成缓存副本，保留 Wiki 原图。"""

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image

MAX_IMAGE_BYTES = 5 * 1024 * 1024
CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "apex-images"


def prepare_apex_image(path: Path, cache_dir: Path = CACHE_DIR) -> Path:
    if path.stat().st_size <= MAX_IMAGE_BYTES:
        return path
    data = path.read_bytes()
    target = cache_dir / f"{hashlib.sha256(data).hexdigest()}-1600-q85.jpg"
    if target.is_file() and 0 < target.stat().st_size <= MAX_IMAGE_BYTES:
        return target
    with Image.open(BytesIO(data)) as original:
        if getattr(original, "is_animated", False):
            raise ValueError("超大动图不能作为静态地图压缩。")
        image = original.convert("RGB")
        image.thumbnail((1600, 1600))
        output = BytesIO()
        image.save(output, format="JPEG", quality=85, optimize=True)
    if output.tell() > MAX_IMAGE_BYTES:
        raise ValueError("地图缓存副本仍超过 5 MB。")
    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(output.getvalue())
    temporary.replace(target)
    return target
