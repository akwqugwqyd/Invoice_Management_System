import tempfile
import unittest
from pathlib import Path

from app.storage import InvoiceStore


class InvoiceStoreTests(unittest.TestCase):
    def test_invoice_is_not_result_until_approved(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = InvoiceStore(Path(directory) / "invoices.db")
            draft = {"vendor_name": "Bharat Office Supply", "items": []}
            store.create("local-id", "source-id", draft, "Bharat Office Supply")

            self.assertEqual(store.get("local-id")["status"], "needs_review")
            self.assertTrue(store.decide("local-id", "approved", draft))
            self.assertEqual(store.get("local-id")["status"], "approved")

    def test_reviewed_invoice_cannot_be_changed_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = InvoiceStore(Path(directory) / "invoices.db")
            store.create("local-id", "source-id", {}, "")
            self.assertTrue(store.decide("local-id", "rejected"))
            self.assertFalse(store.decide("local-id", "approved", {}))


if __name__ == "__main__":
    unittest.main()
