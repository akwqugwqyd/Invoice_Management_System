from __future__ import annotations

import pymupdf


SYNTHETIC_INVOICES = {
    "INV-IND-001": {
        "vendor": "Bharat Office Solutions Pvt Ltd",
        "gstin": "27AABCU9603R1ZM",
        "invoice_no": "BOS/2026-27/001",
        "address": "Office 12, Shivaji Nagar, Pune, Maharashtra 411005",
        "items": [
            ("A4 copier paper, 75 GSM", 10, 2450.00),
            ("Ball pen set, blue", 25, 120.00),
        ],
    },
    "INV-IND-002": {
        "vendor": "Sunrise Electricals India",
        "gstin": "29AAQCS1245F1Z6",
        "invoice_no": "SE/26-27/048",
        "address": "18 MG Road, Bengaluru, Karnataka 560001",
        "items": [
            ("LED panel light, 18 W", 12, 1850.00),
            ("Copper wire, 2.5 sq mm", 3, 4250.00),
        ],
    },
    "INV-IND-003": {
        "vendor": "Aarav Industrial Supplies",
        "gstin": "24AARCA7284N1ZP",
        "invoice_no": "AIS/2026-27/113",
        "address": "Plot 18, GIDC Estate, Ahmedabad, Gujarat 382430",
        "items": [
            ("Stainless steel fasteners, assorted M8-M12", 4.5, 1250.00),
            ("Industrial safety gloves, cut-resistant", 12, 385.50),
            ("PVC insulated copper cable, 2.5 sq mm", 3.75, 4820.00),
            ("Heavy-duty mounting brackets, galvanized", 8, 675.25),
        ],
    },
}


def synthetic_records(base_url: str) -> dict[str, list[dict[str, str]]]:
    root = base_url.rstrip("/")
    return {
        "invoices": [
            {"id": invoice_id, "file_url": f"{root}/sample-api/files/{invoice_id}.pdf"}
            for invoice_id in SYNTHETIC_INVOICES
        ]
    }


def synthetic_invoice_pdf(invoice_id: str) -> bytes:
    invoice = SYNTHETIC_INVOICES[invoice_id]
    document = pymupdf.open()
    page = document.new_page(width=612, height=792)
    page.insert_text((54, 60), invoice["vendor"], fontsize=20, fontname="helv")
    page.insert_text((54, 100), "TAX INVOICE", fontsize=15, fontname="helv")
    page.insert_text((54, 132), f"GSTIN: {invoice['gstin']}", fontsize=10)
    page.insert_text((54, 150), f"Invoice No: {invoice['invoice_no']}", fontsize=11)
    page.insert_text((54, 170), invoice["address"], fontsize=11)
    rows = ["DESCRIPTION                         QTY    UNIT PRICE (INR)"]
    rows.extend(
        f"{description:<34} {quantity:>4}    Rs. {price:,.2f}"
        for description, quantity, price in invoice["items"]
    )
    page.insert_textbox(
        pymupdf.Rect(54, 210, 558, 380),
        "\n".join(rows),
        fontsize=10,
        fontname="cour",
        lineheight=2.1,
    )
    pdf = document.tobytes()
    document.close()
    return pdf
