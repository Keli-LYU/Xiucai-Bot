"""从项目中的秀才目录随机选择图片。"""

import random
from pathlib import Path


XIUCAI_DIR = Path(__file__).resolve().parent / "秀才"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


def choose_xiucai_image() -> Path:
    images = [path for path in XIUCAI_DIR.iterdir()
              if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES]
    if not images:
        raise FileNotFoundError("秀才目录中没有可发送的图片。")
    return random.choice(images)
