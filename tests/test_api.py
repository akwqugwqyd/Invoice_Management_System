import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.storage import InvoiceStore


class ApprovalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        main.store = InvoiceStore(Path(self.temp_directory.name) / "invoices.db")
        main.source_records.clear()
        main.processing_jobs.clear()
        main.store.create(
            "test-invoice",
            "source-123",
            {"vendor_name": "OCR guess", "invoice_no": None, "invoice_state": None, "items": []},
            "OCR text",
        )
        self.client = TestClient(main.app)

    def tearDown(self) -> None:
        self.client.close()
        self.temp_directory.cleanup()

    def test_review_page_is_served(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invoice Management", response.text)
        self.assertIn('id="processing-card"', response.text)
        self.assertIn("Fetch invoices", response.text)
        self.assertIn("Review OCR", response.text)
        self.assertIn("Approve JSON", response.text)
        self.assertIn('id="send-result"', response.text)
        self.assertEqual(response.text.count('class="stepper-item'), 3)
        self.assertNotIn("DEMO", response.text)

        styles = self.client.get("/static/styles.css")
        self.assertEqual(styles.status_code, 200)
        self.assertIn(".processing-card", styles.text)

        script = self.client.get("/static/app.js")
        self.assertEqual(script.status_code, 200)
        self.assertIn("/api/jobs/", script.text)

    def test_synthetic_source_and_file_are_available(self) -> None:
        response = self.client.get("/sample-api/invoices")
        self.assertEqual(response.status_code, 200)
        invoices = response.json()["invoices"]
        self.assertEqual(len(invoices), 3)

        response = self.client.get("/sample-api/files/INV-IND-001.pdf")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        complex_invoice = self.client.get("/sample-api/files/INV-IND-003.pdf")
        self.assertEqual(complex_invoice.status_code, 200)
        self.assertTrue(complex_invoice.content.startswith(b"%PDF"))
        extracted = self.client.get("/api/source-invoices")
        self.assertEqual(
            [invoice["id"] for invoice in extracted.json()["invoices"]],
            ["INV-IND-001", "INV-IND-002", "INV-IND-003"],
        )

    def test_source_list_preview_and_background_ocr_job(self) -> None:
        response = self.client.get("/api/source-invoices")
        self.assertEqual(response.status_code, 200)
        invoices = response.json()["invoices"]
        self.assertEqual(
            [invoice["id"] for invoice in invoices],
            ["INV-IND-001", "INV-IND-002", "INV-IND-003"],
        )
        self.assertEqual(invoices[0]["status"], "available")
        self.assertEqual(invoices[0]["file_type"], "PDF")

        response = self.client.get("/api/source-invoices/INV-IND-001/preview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "application/pdf")

        response = self.client.post("/api/source-invoices/INV-IND-001/process")
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/jobs/{response.json()['job_id']}").json()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["progress"], 100)

        invoice = self.client.get(f"/api/invoices/{job['invoice_id']}").json()
        self.assertEqual(invoice["status"], "needs_review")
        self.assertEqual(invoice["draft"]["vendor_name"], "Bharat Office Solutions Pvt Ltd")
        self.assertEqual(invoice["draft"]["invoice_state"], "Maharashtra")
        self.assertTrue(invoice["draft"]["items"])

        response = self.client.post("/api/source-invoices/INV-IND-003/process")
        self.assertEqual(response.status_code, 202)
        job = self.client.get(f"/api/jobs/{response.json()['job_id']}").json()
        self.assertEqual(job["status"], "completed")
        invoice = self.client.get(f"/api/invoices/{job['invoice_id']}").json()
        self.assertEqual(invoice["draft"]["vendor_name"], "Aarav Industrial Supplies")
        self.assertEqual(invoice["draft"]["invoice_no"], "AIS/2026-27/113")
        self.assertEqual(invoice["draft"]["invoice_state"], "Gujarat")
        self.assertEqual(len(invoice["draft"]["items"]), 4)
        self.assertEqual(
            invoice["draft"]["items"][0],
            {
                "material_description": "Stainless steel fasteners, assorted M8-M12",
                "quantity": 4.5,
                "price": 1250.0,
            },
        )

    def test_fetch_synthetic_invoices_runs_ocr_and_creates_review_drafts(self) -> None:
        response = self.client.post("/api/fetch")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(len(result["created"]), 3, result["errors"])
        self.assertEqual(result["errors"], [])

        invoice_id = result["created"][0]["id"]
        invoice = self.client.get(f"/api/invoices/{invoice_id}").json()
        self.assertEqual(invoice["status"], "needs_review")
        self.assertIn("Invoice", invoice["raw_text"])
        self.assertEqual(invoice["draft"]["vendor_name"], "Bharat Office Solutions Pvt Ltd")
        self.assertEqual(invoice["draft"]["invoice_no"], "BOS/2026-27/001")
        self.assertEqual(invoice["draft"]["invoice_state"], "Maharashtra")
        self.assertEqual(
            invoice["draft"]["items"],
            [
                {
                    "material_description": "A4 copier paper, 75 GSM",
                    "quantity": 10.0,
                    "price": 2450.0,
                },
                {
                    "material_description": "Ball pen set, blue",
                    "quantity": 25.0,
                    "price": 120.0,
                },
            ],
        )

    def test_reset_clears_previous_result_and_allows_ocr_again(self) -> None:
        approved = self.client.post(
            "/api/invoices/test-invoice/approve",
            json={
                "draft": {
                    "vendor_name": "Approved vendor",
                    "invoice_no": "INV-1",
                    "invoice_state": "Maharashtra",
                    "items": [
                        {"material_description": "Paper", "quantity": 1, "price": 10}
                    ],
                }
            },
        )
        self.assertEqual(approved.status_code, 200)
        main.source_records["old-source"] = {
            "id": "old-source",
            "file_url": "https://example.com/old.pdf",
        }
        main.processing_jobs["old-job"] = {"id": "old-job", "status": "completed"}

        response = self.client.post("/api/reset")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "reset"})
        self.assertEqual(self.client.get("/api/invoices").json(), [])
        self.assertEqual(main.source_records, {})
        self.assertEqual(main.processing_jobs, {})

        sources = self.client.get("/api/source-invoices").json()["invoices"]
        self.assertTrue(sources)
        self.assertEqual(sources[0]["status"], "available")
        started = self.client.post(
            f"/api/source-invoices/{sources[0]['id']}/process"
        )
        self.assertEqual(started.status_code, 202)
        job = self.client.get(f"/api/jobs/{started.json()['job_id']}").json()
        self.assertEqual(job["status"], "completed")
        invoice = self.client.get(f"/api/invoices/{job['invoice_id']}").json()
        self.assertEqual(invoice["status"], "needs_review")

    def test_result_is_withheld_until_human_approval(self) -> None:
        response = self.client.get("/api/invoices/test-invoice/result")
        self.assertEqual(response.status_code, 409)

        approved_draft = {
            "vendor_name": "Corrected vendor",
            "invoice_no": "INV-1",
            "invoice_state": "CA",
            "items": [
                {"material_description": "Bolts", "quantity": 3, "price": 1.25}
            ],
        }
        response = self.client.post(
            "/api/invoices/test-invoice/approve",
            json={"draft": approved_draft},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], approved_draft)

        response = self.client.get("/api/invoices/test-invoice/result")
        self.assertEqual(response.json(), approved_draft)

    def test_invalid_reviewed_values_are_rejected(self) -> None:
        response = self.client.post(
            "/api/invoices/test-invoice/approve",
            json={
                "draft": {
                    "vendor_name": "Vendor",
                    "invoice_no": "INV-1",
                    "invoice_state": "CA",
                    "items": [
                        {"material_description": "Bolts", "quantity": -1, "price": 1.25}
                    ],
                }
            },
        )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
