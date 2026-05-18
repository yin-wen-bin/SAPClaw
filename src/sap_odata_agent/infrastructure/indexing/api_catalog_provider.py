from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from threading import RLock
from typing import Any

from sap_odata_agent.infrastructure.indexing.index_loader import LocalIndexLoader


class ApiCatalogProvider:
    """Build a compact API catalog for LLM routing.

    The catalog is intentionally small: it summarizes indexed APIs without
    exposing every field. The router uses this to pick the API before any
    API-specific metadata is loaded.
    """

    _INDEX_SIGNATURE_FILES = (
        "services.json",
        "entities.json",
        "fields.json",
        "entity_graph.json",
        "relations.json",
        "lookup_paths.json",
        "business_terms.json",
    )

    def __init__(self, index_root: str | Path = "data/index", default_service_name: str = "API_BUSINESS_PARTNER") -> None:
        self.index_root = Path(index_root)
        self.default_service_name = default_service_name
        self.loader = LocalIndexLoader(index_root=index_root)
        self._cache_lock = RLock()
        self._cached_signature: tuple[tuple[str, tuple[tuple[int, int], ...]], ...] | None = None
        self._cached_catalog: list[dict[str, Any]] | None = None

    def load(self) -> list[dict[str, Any]]:
        with self._cache_lock:
            signature = self._cache_signature()
            if self._cached_catalog is not None and self._cached_signature == signature:
                return deepcopy(self._cached_catalog)

            catalog: list[dict[str, Any]] = []
            for service_name, _ in signature:
                try:
                    snapshot = self.loader.load(service_name)
                except FileNotFoundError:
                    continue
                catalog.append(self._catalog_entry(snapshot))
            self._cached_signature = signature
            self._cached_catalog = deepcopy(catalog)
            return deepcopy(catalog)

    def _discover_service_names(self) -> list[str]:
        if not self.index_root.exists():
            return [self.default_service_name]
        names = [
            path.name
            for path in self.index_root.iterdir()
            if path.is_dir() and (path / "entities.json").exists()
        ]
        if self.default_service_name not in names:
            names.insert(0, self.default_service_name)
        return list(dict.fromkeys(names))

    def _cache_signature(self) -> tuple[tuple[str, tuple[tuple[int, int], ...]], ...]:
        signature: list[tuple[str, tuple[tuple[int, int], ...]]] = []
        for service_name in self._discover_service_names():
            service_dir = self.index_root / service_name
            file_signatures: list[tuple[int, int]] = []
            for filename in self._INDEX_SIGNATURE_FILES:
                path = service_dir / filename
                try:
                    stat = path.stat()
                except FileNotFoundError:
                    file_signatures.append((0, 0))
                    continue
                file_signatures.append((stat.st_mtime_ns, stat.st_size))
            signature.append((service_name, tuple(file_signatures)))
        return tuple(signature)

    @staticmethod
    def _catalog_entry(snapshot) -> dict[str, Any]:
        service = snapshot.services[0] if snapshot.services else {}
        service_kind = str(service.get("service_kind") or "ODATA")
        runtime_available = service.get("runtime_available", True)
        odata_runtime_available = service.get(
            "odata_runtime_available",
            runtime_available is not False and service_kind != "CDS_VIEW_ONLY",
        )
        ranked_entities = ApiCatalogProvider._rank_entities(snapshot)
        top_entities = [
            str(entity.get("entity_set", ""))
            for entity in ranked_entities[:16]
            if entity.get("entity_set")
        ]
        return {
            "service_name": snapshot.service_name,
            "service_kind": service_kind,
            "runtime_available": runtime_available,
            "odata_runtime_available": odata_runtime_available,
            "runtime_notes": str(service.get("runtime_notes") or ""),
            "short_description": ApiCatalogProvider._short_description(service),
            "primary_business_objects": ApiCatalogProvider._primary_business_objects(ranked_entities),
            "top_entities": top_entities,
            "top_filter_fields": ApiCatalogProvider._top_filter_fields(snapshot, top_entities),
            "top_answer_fields": ApiCatalogProvider._top_answer_fields(snapshot, top_entities),
        }

    @staticmethod
    def _short_description(service: dict[str, Any], max_length: int = 700) -> str:
        description = " ".join(str(service.get("description", "") or "").split())
        if len(description) <= max_length:
            return description
        return description[: max_length - 1].rstrip() + "."

    @staticmethod
    def _rank_entities(snapshot) -> list[dict[str, Any]]:
        entities = list(snapshot.entities or [])
        core_tokens = ApiCatalogProvider._service_core_tokens(snapshot.service_name)

        def score(entity: dict[str, Any]) -> tuple[float, str]:
            entity_set = str(entity.get("entity_set", "") or "")
            description = str(entity.get("description", "") or "")
            pinned_entity_scores = ApiCatalogProvider._pinned_entity_scores(snapshot.service_name)
            normalized = ApiCatalogProvider._normalize(ApiCatalogProvider._humanize_entity_set(entity_set))
            text = ApiCatalogProvider._normalize(f"{entity_set} {description}")
            lower_text = f"{entity_set} {description}".lower()
            value = 0.0
            value += pinned_entity_scores.get(entity_set, 0.0)
            if normalized in core_tokens:
                value += 90.0
            if any(normalized == f"{token}item" for token in core_tokens):
                value += 24.0
            if any(normalized == f"{token}scheduleline" for token in core_tokens):
                value += 16.0
            if any(token and normalized.startswith(token) for token in core_tokens):
                value += 30.0
            if any(token and token in normalized for token in core_tokens):
                value += 40.0
            if any(token and token in text for token in core_tokens):
                value += 12.0
            if entity.get("runtime_available") is False:
                value -= 12.0
            if entity_set.startswith("Get") or entity_set in {"Cancel", "CancelItem"}:
                value -= 10.0
            if any(term in lower_text for term in ("note", "text", "pdf", "binary")):
                value -= 18.0
            if not entity.get("key_fields"):
                value -= 2.0
            priority_terms = {
                "header": 9.0,
                "item": 7.0,
                "schedule": 6.0,
                "account": 5.0,
                "pricing": 4.0,
                "component": 3.0,
            }
            for term, weight in priority_terms.items():
                if term in lower_text:
                    value += weight
            return (-value, entity_set)

        return sorted(entities, key=score)

    @staticmethod
    def _primary_business_objects(entities: list[dict[str, Any]], max_count: int = 10) -> list[str]:
        objects: list[str] = []
        seen: set[str] = set()
        for entity in entities:
            entity_set = str(entity.get("entity_set", "") or "")
            if not entity_set:
                continue
            label = ApiCatalogProvider._humanize_entity_set(entity_set)
            if not label or label in seen:
                continue
            seen.add(label)
            objects.append(label)
            if len(objects) >= max_count:
                break
        return objects

    @staticmethod
    def _top_filter_fields(snapshot, top_entities: list[str], max_count: int = 18) -> list[str]:
        top_entity_rank = {entity_set: index for index, entity_set in enumerate(top_entities)}
        service_tokens = set(ApiCatalogProvider._service_core_tokens(snapshot.service_name))
        priority_tokens = {
            "purchaseorder": 35.0,
            "purchasingdocument": 32.0,
            "supplier": 30.0,
            "customer": 28.0,
            "businesspartner": 28.0,
            "material": 30.0,
            "product": 30.0,
            "plant": 24.0,
            "storagelocation": 20.0,
            "companycode": 22.0,
            "chartofaccounts": 34.0,
            "countrychartofaccounts": 24.0,
            "salesorder": 38.0,
            "orderid": 38.0,
            "orderitem": 28.0,
            "deliverydocument": 38.0,
            "deliverydocumentitem": 30.0,
            "deliverystatus": 34.0,
            "overalldeliverystatus": 30.0,
            "overalltotaldeliverystatus": 34.0,
            "referencesddocument": 36.0,
            "referencesddocumentitem": 30.0,
            "shiptoparty": 24.0,
            "soldtoparty": 24.0,
            "shippingpoint": 22.0,
            "creationdate": 18.0,
            "deliverydate": 28.0,
            "schedulelinedeliverydate": 30.0,
            "iscompletelydelivered": 30.0,
            "goodsreceiptisexpected": 24.0,
            "purchasingprocessingstatus": 22.0,
            "purchasingdocumentdeletioncode": 18.0,
            "purchaseorderitem": 24.0,
            "suppliermaterialnumber": 28.0,
            "materialgroup": 20.0,
            "batch": 18.0,
            "fiscalyear": 18.0,
            "postingdate": 18.0,
            "documentdate": 18.0,
            "isfinallyinvoiced": 34.0,
        }

        ranked: list[tuple[float, str]] = []
        seen: set[str] = set()
        available: set[str] = set()
        for field in snapshot.fields or []:
            if field.get("filterable") is False:
                continue
            entity_set = str(field.get("entity_set") or "")
            field_name = str(field.get("field_name") or "")
            if not entity_set or not field_name:
                continue
            qualified = f"{entity_set}.{field_name}"
            available.add(qualified)
            if qualified in seen:
                continue
            seen.add(qualified)

            normalized_field = ApiCatalogProvider._normalize(field_name)
            label = ApiCatalogProvider._normalize(str(field.get("label") or ""))
            aliases = ApiCatalogProvider._normalize(" ".join(str(item) for item in field.get("business_aliases", []) or []))
            description = ApiCatalogProvider._normalize(str(field.get("description") or ""))
            haystack = f"{normalized_field} {label} {aliases} {description}"

            score = 0.0
            if entity_set in top_entity_rank:
                score += max(0.0, 18.0 - top_entity_rank[entity_set])
            if field.get("is_key"):
                score += 8.0
            if field.get("runtime_available") is False:
                score -= 20.0
            if field.get("selectable") is False:
                score -= 4.0
            for token, weight in priority_tokens.items():
                if token == normalized_field:
                    score += weight * 2.5
                elif token in haystack:
                    score += weight * 0.55
            for token in service_tokens:
                if token and token in haystack:
                    score += 7.0
            if any(term in normalized_field for term in ("note", "text", "longtext", "description")):
                score -= 8.0
            ranked.append((-score, qualified))

        ranked.sort()
        pinned = [
            field
            for field in ApiCatalogProvider._pinned_filter_fields(snapshot.service_name)
            if field in available
        ]
        result = list(dict.fromkeys(pinned))
        for _, qualified in ranked:
            if qualified in result:
                continue
            result.append(qualified)
            if len(result) >= max_count:
                break
        return result[:max_count]

    @staticmethod
    def _top_answer_fields(snapshot, top_entities: list[str], max_count: int = 24) -> list[str]:
        top_entity_rank = {entity_set: index for index, entity_set in enumerate(top_entities)}
        service_tokens = set(ApiCatalogProvider._service_core_tokens(snapshot.service_name))
        priority_tokens = {
            "id": 24.0,
            "name": 36.0,
            "description": 28.0,
            "text": 24.0,
            "status": 26.0,
            "amount": 26.0,
            "currency": 20.0,
            "quantity": 22.0,
            "unit": 16.0,
            "date": 20.0,
            "time": 12.0,
            "companycode": 18.0,
            "companycodename": 44.0,
            "chartofaccounts": 46.0,
            "countrychartofaccounts": 34.0,
            "salesorder": 34.0,
            "orderid": 34.0,
            "orderitem": 24.0,
            "deliverydocument": 44.0,
            "deliverydocumentitem": 36.0,
            "deliverydate": 28.0,
            "referencesddocument": 32.0,
            "referencesddocumentitem": 24.0,
            "shiptoparty": 28.0,
            "soldtoparty": 28.0,
            "shippingpoint": 24.0,
            "overallgoodsmovementstatus": 24.0,
            "overallsdprocessstatus": 24.0,
            "glaccount": 22.0,
            "glaccountname": 46.0,
            "costcenter": 20.0,
            "costcentername": 42.0,
            "profitcenter": 20.0,
            "profitcentername": 42.0,
            "controllingarea": 18.0,
            "controllingareaname": 40.0,
            "ledger": 18.0,
            "ledgername": 36.0,
            "material": 22.0,
            "product": 22.0,
            "plant": 18.0,
            "supplier": 20.0,
            "customer": 20.0,
        }

        ranked: list[tuple[float, str]] = []
        seen: set[str] = set()
        suppressed = ApiCatalogProvider._suppressed_answer_fields(snapshot.service_name)
        for field in snapshot.fields or []:
            if field.get("selectable") is False:
                continue
            entity_set = str(field.get("entity_set") or "")
            field_name = str(field.get("field_name") or "")
            if not entity_set or not field_name:
                continue
            qualified = f"{entity_set}.{field_name}"
            if qualified in suppressed:
                continue
            if qualified in seen:
                continue
            seen.add(qualified)

            normalized_field = ApiCatalogProvider._normalize(field_name)
            label = ApiCatalogProvider._normalize(str(field.get("label") or ""))
            aliases = ApiCatalogProvider._normalize(" ".join(str(item) for item in field.get("business_aliases", []) or []))
            description = ApiCatalogProvider._normalize(str(field.get("description") or ""))
            haystack = f"{normalized_field} {label} {aliases} {description}"

            score = 0.0
            if entity_set in top_entity_rank:
                score += max(0.0, 22.0 - top_entity_rank[entity_set])
            if field.get("is_key"):
                score += 10.0
            if field.get("runtime_available") is False:
                score -= 20.0
            if field.get("filterable") is False:
                score -= 1.0
            for token, weight in priority_tokens.items():
                if token == normalized_field:
                    score += weight * 2.4
                elif token in normalized_field:
                    score += weight * 1.0
                elif token in haystack:
                    score += weight * 0.35
            for token in service_tokens:
                if token and token in haystack:
                    score += 6.0
            if any(term in normalized_field for term in ("metadata", "uuid", "etag")):
                score -= 10.0
            ranked.append((-score, qualified))

        ranked.sort()
        pinned = [
            field
            for field in ApiCatalogProvider._pinned_answer_fields(snapshot.service_name)
            if field in seen and field not in suppressed
        ]
        result = list(dict.fromkeys(pinned))
        for _, qualified in ranked:
            if qualified in result:
                continue
            result.append(qualified)
            if len(result) >= max_count:
                break
        return result[:max_count]

    @staticmethod
    def _suppressed_answer_fields(service_name: str) -> set[str]:
        if service_name == "API_GLACCOUNTLINEITEM":
            return {"GLAccountLineItem.ID"}
        if service_name == "C_TRIALBALANCE_CDS":
            return {"C_TRIALBALANCEResults.ID"}
        return set()

    @staticmethod
    def _pinned_filter_fields(service_name: str) -> list[str]:
        if service_name == "API_BUSINESS_PARTNER":
            return [
                "A_BusinessPartner.BusinessPartner",
                "A_BusinessPartner.Supplier",
                "A_BusinessPartner.Customer",
                "A_Supplier.Supplier",
                "A_Supplier.SupplierName",
                "A_Supplier.SupplierFullName",
                "A_Supplier.PaymentIsBlockedForSupplier",
                "A_Supplier.PostingIsBlocked",
                "A_Supplier.PurchasingIsBlocked",
                "A_SupplierCompany.Supplier",
                "A_SupplierCompany.CompanyCode",
                "A_SupplierCompany.PaymentTerms",
                "A_AddressEmailAddress.EmailAddress",
                "A_AddressPhoneNumber.PhoneNumber",
                "A_AddressPhoneNumber.InternationalPhoneNumber",
                "A_AddressFaxNumber.FaxNumber",
                "A_AddressFaxNumber.InternationalFaxNumber",
            ]
        if service_name == "API_PRODUCT_SRV":
            return [
                "A_Product.Product",
                "A_Product.ProductType",
                "A_Product.BaseUnit",
                "A_Product.CrossPlantStatus",
                "A_Product.IsMarkedForDeletion",
                "A_ProductDescription.Product",
                "A_ProductDescription.Language",
                "A_ProductDescription.ProductDescription",
                "A_ProductPlant.Product",
                "A_ProductPlant.Plant",
                "A_ProductUnitsOfMeasure.Product",
                "A_ProductUnitsOfMeasure.AlternativeUnit",
            ]
        if service_name == "API_PURCHASEORDER_PROCESS_SRV":
            return [
                "A_PurchaseOrderItem.IsFinallyInvoiced",
                "A_PurchaseOrderItem.Material",
                "A_PurchaseOrderScheduleLine.ScheduleLineDeliveryDate",
                "A_PurchaseOrder.Supplier",
            ]
        if service_name == "API_SUPPLIERINVOICE_PROCESS_SRV":
            return [
                "A_SupplierInvoice.SupplierInvoice",
                "A_SupplierInvoice.FiscalYear",
                "A_SupplierInvoice.CompanyCode",
                "A_SupplierInvoice.InvoicingParty",
                "A_SupplierInvoice.PaymentBlockingReason",
                "A_SupplierInvoice.IsReversal",
                "A_SupplierInvoice.IsReversed",
                "A_SupplierInvoiceTax.SupplierInvoice",
                "A_SupplierInvoiceTax.FiscalYear",
                "A_SupplierInvoiceTax.TaxCode",
                "A_SupplierInvoiceTax.DocumentCurrency",
            ]
        if service_name == "API_INFORECORD_PROCESS_SRV":
            return [
                "A_PurchasingInfoRecord.PurchasingInfoRecord",
                "A_PurchasingInfoRecord.Supplier",
                "A_PurchasingInfoRecord.Material",
                "A_PurchasingInfoRecord.MaterialGroup",
                "A_PurInfoRecdPrcgCndn.ConditionRecord",
                "A_PurInfoRecdPrcgCndn.ConditionType",
                "A_PurInfoRecdPrcgCndn.ConditionRateAmount",
                "A_PurInfoRecdPrcgCndn.ConditionCurrency",
                "A_PurInfoRecdPrcgCndn.ConditionRateValue",
                "A_PurInfoRecdPrcgCndn.ConditionRateValueUnit",
                "A_PurInfoRecdPrcgCndn.ConditionQuantity",
                "A_PurInfoRecdPrcgCndn.ConditionQuantityUnit",
                "A_PurInfoRecdPrcgCndnValidity.ConditionRecord",
                "A_PurInfoRecdPrcgCndnValidity.Material",
                "A_PurInfoRecdPrcgCndnValidity.Supplier",
                "A_PurInfoRecdPrcgCndnValidity.PurchasingInfoRecord",
            ]
        if service_name == "API_MATERIAL_STOCK_SRV":
            return [
                "A_MaterialStock.Material",
                "A_MaterialStock.MaterialBaseUnit",
                "A_MatlStkInAcctMod.Material",
                "A_MatlStkInAcctMod.Plant",
                "A_MatlStkInAcctMod.StorageLocation",
                "A_MatlStkInAcctMod.InventoryStockType",
                "A_MatlStkInAcctMod.MatlWrhsStkQtyInMatlBaseUnit",
                "A_MaterialSerialNumber.Material",
                "A_MaterialSerialNumber.SerialNumber",
            ]
        if service_name == "API_MATERIAL_DOCUMENT_SRV":
            return [
                "A_MaterialDocumentItem.ManufacturingOrder",
                "A_MaterialDocumentItem.MaterialDocument",
                "A_MaterialDocumentItem.MaterialDocumentYear",
                "A_MaterialDocumentItem.MaterialDocumentItem",
                "A_MaterialDocumentItem.Material",
                "A_MaterialDocumentItem.Plant",
                "A_MaterialDocumentItem.PurchaseOrder",
                "A_MaterialDocumentItem.PurchaseOrderItem",
            ]
        if service_name == "API_COMPANYCODE_SRV":
            return [
                "A_CompanyCode.CompanyCode",
                "A_CompanyCode.ChartOfAccounts",
                "A_CompanyCode.CountryChartOfAccounts",
            ]
        if service_name == "API_GLACCOUNTINCHARTOFACCOUNTS_SRV":
            return [
                "A_GLAccountInChartOfAccounts.ChartOfAccounts",
                "A_GLAccountInChartOfAccounts.GLAccount",
                "A_GLAccountInChartOfAccounts.IsProfitLossAccount",
                "A_GLAccountInChartOfAccounts.IsBalanceSheetAccount",
                "A_GLAccountInChartOfAccounts.ProfitLossAccountType",
                "A_GLAccountInChartOfAccounts.GLAccountType",
                "A_GLAccountInChartOfAccounts.SampleGLAccount",
                "A_GLAccountInChartOfAccounts.AccountIsBlockedForPosting",
                "A_GLAccountText.ChartOfAccounts",
                "A_GLAccountText.GLAccount",
                "A_GLAccountText.Language",
            ]
        if service_name == "API_GLACCOUNTLINEITEM":
            return [
                "GLAccountLineItem.CompanyCode",
                "GLAccountLineItem.GLAccount",
                "GLAccountLineItem.PostingDate",
                "GLAccountLineItem.ClearingDate",
                "GLAccountLineItem.Supplier",
                "GLAccountLineItem.Customer",
                "GLAccountLineItem.SpecialGLCode",
                "GLAccountLineItem.ProfitCenter",
                "GLAccountLineItem.SalesOrganization",
                "GLAccountLineItem.CustomerGroup",
                "GLAccountLineItem.ReferenceDocument",
                "GLAccountLineItem.AccountingDocument",
                "GLAccountLineItem.AccountingDocumentItem",
                "GLAccountLineItem.Ledger",
                "GLAccountLineItem.FiscalYear",
            ]
        if service_name == "API_OPLACCTGDOCITEMCUBE_SRV":
            return [
                "A_OperationalAcctgDocItemCube.CompanyCode",
                "A_OperationalAcctgDocItemCube.FiscalYear",
                "A_OperationalAcctgDocItemCube.Supplier",
                "A_OperationalAcctgDocItemCube.Customer",
                "A_OperationalAcctgDocItemCube.ClearingDate",
                "A_OperationalAcctgDocItemCube.IsCleared",
                "A_OperationalAcctgDocItemCube.NetDueDate",
                "A_OperationalAcctgDocItemCube.DueCalculationBaseDate",
                "A_OperationalAcctgDocItemCube.PaymentBlockingReason",
                "A_OperationalAcctgDocItemCube.SpecialGLCode",
                "A_OperationalAcctgDocItemCube.AccountingDocumentType",
                "A_OperationalAcctgDocItemCube.AccountingDocCreatedByUser",
                "A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency",
                "A_OperationalAcctgDocItemCube.GLAccount",
                "A_OperationalAcctgDocItemCube.PostingDate",
            ]
        if service_name == "C_TRIALBALANCE_CDS":
            return [
                "C_TRIALBALANCEResults.Ledger",
                "C_TRIALBALANCEResults.CompanyCode",
                "C_TRIALBALANCEResults.FiscalYear",
                "C_TRIALBALANCEResults.FiscalPeriod",
                "C_TRIALBALANCEResults.GLAccount",
                "C_TRIALBALANCEResults.ProfitCenter",
                "C_TRIALBALANCEResults.Segment",
                "C_TRIALBALANCEResults.IsBalanceSheetAccount",
            ]
        if service_name == "API_JOURNALENTRYITEMBASIC_SRV":
            return [
                "A_JournalEntryItemBasic.CompanyCode",
                "A_JournalEntryItemBasic.ID",
                "A_JournalEntryItemBasic.FunctionalArea",
                "A_JournalEntryItemBasic.CostCenter",
                "A_JournalEntryItemBasic.ProfitCenter",
                "A_JournalEntryItemBasic.GLAccount",
                "A_JournalEntryItemBasic.Ledger",
                "A_JournalEntryItemBasic.Plant",
            ]
        if service_name == "API_SALES_ORDER_SRV":
            return [
                "A_SalesOrder.SalesOrder",
                "A_SalesOrderItem.Material",
                "A_SalesOrderItem.DeliveryStatus",
                "A_SalesOrder.OverallTotalDeliveryStatus",
                "A_SalesOrderItem.SalesOrder",
                "A_SalesOrder.PurchaseOrderByCustomer",
                "A_SalesOrder.SoldToParty",
                "A_SalesOrder.OverallDeliveryStatus",
            ]
        if service_name == "API_OUTBOUND_DELIVERY_SRV":
            return [
                "A_OutbDeliveryItem.ReferenceSDDocument",
                "A_OutbDeliveryItem.ReferenceSDDocumentItem",
                "A_OutbDeliveryHeader.SoldToParty",
                "A_OutbDeliveryHeader.ShipToParty",
                "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
                "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus",
                "A_OutbDeliveryItem.GoodsMovementStatus",
                "A_OutbDeliveryItem.DeliveryRelatedBillingStatus",
                "A_OutbDeliveryHeader.OrderID",
                "A_OutbDeliveryHeader.DeliveryDocument",
                "A_OutbDeliveryHeader.ActualGoodsMovementDate",
                "A_OutbDeliveryHeader.DeliveryDate",
                "A_OutbDeliveryItem.OrderID",
                "A_OutbDeliveryItem.DeliveryDocument",
                "A_OutbDeliveryItem.DeliveryDocumentItem",
            ]
        if service_name == "API_PRODUCTION_ORDER_2_SRV":
            return [
                "A_ProductionOrderOperation_2.ProductionPlant",
                "A_ProductionOrderOperation_2.WorkCenter",
                "A_ProductionOrderOperation_2.ManufacturingOrder",
                "A_ProductionOrderOperation_2.ManufacturingOrderOperation",
                "A_ProductionOrder_2.ProductionPlant",
                "A_ProductionOrder_2.ManufacturingOrder",
                "A_ProductionOrder_2.Material",
            ]
        if service_name == "I_ProductionVersion":
            return [
                "I_ProductionVersion.Material",
                "I_ProductionVersion.Plant",
                "I_ProductionVersion.ProductionVersion",
                "I_ProductionVersion.ValidityStartDate",
                "I_ProductionVersion.ValidityEndDate",
                "I_ProductionVersion.MaterialMinLotSizeQuantity",
                "I_ProductionVersion.MaterialMaxLotSizeQuantity",
                "I_ProductionVersion.ProductionVersionStatus",
                "I_ProductionVersion.ProductionVersionIsLocked",
                "I_ProductionVersion.BillOfMaterialVariantUsage",
                "I_ProductionVersion.BillOfMaterialVariant",
                "I_ProductionVersion.BillOfOperationsType",
                "I_ProductionVersion.BillOfOperationsGroup",
                "I_ProductionVersion.BillOfOperationsVariant",
                "I_ProductionVersion.ProductionLine",
                "I_ProductionVersion.ProductionSupplyArea",
            ]
        return []

    @staticmethod
    def _pinned_answer_fields(service_name: str) -> list[str]:
        if service_name == "API_COMPANYCODE_SRV":
            return [
                "A_CompanyCode.CompanyCode",
                "A_CompanyCode.CompanyCodeName",
                "A_CompanyCode.ChartOfAccounts",
                "A_CompanyCode.CountryChartOfAccounts",
            ]
        if service_name == "API_GLACCOUNTINCHARTOFACCOUNTS_SRV":
            return [
                "A_GLAccountInChartOfAccounts.ChartOfAccounts",
                "A_GLAccountInChartOfAccounts.GLAccount",
                "A_GLAccountInChartOfAccounts.GLAccountGroup",
                "A_GLAccountInChartOfAccounts.GLAccountType",
                "A_GLAccountInChartOfAccounts.IsProfitLossAccount",
                "A_GLAccountInChartOfAccounts.IsBalanceSheetAccount",
                "A_GLAccountInChartOfAccounts.ProfitLossAccountType",
                "A_GLAccountInChartOfAccounts.SampleGLAccount",
                "A_GLAccountText.GLAccountName",
                "A_GLAccountText.GLAccountLongName",
            ]
        if service_name == "API_JOURNALENTRYITEMBASIC_SRV":
            return [
                "A_JournalEntryItemBasic.ID",
                "A_JournalEntryItemBasic.CompanyCode",
                "A_JournalEntryItemBasic.CompanyCodeName",
                "A_JournalEntryItemBasic.FunctionalArea",
                "A_JournalEntryItemBasic.FunctionalAreaName",
                "A_JournalEntryItemBasic.CostCenter",
                "A_JournalEntryItemBasic.CostCenterName",
                "A_JournalEntryItemBasic.ProfitCenter",
                "A_JournalEntryItemBasic.ProfitCenterName",
                "A_JournalEntryItemBasic.GLAccount",
                "A_JournalEntryItemBasic.GLAccountName",
                "A_JournalEntryItemBasic.AmountInCompanyCodeCurrency",
            ]
        if service_name == "API_GLACCOUNTLINEITEM":
            return [
                "GLAccountLineItem.CompanyCode",
                "GLAccountLineItem.FiscalYear",
                "GLAccountLineItem.AccountingDocument",
                "GLAccountLineItem.AccountingDocumentItem",
                "GLAccountLineItem.Ledger",
                "GLAccountLineItem.GLAccount",
                "GLAccountLineItem.Supplier",
                "GLAccountLineItem.Customer",
                "GLAccountLineItem.ReferenceDocument",
                "GLAccountLineItem.CompanyCodeCurrency",
                "GLAccountLineItem.PostingDate",
                "GLAccountLineItem.ClearingDate",
                "GLAccountLineItem.ClearingAccountingDocument",
                "GLAccountLineItem.SpecialGLCode",
                "GLAccountLineItem.ProfitCenter",
                "GLAccountLineItem.SalesOrganization",
                "GLAccountLineItem.CustomerGroup",
                "GLAccountLineItem.AmountInCompanyCodeCurrency",
            ]
        if service_name == "API_OPLACCTGDOCITEMCUBE_SRV":
            return [
                "A_OperationalAcctgDocItemCube.CompanyCode",
                "A_OperationalAcctgDocItemCube.FiscalYear",
                "A_OperationalAcctgDocItemCube.AccountingDocument",
                "A_OperationalAcctgDocItemCube.AccountingDocumentItem",
                "A_OperationalAcctgDocItemCube.Supplier",
                "A_OperationalAcctgDocItemCube.SupplierName",
                "A_OperationalAcctgDocItemCube.Customer",
                "A_OperationalAcctgDocItemCube.CustomerName",
                "A_OperationalAcctgDocItemCube.GLAccount",
                "A_OperationalAcctgDocItemCube.PostingDate",
                "A_OperationalAcctgDocItemCube.ClearingDate",
                "A_OperationalAcctgDocItemCube.IsCleared",
                "A_OperationalAcctgDocItemCube.NetDueDate",
                "A_OperationalAcctgDocItemCube.DueCalculationBaseDate",
                "A_OperationalAcctgDocItemCube.PaymentBlockingReason",
                "A_OperationalAcctgDocItemCube.SpecialGLCode",
                "A_OperationalAcctgDocItemCube.ProfitCenter",
                "A_OperationalAcctgDocItemCube.AccountingDocumentType",
                "A_OperationalAcctgDocItemCube.AccountingDocCreatedByUser",
                "A_OperationalAcctgDocItemCube.AmountInCompanyCodeCurrency",
            ]
        if service_name == "API_SUPPLIERINVOICE_PROCESS_SRV":
            return [
                "A_SupplierInvoice.SupplierInvoice",
                "A_SupplierInvoice.FiscalYear",
                "A_SupplierInvoice.CompanyCode",
                "A_SupplierInvoice.DocumentDate",
                "A_SupplierInvoice.PostingDate",
                "A_SupplierInvoice.InvoicingParty",
                "A_SupplierInvoice.InvoiceGrossAmount",
                "A_SupplierInvoice.DocumentCurrency",
                "A_SupplierInvoice.PaymentBlockingReason",
                "A_SupplierInvoice.IsReversal",
                "A_SupplierInvoice.IsReversed",
                "A_SupplierInvoiceTax.SupplierInvoice",
                "A_SupplierInvoiceTax.FiscalYear",
                "A_SupplierInvoiceTax.SupplierInvoiceTaxCounter",
                "A_SupplierInvoiceTax.TaxCode",
                "A_SupplierInvoiceTax.TaxAmount",
                "A_SupplierInvoiceTax.TaxBaseAmountInTransCrcy",
                "A_SupplierInvoiceTax.DocumentCurrency",
            ]
        if service_name == "C_TRIALBALANCE_CDS":
            return [
                "C_TRIALBALANCEResults.Ledger",
                "C_TRIALBALANCEResults.CompanyCode",
                "C_TRIALBALANCEResults.FiscalYear",
                "C_TRIALBALANCEResults.FiscalPeriod",
                "C_TRIALBALANCEResults.GLAccount",
                "C_TRIALBALANCEResults.EndingBalanceAmtInCoCodeCrcy",
                "C_TRIALBALANCEResults.ProfitCenter",
                "C_TRIALBALANCEResults.ProfitCenterName",
                "C_TRIALBALANCEResults.Segment",
                "C_TRIALBALANCEResults.SegmentName",
                "C_TRIALBALANCEResults.IsBalanceSheetAccount",
                "C_TRIALBALANCEResults.StartingBalanceAmtInCoCodeCrcy",
                "C_TRIALBALANCEResults.DebitAmountInCoCodeCrcy",
                "C_TRIALBALANCEResults.CreditAmountInCoCodeCrcy",
            ]
        if service_name == "API_SALES_ORDER_SRV":
            return [
                "A_SalesOrder.SalesOrder",
                "A_SalesOrderItem.SalesOrder",
                "A_SalesOrderItem.SalesOrderItem",
                "A_SalesOrderItem.Material",
                "A_SalesOrderItem.DeliveryStatus",
                "A_SalesOrderItem.RequestedQuantity",
                "A_SalesOrder.SalesOrderType",
                "A_SalesOrder.SalesOrganization",
                "A_SalesOrder.SoldToParty",
                "A_SalesOrder.OverallDeliveryStatus",
                "A_SalesOrder.OverallTotalDeliveryStatus",
            ]
        if service_name == "API_OUTBOUND_DELIVERY_SRV":
            return [
                "A_OutbDeliveryHeader.DeliveryDocument",
                "A_OutbDeliveryHeader.ActualGoodsMovementDate",
                "A_OutbDeliveryHeader.DeliveryDate",
                "A_OutbDeliveryHeader.SoldToParty",
                "A_OutbDeliveryHeader.ShipToParty",
                "A_OutbDeliveryHeader.OverallGoodsMovementStatus",
                "A_OutbDeliveryHeader.OverallDelivReltdBillgStatus",
                "A_OutbDeliveryItem.DeliveryDocument",
                "A_OutbDeliveryItem.DeliveryDocumentItem",
                "A_OutbDeliveryItem.ReferenceSDDocument",
                "A_OutbDeliveryItem.ReferenceSDDocumentItem",
                "A_OutbDeliveryHeader.OrderID",
                "A_OutbDeliveryHeader.ShippingPoint",
                "A_OutbDeliveryHeader.OverallSDProcessStatus",
                "A_OutbDeliveryItem.OrderID",
                "A_OutbDeliveryItem.Material",
                "A_OutbDeliveryItem.GoodsMovementStatus",
                "A_OutbDeliveryItem.DeliveryRelatedBillingStatus",
            ]
        if service_name == "API_MATERIAL_DOCUMENT_SRV":
            return [
                "A_MaterialDocumentItem.MaterialDocument",
                "A_MaterialDocumentItem.MaterialDocumentYear",
                "A_MaterialDocumentItem.MaterialDocumentItem",
                "A_MaterialDocumentItem.ManufacturingOrder",
                "A_MaterialDocumentItem.Material",
                "A_MaterialDocumentItem.Plant",
                "A_MaterialDocumentItem.GoodsMovementType",
                "A_MaterialDocumentItem.PurchaseOrder",
                "A_MaterialDocumentItem.PurchaseOrderItem",
            ]
        if service_name == "API_PRODUCTION_ORDER_2_SRV":
            return [
                "A_ProductionOrderOperation_2.ManufacturingOrder",
                "A_ProductionOrderOperation_2.ManufacturingOrderOperation",
                "A_ProductionOrderOperation_2.ProductionPlant",
                "A_ProductionOrderOperation_2.WorkCenter",
                "A_ProductionOrderOperation_2.MfgOrderOperationText",
                "A_ProductionOrder_2.ManufacturingOrder",
                "A_ProductionOrder_2.Material",
                "A_ProductionOrder_2.ProductionPlant",
            ]
        if service_name == "I_ProductionVersion":
            return [
                "I_ProductionVersion.Material",
                "I_ProductionVersion.Plant",
                "I_ProductionVersion.ProductionVersion",
                "I_ProductionVersion.ProductionVersionText",
                "I_ProductionVersion.ValidityStartDate",
                "I_ProductionVersion.ValidityEndDate",
                "I_ProductionVersion.MaterialMinLotSizeQuantity",
                "I_ProductionVersion.MaterialMaxLotSizeQuantity",
                "I_ProductionVersion.ProductionVersionStatus",
                "I_ProductionVersion.BillOfMaterialVariantUsage",
                "I_ProductionVersion.BillOfMaterialVariant",
                "I_ProductionVersion.BillOfOperationsType",
                "I_ProductionVersion.BillOfOperationsGroup",
                "I_ProductionVersion.BillOfOperationsVariant",
                "I_ProductionVersion.ProductionLine",
                "I_ProductionVersion.ProductionSupplyArea",
            ]
        return []

    @staticmethod
    def _pinned_entity_scores(service_name: str) -> dict[str, float]:
        if service_name == "API_SALES_ORDER_SRV":
            return {
                "A_SalesOrder": 140.0,
                "A_SalesOrderItem": 110.0,
                "A_SalesOrderItmSubsqntProcFlow": 70.0,
                "A_SalesOrderSubsqntProcFlow": 70.0,
            }
        if service_name == "API_OUTBOUND_DELIVERY_SRV":
            return {
                "A_OutbDeliveryHeader": 140.0,
                "A_OutbDeliveryItem": 120.0,
                "A_OutbDeliveryDocFlow": 80.0,
            }
        return {}

    @staticmethod
    def _service_core_tokens(service_name: str) -> list[str]:
        service = str(service_name or "")
        parts = [
            part
            for part in re.split(r"[_\W]+", service)
            if part and part not in {"API", "SRV", "PROCESS", "BASIC"}
        ]
        return [ApiCatalogProvider._normalize(part) for part in parts]

    @staticmethod
    def _humanize_entity_set(entity_set: str) -> str:
        name = str(entity_set or "")
        for prefix in ("A_", "C_", "I_"):
            if name.startswith(prefix):
                name = name[len(prefix) :]
        replacements = {
            "POSubcontracting": "Purchase Order Subcontracting",
            "PurOrd": "Purchase Order",
            "Purg": "Purchasing",
            "Suplr": "Supplier",
            "Invc": "Invoice",
            "Matl": "Material",
            "Stk": "Stock",
            "Outb": "Outbound",
        }
        for source, target in replacements.items():
            name = name.replace(source, target)
        name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
        name = re.sub(r"\s+", " ", name).strip()
        return name

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())
