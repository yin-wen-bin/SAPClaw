# API_SERVICE_ENTRY_SHEET_SRV Skill

## Purpose

Use this API for service entry sheet headers, service entry sheet items, and service entry sheet account assignments. For service entry sheet header approval status, select `A_ServiceEntrySheet.ApprovalStatus`; use `A_ServiceEntrySheet.SESWorkflowStatus` only for workflow status wording or when both approval and workflow status are requested.

Keep `data/index/API_SERVICE_ENTRY_SHEET_SRV` as the schema ground truth. This skill provides business usage guidance only. SAP $metadata is available in the local index; treat SAP 401/403/timeout responses as execution-time service or authorization issues, not schema absence.

## When To Use

- The user asks about this service enables a remote system to read, create and update service entry sheets from or in the sap s/4 hana system. it also provides service nodes to submit a service entry sheet for approval, withdraw a service entry sheet from approval or revoke approval of an already approved service entry sheet. or the business objects exposed by this service: Service Entry Sheet, Service Entry Sheet Item, Srvc Entr Sht Acct Assignment, Revoke Approval, Submit For Approval, Withdraw From Approval.
- The request is read-oriented and can be answered from entity sets and fields indexed under `data/index/API_SERVICE_ENTRY_SHEET_SRV`.
- Prefer this API when the user language clearly matches the service title, entity names, or documented field descriptions.

## When Not To Use

- Do not use this API for unrelated master data or transactions that belong to a more specific API already available in the catalog.
- Do not use this API for write, create, update, delete, release, cancel, or action execution in normal read-only query planning unless the user explicitly asks and the application mode allows it.
- Do not invent fields, entities, joins, or business conclusions beyond the indexed schema and this skill.

## Key Entities

- `A_ServiceEntrySheet`: Reads the header data from all service entry sheets.. Methods: GET, PATCH, POST.
- `A_ServiceEntrySheetItem`: Reads all service entry sheet items.. Methods: GET, PATCH.
- `A_SrvcEntrShtAcctAssignment`: Reads all account assignments of service entry sheets.. Methods: GET, PATCH.
- `RevokeApproval`: Revokes the approval of a service entry sheet.. Methods: POST. documentation-only; verify against metadata before execution.
- `SubmitForApproval`: Submits a service entry sheet for approval.. Methods: POST. documentation-only; verify against metadata before execution.
- `WithdrawFromApproval`: Withdraws a service entry sheet from the approval process.. Methods: POST. documentation-only; verify against metadata before execution.

## Business Semantics

- Primary business scope: This service enables a remote system to read, create and update service entry sheets from or in the SAP S/4 HANA system. It also provides service nodes to submit a service entry sheet for approval, withdraw a service entry sheet from approval or revoke approval of an already approved service entry sheet..
- Use the service description, entity descriptions, and field descriptions from `data/index/API_SERVICE_ENTRY_SHEET_SRV` to infer user intent.
- Preserve SAP document numbers, item numbers, partner numbers, material/product IDs, company codes, plants, fiscal years, dates, currencies, quantities, statuses, and type codes exactly as returned by SAP.
- When a user asks for a list, prefer the entity whose business level matches the requested object: header for document headers, item for line items, schedule for schedule lines, partner/address/text/pricing/account entities only when those details are explicitly requested.
- For boolean fields, use unquoted OData boolean literals `true` and `false`. For string indicator fields, preserve the string literal exactly.

## Common Planning Patterns

### Direct Entity Query

- Select the entity whose description most directly matches the requested business object.
- Apply user-provided identifiers, dates, statuses, organizational units, material/product IDs, customer/supplier IDs, and document numbers as filters when corresponding filterable fields exist.
- Keep `$select` focused on key fields plus fields needed to answer the question.
- For service entry sheet header approval status, select `A_ServiceEntrySheet.ApprovalStatus`.
- Select `A_ServiceEntrySheet.SESWorkflowStatus` only when the user asks for workflow status, workflow approval state, or when both approval status and workflow status are requested.
- For wording such as `account assignments for service entry sheets`, `service entry sheet account assignments`, or `service entry sheet account assignment records`, select only `A_SrvcEntrShtAcctAssignment.AccountAssignment`, `A_SrvcEntrShtAcctAssignment.ServiceEntrySheet`, `A_SrvcEntrShtAcctAssignment.ServiceEntrySheetItem`, `A_SrvcEntrShtAcctAssignment.AccountAssignmentUUID`, `A_SrvcEntrShtAcctAssignment.PurchasingOrganization`, `A_SrvcEntrShtAcctAssignment.PurchasingGroup`, `A_SrvcEntrShtAcctAssignment.Plant`, and `A_SrvcEntrShtAcctAssignment.BusinessArea`.

### Detail Query

- Use item/detail/text/pricing/account/partner/schedule entities only when the user asks for that detail level or when a relationship path in `lookup_paths.json` proves the navigation.
- For cross-entity questions, use indexed lookup paths instead of guessing joins.

### Runtime Availability

- SAP $metadata was available when this index was built. Use `data/index/API_SERVICE_ENTRY_SHEET_SRV` as the executable schema contract.
- If SAP returns 401, 403, timeout, or service unavailable during execution, report it as a runtime service/authentication issue.

## Pitfalls

- Do not confuse similarly named APIs. Check the selected API's service title and key entities before planning.
- Do not treat a detail entity as proof of a header-level business status unless the indexed fields explicitly support that status.
- Do not use action/function entities for read-only questions unless they are documented function imports and all required parameters are available.
- Do not answer from an empty or blank less-specific field when a more specific entity or field exists for the business concept.

## Needs Verification

- Verify entity and field availability against `data/index/API_SERVICE_ENTRY_SHEET_SRV` before execution.
- Verify SAP runtime connectivity and authorization if execution fails despite a schema-valid plan.
- For ambiguous terms that map to multiple entities or business levels, ask a concise clarification question instead of guessing.
