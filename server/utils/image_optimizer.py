import os
import io
import warnings
from PIL import Image


class ImageTooLargeError(ValueError):
    """Raised when an uploaded raster image exceeds the safe pixel budget."""


def optimize_and_save_file(file_data: bytes, dest_path: str, max_dimension: int = 2560, quality: int = 82, max_pixels: int = 40_000_000) -> int:
    """
    Saves binary file data to disk.
    If the file is a raster image (JPEG, PNG, WEBP), it optimizes and resizes it to reduce disk usage
    while preserving visual quality. For non-images or on failure, it saves raw bytes.
    Returns the final written file size in bytes.
    """
    ext = os.path.splitext(dest_path)[1].lower()
    if ext in [".jpg", ".jpeg", ".png", ".webp"]:
        try:
            # Pillow emits a warning before its hard decompression-bomb threshold.
            # Promote that warning to an exception and enforce our lower app limit.
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(file_data)) as img:
                    w, h = img.size
                    if w <= 0 or h <= 0 or w * h > max_pixels:
                        raise ImageTooLargeError(
                            f"이미지 해상도가 허용 한도({max_pixels:,} pixels)를 초과합니다."
                        )
                    img.load()
                    # Handle EXIF orientation if present
                    try:
                        from PIL import ImageOps
                        img = ImageOps.exif_transpose(img)
                    except Exception:
                        pass

                    # Downscale if image is excessively large
                    w, h = img.size
                    if w > max_dimension or h > max_dimension:
                        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)

                    # Save optimized based on format
                if ext in [".jpg", ".jpeg"]:
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                    img.save(dest_path, "JPEG", quality=quality, optimize=True)
                elif ext == ".png":
                    # If RGBA, keep RGBA; optimize PNG compression
                    img.save(dest_path, "PNG", optimize=True)
                elif ext == ".webp":
                    img.save(dest_path, "WEBP", quality=quality, method=4)
                
                    return os.path.getsize(dest_path)
        except ImageTooLargeError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as image_error:
            raise ImageTooLargeError("이미지 해상도가 안전 한도를 초과합니다.") from image_error
        except Exception:
            # Fallback to direct raw write on non-security image processing errors.
            pass

    # Non-image or fallback
    with open(dest_path, "wb") as f:
        f.write(file_data)
    return len(file_data)
