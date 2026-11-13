import unittest

from app.extraction import parse_invoice_text


class ParseInvoiceTextTests(unittest.TestCase):
    def test_extracts_indian_invoice_fields_and_rupee_item_prices(self) -> None:
        draft = parse_invoice_text(
            "Bharat Office Solutions Pvt Ltd\n"
            "Invoice No: BOS/2026-27/001\n"
            "GSTIN: 27AABCU9603R1ZM\n"
            "Address: Pune, Maharashtra 411005\n"
            "A4 copier paper, 75 GSM 10 Rs. 2,450.00\n"
        )

        self.assertEqual(draft.vendor_name, "Bharat Office Solutions Pvt Ltd")
        self.assertEqual(draft.invoice_no, "BOS/2026-27/001")
        self.assertEqual(draft.invoice_state, "Maharashtra")
        self.assertEqual(
            [item.model_dump() for item in draft.items],
            [
                {
                    "material_description": "A4 copier paper, 75 GSM",
                    "quantity": 10.0,
                    "price": 2450.0,
                }
            ],
        )

    def test_missing_fields_remain_empty_for_human_review(self) -> None:
        draft = parse_invoice_text("")

        self.assertIsNone(draft.vendor_name)
        self.assertIsNone(draft.invoice_no)
        self.assertIsNone(draft.invoice_state)
        self.assertEqual(draft.items, [])


if __name__ == "__main__":
    unittest.main()
