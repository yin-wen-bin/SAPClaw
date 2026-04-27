# API_BUSINESS_PARTNER Skill

## Purpose

Use this API for business partner master data. It covers business partners, suppliers, customers, addresses, contact data, tax numbers, bank details, company-code views, purchasing-organization views, and sales-area views.

Keep `data/index/API_BUSINESS_PARTNER` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for supplier, customer, or business partner master data.
- The user asks for names, addresses, email, phone, bank data, tax numbers, roles, relationship data, supplier purchasing data, supplier company data, customer company data, or customer sales-area data.
- The user asks to identify or list suppliers or customers by master-data attributes.

## When Not To Use

- Do not use this API for purchase orders, purchase requisitions, supplier invoices, material documents, stock balances, product availability, or product master data.
- Do not use this API to answer transactional status questions such as open purchase orders, undelivered purchase orders, unpaid supplier invoices, or current inventory.

## Key Entities

- `A_BusinessPartner`: general business partner master data.
- `A_Supplier`: supplier master data.
- `A_Customer`: customer master data.
- `A_BusinessPartnerAddress`: business partner address records.
- `A_AddressEmailAddress`: email records for a business partner address.
- `A_AddressPhoneNumber`: phone records for a business partner address.
- `A_BusinessPartnerBank`: bank-account data.
- `A_BusinessPartnerTaxNumber`: tax-number data.
- `A_SupplierCompany`: supplier company-code view.
- `A_SupplierPurchasingOrg`: supplier purchasing-organization view.
- `A_CustomerCompany`: customer company-code view.
- `A_CustomerSalesArea`: customer sales-area view.

## Business Semantics

- A business partner can have supplier and customer roles. Use the supplier entities for supplier-specific fields and customer entities for customer-specific fields.
- Supplier and customer IDs are identifiers. Preserve leading zeros and user-specified values exactly.
- Address, email, and phone records are address-level data. If a user asks for contact details, expect a plan that starts from the business partner or supplier/customer and then reads address communication entities.
- Company-code and purchasing-organization data are role-specific extensions, not general business partner attributes.

## Common Planning Patterns

### Supplier Master Data

- Query `A_Supplier` when the user provides a supplier ID or asks for supplier master details.
- Use `A_SupplierCompany` for supplier company-code data.
- Use `A_SupplierPurchasingOrg` for supplier purchasing-organization data.

### Business Partner Address And Contact

- Query `A_BusinessPartner` or `A_Supplier` to identify the business partner.
- Query `A_BusinessPartnerAddress` for address records.
- Query `A_AddressEmailAddress` or `A_AddressPhoneNumber` when email or phone details are requested.

### Customer Master Data

- Query `A_Customer` for customer master data.
- Use `A_CustomerCompany` for company-code data and `A_CustomerSalesArea` for sales-area data.

## Pitfalls

- This API does not contain purchase order, invoice, stock, or material movement transaction records.
- Do not infer supplier purchasing activity from supplier master records.
- Do not answer "undelivered orders" or "open invoice orders" from business partner data.

## Needs Verification

- Complex partner-role, relationship, or contact-person questions may require checking which partner-function entity contains the exact requested role.
