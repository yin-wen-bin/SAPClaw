# API_SUPPLIERINVOICE_PROCESS_SRV Skill

## Purpose

Use this API for supplier invoice transaction data. It covers supplier invoice headers, tax data, withholding tax, invoice item account assignments, PO-referenced invoice items, material/GL/asset invoice items, selected purchasing documents, selected inbound delivery notes, and invoice actions.

Keep `data/index/API_SUPPLIERINVOICE_PROCESS_SRV` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for supplier invoices, invoice documents, invoice dates, fiscal year, company code, invoice status, tax, withholding tax, invoice items, invoice account assignments, or supplier invoice lines with purchase order reference.
- The user clarifies that "open invoice" means supplier invoices or unpaid bills, not purchase orders that are not finally invoiced.

## When Not To Use

- Do not use this API for purchase order item status, purchase order receipt status, current stock, material documents, purchase requisitions, or product master data.
- Do not use this API for "purchase orders not finally invoiced" when the intended object is a purchase order; use the purchase order API for that scenario.

## Key Entities

- `A_SupplierInvoice`: supplier invoice header data.
- `A_SuplrInvcItemPurOrdRef`: supplier invoice item data with purchase order reference.
- `A_SuplrInvcItemAcctAssgmt`: supplier invoice item account assignment data.
- `A_SupplierInvoiceTax`: supplier invoice tax data.
- `A_SuplrInvcHeaderWhldgTax`: withholding tax data.
- `A_SupplierInvoiceItemMaterial`: supplier invoice item data for material postings.
- `A_SupplierInvoiceItemGLAcct`: supplier invoice item data for G/L account postings.
- `A_SupplierInvoiceItemAsset`: supplier invoice item data for asset postings.
- `A_SuplrInvcSeldPurgDocument`: selected purchasing document data entered for supplier invoice.
- `A_SuplrInvoiceAdditionalData`: additional invoice data.
- `Post`: action to post an invoice; not supported by normal read-only query planning.
- `Cancel`: action to reverse an invoice; not supported by normal read-only query planning.
- `Release`: action to release an invoice; not supported by normal read-only query planning.

## Business Semantics

- Supplier invoices are invoice documents. They are different from purchase orders and goods receipts.
- "Open supplier invoices" or "unpaid bills" should route here when the user means invoice documents.
- "Purchase orders not finally invoiced" belongs to the purchase order API and usually uses purchase order item final-invoice status.
- PO-referenced invoice questions usually require item-level invoice entities that include purchase document references.
- Preserve supplier IDs, invoice numbers, fiscal years, company codes, purchase order numbers, material IDs, and dates exactly.

## Common Planning Patterns

### Supplier Invoice Header

- Query `A_SupplierInvoice` for header-level invoice questions such as invoice number, supplier, company code, fiscal year, posting date, document date, or invoice status when available.

### Payment Blocking

- For supplier invoice payment-block wording such as `付款冻结`, `被冻结付款`, `被付款冻结的发票`, `payment block`, or `blocked invoices`, query `A_SupplierInvoice`.
- Select `A_SupplierInvoice.FiscalYear`, `A_SupplierInvoice.SupplierInvoice`, `A_SupplierInvoice.CompanyCode`, `A_SupplierInvoice.DocumentDate`, `A_SupplierInvoice.PostingDate`, `A_SupplierInvoice.InvoicingParty`, `A_SupplierInvoice.DocumentCurrency`, `A_SupplierInvoice.InvoiceGrossAmount`, and `A_SupplierInvoice.PaymentBlockingReason`.
- Filter `A_SupplierInvoice.CompanyCode` and `A_SupplierInvoice.InvoicingParty` when provided, and use `A_SupplierInvoice.PaymentBlockingReason ne ''` when the user asks for blocked invoices without specifying a blocking reason.
- Do not ask whether the user means invoice header or accounting item when the request is specifically for supplier invoices blocked for payment; `A_SupplierInvoice.PaymentBlockingReason` is the header-level field to start with.

### Reversal Status

- For supplier invoice reversal, cancellation, reversed, reversal relationship, or "has this invoice been reversed" wording, query `A_SupplierInvoice`.
- When the user provides a supplier invoice number, filter `SupplierInvoice eq <invoice_number>`.
- Select `A_SupplierInvoice.SupplierInvoice`, `A_SupplierInvoice.FiscalYear`, `A_SupplierInvoice.CompanyCode`, `A_SupplierInvoice.DocumentDate`, `A_SupplierInvoice.PostingDate`, `A_SupplierInvoice.InvoicingParty`, `A_SupplierInvoice.IsReversal`, and `A_SupplierInvoice.IsReversed`.
- Do not ask for clarification when the user only asks whether the invoice is a reversal or has been reversed; answer from `IsReversal` and `IsReversed`.

### Invoice Items With Purchase Order Reference

- Query `A_SuplrInvcItemPurOrdRef` when the user asks for invoices tied to purchase orders or PO item references.

### Taxes And Withholding

- For supplier invoice tax code/tax amount wording such as `税码`, `税额`, `TaxCode`, or `TaxAmount`, query `A_SupplierInvoiceTax`; it is the dedicated supplier invoice tax entity.
- Select `A_SupplierInvoiceTax.FiscalYear`, `A_SupplierInvoiceTax.SupplierInvoice`, `A_SupplierInvoiceTax.SupplierInvoiceTaxCounter`, `A_SupplierInvoiceTax.TaxCode`, `A_SupplierInvoiceTax.DocumentCurrency`, `A_SupplierInvoiceTax.TaxAmount`, and `A_SupplierInvoiceTax.TaxBaseAmountInTransCrcy`.
- If the user provides a fiscal year, filter `A_SupplierInvoiceTax.FiscalYear eq <year>`. If the user provides a supplier invoice number, filter `A_SupplierInvoiceTax.SupplierInvoice eq <invoice_number>`.
- Do not ask whether the user means header-level or item-level tax when the request is simply for supplier invoice tax code and tax amount; start with `A_SupplierInvoiceTax`.
- Query `A_SupplierInvoiceTax` for invoice tax details.
- Query `A_SuplrInvcHeaderWhldgTax` for withholding tax details.

### Account Assignment

- Query `A_SuplrInvcItemAcctAssgmt` for invoice item account assignment data.

## Pitfalls

- Do not treat supplier invoice records as proof that a purchase order is fully received.
- Do not plan `Post`, `Cancel`, or `Release` actions for ordinary read-only queries.
- If the phrase "open invoice order" is ambiguous, clarify whether the user wants open purchase orders or open supplier invoices.

## Needs Verification

- Exact unpaid/open invoice semantics may require confirmation of invoice status fields and payment-clearing data available in the connected SAP system.
