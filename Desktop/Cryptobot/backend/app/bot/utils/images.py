import base64
import logging
from io import BytesIO

from PIL import Image
from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger("tbx.bot.utils")

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic")


async def extract_image_bytes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> BytesIO | None:
    msg = update.effective_message
    if msg is None:
        return None

    if getattr(msg, "photo", None):
        file_id = msg.photo[-1].file_id
        tg_file = await context.bot.get_file(file_id)
        bio = BytesIO()
        await tg_file.download_to_memory(out=bio)
        bio.seek(0)
        return bio

    if msg.document:
        doc = msg.document
        mime = (doc.mime_type or "").lower()
        fname = (doc.file_name or "").lower()
        if mime.startswith("image/") or any(fname.endswith(ext) for ext in IMAGE_EXTS):
            tg_file = await context.bot.get_file(doc.file_id)
            bio = BytesIO()
            await tg_file.download_to_memory(out=bio)
            bio.seek(0)
            return bio

    return None


def to_jpeg_base64(image_bytes: BytesIO) -> str:
    image_bytes.seek(0)
    im = Image.open(image_bytes).convert("RGB")
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=90, optimize=True)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("ascii")
