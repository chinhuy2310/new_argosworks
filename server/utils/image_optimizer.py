import os
import io
import warnings
from PIL import Image


class ImageTooLargeError(ValueError):
    """Raised when an uploaded raster image exceeds the safe pixel budget."""


def optimize_and_save_file(
    file_data: bytes,
    dest_path: str,
    max_dimension: int = 2560,
    quality: int = 82,
    max_pixels: int = 40_000_000,
) -> int:
    """
    Save uploaded bytes, optimizing supported raster images.
    Reject decompression bombs instead of falling back to storing the original bytes.
    """
    ext = os.path.splitext(dest_path)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        try:
            # Promote Pillow's decompression-bomb warning to an exception.
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(file_data)) as img:
                    width, height = img.size
                    if width <= 0 or height <= 0 or width * height > max_pixels:
                        raise ImageTooLargeError(
                            f"이미지 해상도가 허용 한도({max_pixels:,} pixels)를 초과합니다."
                        )
                    img.load()

                    try:
                        from PIL import ImageOps
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass

                    width, height = img.size
                    if width > max_dimension or height > max_dimension:
                        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

                    if ext in [".jpg", ".jpeg"]:
                        if img.mode != "RGB":
                            img = img.convert("RGB")
                        img.save(dest_path, "JPEG", quality=quality, optimize=True)
                    elif ext == ".png":
                        img.save(dest_path, "PNG", optimize=True)
                    elif ext == ".webp":
                        img.save(dest_path, "WEBP", quality=quality, method=4)

                    return os.path.getsize(dest_path)
        except ImageTooLargeError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as image_error:
            raise ImageTooLargeError("이미지 해상도가 안전 한도를 초과합니다.") from image_error
        except Exception:
            # Keep the historical behavior for corrupt/non-image files with image suffixes.
            pass

    with open(dest_path, "wb") as output_file:
        output_file.write(file_data)
    return len(file_data)
