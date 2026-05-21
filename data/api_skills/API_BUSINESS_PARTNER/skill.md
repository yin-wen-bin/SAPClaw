# API_BUSINESS_PARTNER Skill

## Purpose

Use this API for business partner master data. It covers business partners, suppliers, customers, addresses, contact data, tax numbers, bank details, company-code views, purchasing-organization views, and sales-area views.

Keep `data/index/API_BUSINESS_PARTNER` as the schema ground truth. This skill provides business usage guidance only.

## When To Use

- The user asks for supplier, customer, or business partner master data.
- The user asks for names, addresses, email, phone, fax, bank data, tax numbers, roles, relationship data, supplier purchasing data, supplier company data, customer company data, or customer sales-area data.
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
- `A_AddressFaxNumber`: fax records for a business partner address.
- `A_BusinessPartnerBank`: bank-account data.
- `A_BusinessPartnerTaxNumber`: tax-number data.
- `A_SupplierCompany`: supplier company-code view.
- `A_SupplierPurchasingOrg`: supplier purchasing-organization view.
- `A_CustomerCompany`: customer company-code view.
- `A_CustomerSalesArea`: customer sales-area view.

## Business Semantics

- A business partner can have supplier and customer roles. Use the supplier entities for supplier-specific fields and customer entities for customer-specific fields.
- Supplier and customer IDs are identifiers. Preserve leading zeros and user-specified values exactly.
- `A_Supplier` contains supplier-specific names and block flags such as `SupplierName`, `SupplierFullName`, `PaymentIsBlockedForSupplier`, `PostingIsBlocked`, and `PurchasingIsBlocked`.
- Address, email, phone, and fax records are address-level data. If a user asks for contact details for a specific supplier/customer/business partner, expect a plan that starts from the business partner or supplier/customer and then reads address communication entities.
- If the user asks for a general email, phone, or fax list and does not ask for business partner enrichment, query the communication entity directly so the communication value fields remain in the final answer.
- Phrases such as "business partner email list", "business partner phone list", or "business partner fax list" identify the master-data domain. They do not by themselves require returning the `BusinessPartner` ID unless the user explicitly asks for business partner number/ID/details.
- Company-code and purchasing-organization data are role-specific extensions, not general business partner attributes.
- Supplier company-code payment terms are maintained on `A_SupplierCompany.PaymentTerms`, not on the general `A_Supplier` or `A_BusinessPartner` entity.
- For a generic "basic information", "profile", "details", "overview", "basic master data", `基本信息`, `详情`, `概况`, or `主数据` request, output fields should be business-facing. Prefer IDs, names, address, and contact fields. Do not return mainly account group, blocking, authorization, creation, or audit fields unless the user asks for those controls.

## Common Planning Patterns

### Supplier Master Data

- Query `A_Supplier` when the user provides a supplier ID or asks for supplier master details.
- For a supplier basic information/profile request, select `A_Supplier.Supplier`, `A_Supplier.SupplierName`, and `A_Supplier.SupplierFullName` first. Do not make `A_Supplier.SupplierAccountGroup`, `A_Supplier.PurchasingIsBlocked`, `A_Supplier.PostingIsBlocked`, `A_Supplier.PaymentIsBlockedForSupplier`, `A_Supplier.AuthorizationGroup`, `A_Supplier.CreationDate`, or `A_Supplier.CreatedByUser` the main output fields unless the user asks for account group, block/freeze status, authorization, or creation/audit information.
- For a broad supplier basic information/profile/detail/overview request that is not limited to name or status, use this multi-step profile lookup by default so address fields are returned with the supplier identity:
  - Step 1: query `A_Supplier` by `A_Supplier.Supplier`; select `A_Supplier.Supplier`, `A_Supplier.SupplierName`, and `A_Supplier.SupplierFullName`.
  - Step 2: query `A_BusinessPartnerAddress` with `A_BusinessPartnerAddress.BusinessPartner` bound from `A_Supplier.Supplier`; select `A_BusinessPartnerAddress.BusinessPartner`, `A_BusinessPartnerAddress.AddressID`, `A_BusinessPartnerAddress.FullName`, `A_BusinessPartnerAddress.StreetName`, `A_BusinessPartnerAddress.CityName`, `A_BusinessPartnerAddress.PostalCode`, `A_BusinessPartnerAddress.Country`, and `A_BusinessPartnerAddress.Person`.
  - Step 3 only when phone/email/fax is requested or contact details are explicitly expected: query `A_AddressPhoneNumber` by `A_AddressPhoneNumber.AddressID` and select `A_AddressPhoneNumber.AddressID`, `A_AddressPhoneNumber.Person`, `A_AddressPhoneNumber.PhoneNumber`, and `A_AddressPhoneNumber.InternationalPhoneNumber`; or query `A_AddressEmailAddress` by `A_AddressEmailAddress.AddressID` and select `A_AddressEmailAddress.AddressID`, `A_AddressEmailAddress.Person`, and `A_AddressEmailAddress.EmailAddress`.
- For supplier name plus freeze/block status, query `A_Supplier` directly and select `Supplier`, `SupplierName`, `SupplierFullName`, `PaymentIsBlockedForSupplier`, `PostingIsBlocked`, and `PurchasingIsBlocked`.
- Use `A_SupplierCompany` for supplier company-code data.
- For supplier company-code payment terms, query `A_SupplierCompany` and select `Supplier`, `CompanyCode`, `CompanyCodeName`, and `PaymentTerms`.
- Use `A_SupplierPurchasingOrg` for supplier purchasing-organization data.

### Business Partner Address And Contact

- Query `A_BusinessPartner` or `A_Supplier` to identify the business partner.
- Query `A_BusinessPartnerAddress` for address records.
- For supplier address lookups, binding `A_Supplier.Supplier` to `A_BusinessPartnerAddress.BusinessPartner` is valid. In this API, the supplier ID is the business partner key used by address records. Do not add a top-level `Supplier` filter on `A_BusinessPartnerAddress`; put the supplier filter on the `A_Supplier` step and bind the address step with `BusinessPartner`.
- Query `A_AddressEmailAddress` or `A_AddressPhoneNumber` when email or phone details are requested.
- Query `A_AddressFaxNumber` when fax details are requested.
- For general communication lists:
  - email list: query `A_AddressEmailAddress` directly and select `AddressID`, `Person`, `OrdinalNumber`, `EmailAddress`, and `IsDefaultEmailAddress`.
  - phone list: query `A_AddressPhoneNumber` directly and select `AddressID`, `Person`, `OrdinalNumber`, `PhoneNumber`, `InternationalPhoneNumber`, and `IsDefaultPhoneNumber`.
  - fax list: query `A_AddressFaxNumber` directly and select `AddressID`, `Person`, `OrdinalNumber`, `FaxNumber`, `InternationalFaxNumber`, and `IsDefaultFaxNumber`.

### Supplier Contact Enrichment From Purchase Orders

- If another API has resolved a supplier ID from a purchase order, use that supplier ID as the business partner key for supplier contact enrichment.
- Query `A_Supplier` with `Supplier` to return `SupplierName` and `SupplierFullName`.
- Query `A_BusinessPartnerAddress` with `BusinessPartner` equal to the supplier ID to return available supplier address/contact fields such as `AddressID`, `FullName`, `Person`, `CityName`, and `StreetName`.
- Only query `A_AddressEmailAddress` or `A_AddressPhoneNumber` when the user specifically asks for email or phone numbers, because some suppliers have address records without maintained email/phone rows.

### Customer Master Data

- Query `A_Customer` for customer master data.
- For a customer basic information/profile request, select `A_Customer.Customer`, `A_Customer.CustomerName`, `A_Customer.CustomerFullName`, and `A_Customer.BPCustomerFullName` first. Do not make `A_Customer.CustomerAccountGroup`, `A_Customer.BillingIsBlockedForCustomer`, `A_Customer.AuthorizationGroup`, `A_Customer.CreationDate`, or `A_Customer.CreatedByUser` the main output fields unless the user asks for account group, block status, authorization, or creation/audit information.
- Use `A_CustomerCompany` for company-code data and `A_CustomerSalesArea` for sales-area data.

## Pitfalls

- This API does not contain purchase order, invoice, stock, or material movement transaction records.
- Do not infer supplier purchasing activity from supplier master records.
- Do not answer "undelivered orders" or "open invoice orders" from business partner data.

## Needs Verification

- Complex partner-role, relationship, or contact-person questions may require checking which partner-function entity contains the exact requested role.
