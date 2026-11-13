# Project Requirements

## Project purpose

Build a local application that demonstrates how invoice documents can be converted into structured data with OCR, reviewed by a person, and returned as JSON. The assignment uses synthetic Indian invoices so the complete workflow can be demonstrated without a real invoice API or private business documents.

## Required invoice data

The approved JSON must include:

- `vendor_name` — supplier or vendor name
- `invoice_no` — invoice number
- `invoice_state` — vendor's Indian state
- `items` — a list of invoice line items, each with:
  - `material_description`
  - `quantity`
  - `price` — per-unit price in INR

An invoice may have more than one line item. `quantity` and `price` are numeric values.

Example:

```json
{
  "vendor_name": "Aarav Industrial Supplies",
  "invoice_no": "AIS/2026-27/113",
  "invoice_state": "Gujarat",
  "items": [
    {
      "material_description": "Stainless steel fasteners, assorted M8-M12",
      "quantity": 4.5,
      "price": 1250.0
    }
  ]
}
```

## Functional requirements

### Source invoices

1. Provide a fetch action that displays available invoices in the interface.
2. Include synthetic sample data in an Indian invoice format. A real source API is not required for this assignment.
3. Let the user select an invoice and preview its original document.
4. Do not start OCR until the user selects an invoice and requests processing.

### OCR and review

5. Use Tesseract OCR to recognize text from the selected PDF or supported image.
6. Show OCR progress while processing.
7. Extract the required invoice fields and retain the recognized text for review.
8. Present the extracted fields and line items in editable controls.
9. Allow the user to add or remove line items.
10. Treat OCR output as an unapproved draft; a person must review it before the result is approved.

### Approval and JSON

11. Validate the reviewed values before approval. A line item must have a description, quantity, and price; at least one complete line item is required.
12. Save the approved values and status locally.
13. Do not return the final JSON through the result endpoint until approval.
14. Display the approved JSON after approval and provide a Send JSON action that retrieves it from the application. Sending to a separate downstream system is outside the current assignment scope.

### Fresh run

15. Start with a clean application state on page load or refresh by clearing the local invoice and job state. This behavior is for the single-user assignment workflow.

## Quality and operational requirements

- Keep the three-stage workflow understandable: fetch, review OCR, approve JSON.
- Keep vendor state as a state name and prices as numeric INR unit prices.
- Support multiple items and decimal quantities.
- Keep sample documents local; do not require external credentials for the standard run.
- Report processing and validation errors to the user rather than presenting failed data as successful output.
- Enforce document size, type, and PDF page limits implemented by the application.
- Keep generated runtime data, environment files, and local Python environments out of source control.

## Acceptance criteria

The implementation meets the assignment requirements when:

1. Fetch displays the three synthetic Indian invoice records without immediately running OCR.
2. Selecting an invoice and clicking **Run OCR** shows progress and produces a draft with the required fields.
3. The user can correct extracted fields and line items before approval.
4. Invalid or incomplete line items cannot be approved.
5. Approval makes the JSON available; before approval, the result endpoint rejects the request.
6. **Send JSON** retrieves and displays only the approved result and confirms the action to the user.
7. Refreshing the page starts the configured fresh workflow.
8. Automated tests cover the source records, OCR extraction, validation, storage, and approval gate.

## Out of scope

- Login, roles, and multi-user isolation
- A production invoice provider or destination API
- Sending data to accounting, ERP, or payment systems
- Guaranteed OCR accuracy for arbitrary invoice layouts
- Production hosting, monitoring, and scaling

The current application is an assignment implementation and should be run locally. In particular, its refresh reset clears shared local invoice data, so it is not intended for concurrent users.
