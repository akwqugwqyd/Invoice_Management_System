from __future__ import annotations

import io
import os
import re
from pathlib import Path
from typing import Any

import pymupdf
import pytesseract
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")
configured_tesseract = os.getenv("TESSERACT_CMD")
if configured_tesseract:
    pytesseract.pytesseract.tesseract_cmd = configured_tesseract
elif os.name == "nt":
    standard_tesseract_path = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    if standard_tesseract_path.is_file():
        pytesseract.pytesseract.tesseract_cmd = str(standard_tesseract_path)


class InvoiceItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    material_description: str = Field(min_length=1)
    quantity: float = Field(ge=0, allow_inf_nan=False)
    price: float = Field(ge=0, allow_inf_nan=False)


class InvoiceDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vendor_name: str | None = None
    invoice_no: str | None = None
    invoice_state: str | None = None
    items: list[InvoiceItem] = Field(default_factory=list)


def extract_text(document: bytes, filename: str) -> str:
    suffix = filename.lower().rsplit(".", maxsplit=1)[-1] if "." in filename else ""
    if suffix == "pdf":
        with pymupdf.open(stream=document, filetype="pdf") as pdf:
            if len(pdf) > 20:
                raise ValueError("PDF exceeds the 20-page processing limit")
            return "\n".join(
                pytesseract.image_to_string(page.get_pixmap(dpi=200).pil_image())
                for page in pdf
            )

    if suffix not in {"png", "jpg", "jpeg", "tif", "tiff", "bmp"}:
        raise ValueError(f"Unsupported invoice file type: {suffix or 'unknown'}")

    with Image.open(io.BytesIO(document)) as image:
        image = ImageOps.grayscale(image)
        return pytesseract.image_to_string(image)


def parse_invoice_text(text: str) -> InvoiceDraft:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    vendor_name = lines[0] if lines else None

    invoice_match = re.search(
        r"\binvoice\s*(?:number|no\.?|#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9/-]*)",
        text,
        flags=re.IGNORECASE,
    )
    indian_states = (
        "Andaman and Nicobar Islands",
        "Arunachal Pradesh",
        "Himachal Pradesh",
        "Jammu and Kashmir",
        "Madhya Pradesh",
        "Uttar Pradesh",
        "Andhra Pradesh",
        "Chhattisgarh",
        "Dadra and Nagar Haveli and Daman and Diu",
        "Himachal Pradesh",
        "Tamil Nadu",
        "Uttarakhand",
        "West Bengal",
        "Maharashtra",
        "Telangana",
        "Rajasthan",
        "Karnataka",
        "Jharkhand",
        "Meghalaya",
        "Nagaland",
        "Puducherry",
        "Lakshadweep",
        "Chandigarh",
        "Mizoram",
        "Manipur",
        "Sikkim",
        "Tripura",
        "Haryana",
        "Punjab",
        "Assam",
        "Odisha",
        "Bihar",
        "Goa",
        "Gujarat",
        "Kerala",
        "Delhi",
    )
    state_pattern = "|".join(
        re.escape(state) for state in sorted(set(indian_states), key=len, reverse=True)
    )
    state_match = re.search(
        rf"\b({state_pattern})\s+\d{{6}}\b",
        text,
        flags=re.IGNORECASE,
    )

    items: list[InvoiceItem] = []
    for line in lines:
        match = re.match(
            r"^(?P<description>.+?)\s+(?P<quantity>\d+(?:\.\d+)?)\s+"
            r"(?:(?:₹|INR|Rs\.?)\s*)?"
            r"(?P<price>\d+(?:,\d{2,3})*(?:\.\d{2})?)$",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            items.append(
                InvoiceItem(
                    material_description=match.group("description").strip(),
                    quantity=float(match.group("quantity")),
                    price=float(match.group("price").replace(",", "")),
                )
            )

    return InvoiceDraft(
        vendor_name=vendor_name,
        invoice_no=invoice_match.group(1) if invoice_match else None,
        invoice_state=state_match.group(1).title() if state_match else None,
        items=items,
    )


def draft_from_text(text: str) -> dict[str, Any]:
    return parse_invoice_text(text).model_dump()
