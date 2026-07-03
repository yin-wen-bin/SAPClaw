import json
from pathlib import Path

from sap_odata_agent.infrastructure.indexing.dual_source_index_builder import (
    DualSourceIndexBuilder,
    OpenApiDocumentParser,
    SapMetadataParser,
    SapConnectionConfig,
)


SAMPLE_XML = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="API_TEST" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="A_BusinessPartnerType">
        <Key>
          <PropertyRef Name="BusinessPartner"/>
        </Key>
        <Property Name="BusinessPartner" Type="Edm.String" Nullable="false" sap:label="Business Partner Number"/>
        <Property Name="Customer" Type="Edm.String" sap:label="Customer Number" sap:filter-restriction="single-value"/>
        <NavigationProperty Name="to_Address" Relationship="API_TEST.to_Address"/>
      </EntityType>
      <EntityContainer Name="API_TEST_Entities" m:IsDefaultEntityContainer="true" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
        <EntitySet Name="A_BusinessPartner" EntityType="API_TEST.A_BusinessPartnerType" sap:creatable="true" sap:updatable="true" sap:deletable="false"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""

SAMPLE_OPENAPI = {
    "openapi": "3.0.0",
    "info": {
        "title": "Business Partner",
        "version": "1.0.0",
        "description": "OpenAPI description for the business partner service.",
    },
    "externalDocs": {"url": "https://example.com/docs"},
    "servers": [{"url": "https://example.com/sap/opu/odata/sap/API_TEST"}],
    "paths": {
        "/A_BusinessPartner": {
            "get": {"summary": "Read business partners", "tags": ["Business Partner"]},
            "post": {"summary": "Create business partners", "tags": ["Business Partner"]},
        }
    },
    "components": {
        "schemas": {
            "API_TEST.A_BusinessPartnerType": {
                "properties": {
                    "BusinessPartner": {"description": "Business partner id from OpenAPI"},
                    "Customer": {"description": "Customer number from OpenAPI"},
                    "BusinessPartnerFullName": {"description": "Full name from OpenAPI"},
                }
            }
        }
    },
}


def test_parsers_and_merge_include_runtime_and_doc_only_fields() -> None:
    metadata_parser = SapMetadataParser()
    openapi_parser = OpenApiDocumentParser()
    builder = DualSourceIndexBuilder(metadata_parser=metadata_parser, openapi_parser=openapi_parser)

    parsed_metadata = metadata_parser.parse(SAMPLE_XML, "API_TEST", "http://sap.example.com/$metadata")
    parsed_openapi = openapi_parser.parse(SAMPLE_OPENAPI, "<LOCAL_OPENAPI_FILE>")
    bundle = builder._merge(parsed_metadata, parsed_openapi, "API_TEST")

    service = bundle.services[0]
    assert service.documentation_available is True
    assert service.runtime_available is True

    entity = next(item for item in bundle.entities if item.entity_set == "A_BusinessPartner")
    assert set(entity.supported_methods) >= {"GET", "POST", "PATCH"}
    assert entity.documentation_available is True

    runtime_field = next(
        item for item in bundle.fields if item.entity_set == "A_BusinessPartner" and item.field_name == "BusinessPartner"
    )
    assert runtime_field.runtime_available is True
    assert runtime_field.documentation_available is True
    assert runtime_field.description

    doc_only_field = next(
        item
        for item in bundle.fields
        if item.entity_set == "A_BusinessPartner" and item.field_name == "BusinessPartnerFullName"
    )
    assert doc_only_field.runtime_available is False
    assert doc_only_field.documentation_available is True


def test_merge_uses_metadata_business_aliases_for_payment_terms() -> None:
    metadata_parser = SapMetadataParser()
    openapi_parser = OpenApiDocumentParser()
    builder = DualSourceIndexBuilder(metadata_parser=metadata_parser, openapi_parser=openapi_parser)

    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="API_TEST" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="A_SupplierCompanyType">
        <Key>
          <PropertyRef Name="Supplier"/>
          <PropertyRef Name="CompanyCode"/>
        </Key>
        <Property Name="Supplier" Type="Edm.String" Nullable="false" sap:label="Supplier"/>
        <Property Name="CompanyCode" Type="Edm.String" Nullable="false" sap:label="Company Code"/>
        <Property Name="PaymentTerms" Type="Edm.String" sap:label="付款条件" sap:quickinfo="付款条件代码"/>
      </EntityType>
      <EntityContainer Name="API_TEST_Entities" m:IsDefaultEntityContainer="true" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
        <EntitySet Name="A_SupplierCompany" EntityType="API_TEST.A_SupplierCompanyType" sap:creatable="true" sap:updatable="true" sap:deletable="false"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    sample_openapi = {
        "openapi": "3.0.0",
        "info": {"title": "Supplier Company", "version": "1.0.0"},
        "servers": [{"url": "https://example.com/sap/opu/odata/sap/API_TEST"}],
        "paths": {"/A_SupplierCompany": {"get": {"summary": "Read supplier company data", "tags": ["Supplier Company"]}}},
        "components": {
            "schemas": {
                "API_TEST.A_SupplierCompanyType": {
                    "properties": {
                        "PaymentTerms": {"description": "Payment terms code"},
                    }
                }
            }
        },
    }

    parsed_metadata = metadata_parser.parse(sample_xml, "API_TEST", "http://sap.example.com/$metadata")
    parsed_openapi = openapi_parser.parse(sample_openapi, "<LOCAL_OPENAPI_FILE>")
    bundle = builder._merge(parsed_metadata, parsed_openapi, "API_TEST")

    payment_terms_field = next(
        item for item in bundle.fields if item.entity_set == "A_SupplierCompany" and item.field_name == "PaymentTerms"
    )
    assert "付款条件" in payment_terms_field.business_aliases
    assert "付款条件代码" in payment_terms_field.business_aliases

    payment_terms_alias = next(
        item
        for item in bundle.business_terms
        if item.term == "付款条件代码" and item.mapped_entity_set == "A_SupplierCompany"
    )
    assert payment_terms_alias.mapped_fields == ["PaymentTerms"]


def test_builder_writes_index_files(tmp_path: Path) -> None:
    class StubFetcher:
        def fetch(self, config, service_name: str) -> tuple[str, str]:
            return SAMPLE_XML, f"https://sap.example.com/{service_name}/$metadata"

    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text(json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    builder = DualSourceIndexBuilder(fetcher=StubFetcher())
    bundle = builder.build(
        sap_config=SapConnectionConfig(
            base_url="https://sap.example.com",
            username="user",
            password="pass",
            client="100",
        ),
        sap_service_name="API_TEST",
        openapi_json_path=openapi_path,
        output_root=tmp_path / "index",
    )

    output_dir = tmp_path / "index" / "API_TEST"
    assert (output_dir / "services.json").exists()
    assert (output_dir / "entities.json").exists()
    assert (output_dir / "fields.json").exists()
    assert (output_dir / "lookup_paths.json").exists()
    assert (output_dir / "vector_documents.jsonl").exists()
    assert (output_dir / "doc_chunks.jsonl").exists()
    assert bundle.summary["merged_entity_count"] >= 1
    assert bundle.summary["vector_document_count"] >= 1


def test_builder_reads_openapi_json_with_utf8_bom(tmp_path: Path) -> None:
    class StubFetcher:
        def fetch(self, config, service_name: str) -> tuple[str, str]:
            return SAMPLE_XML, f"https://sap.example.com/{service_name}/$metadata"

    openapi_path = tmp_path / "openapi.json"
    openapi_path.write_text("\ufeff" + json.dumps(SAMPLE_OPENAPI), encoding="utf-8")

    builder = DualSourceIndexBuilder(fetcher=StubFetcher())
    bundle = builder.build(
        sap_config=SapConnectionConfig(
            base_url="https://sap.example.com",
            username="user",
            password="pass",
            client="100",
        ),
        sap_service_name="API_TEST",
        openapi_json_path=openapi_path,
        output_root=tmp_path / "index",
    )

    assert bundle.summary["merged_entity_count"] >= 1


def test_merge_uses_metadata_business_aliases_for_planned_delivery_time() -> None:
    metadata_parser = SapMetadataParser()
    openapi_parser = OpenApiDocumentParser()
    builder = DualSourceIndexBuilder(metadata_parser=metadata_parser, openapi_parser=openapi_parser)

    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="API_TEST" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="A_SupplierPurchasingOrgType">
        <Key>
          <PropertyRef Name="Supplier"/>
          <PropertyRef Name="PurchasingOrganization"/>
        </Key>
        <Property Name="Supplier" Type="Edm.String" Nullable="false" sap:label="Supplier"/>
        <Property Name="PurchasingOrganization" Type="Edm.String" Nullable="false" sap:label="Purchasing Organization"/>
        <Property Name="MaterialPlannedDeliveryDurn" Type="Edm.String" sap:label="计划交货时间" sap:quickinfo="计划交货时间（天）"/>
      </EntityType>
      <EntityContainer Name="API_TEST_Entities" m:IsDefaultEntityContainer="true" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
        <EntitySet Name="A_SupplierPurchasingOrg" EntityType="API_TEST.A_SupplierPurchasingOrgType" sap:creatable="true" sap:updatable="true" sap:deletable="false"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""

    parsed_metadata = metadata_parser.parse(sample_xml, "API_TEST", "http://sap.example.com/$metadata")
    parsed_openapi = openapi_parser.parse(SAMPLE_OPENAPI, "<LOCAL_OPENAPI_FILE>")
    bundle = builder._merge(parsed_metadata, parsed_openapi, "API_TEST")

    field = next(
        item
        for item in bundle.fields
        if item.entity_set == "A_SupplierPurchasingOrg" and item.field_name == "MaterialPlannedDeliveryDurn"
    )
    assert "计划交货时间" in field.business_aliases
    assert "计划交货时间（天）" in field.business_aliases


def test_merge_builds_attribute_filter_lookup_path_for_city_to_supplier_list() -> None:
    metadata_parser = SapMetadataParser()
    openapi_parser = OpenApiDocumentParser()
    builder = DualSourceIndexBuilder(metadata_parser=metadata_parser, openapi_parser=openapi_parser)

    sample_xml = """<?xml version="1.0" encoding="utf-8"?>
<edmx:Edmx xmlns:edmx="http://schemas.microsoft.com/ado/2007/06/edmx">
  <edmx:DataServices>
    <Schema Namespace="API_TEST" xmlns="http://schemas.microsoft.com/ado/2008/09/edm" xmlns:sap="http://www.sap.com/Protocols/SAPData">
      <EntityType Name="A_BusinessPartnerType">
        <Key>
          <PropertyRef Name="BusinessPartner"/>
        </Key>
        <Property Name="BusinessPartner" Type="Edm.String" Nullable="false" sap:label="Business Partner"/>
        <Property Name="Supplier" Type="Edm.String" sap:label="Supplier"/>
      </EntityType>
      <EntityType Name="A_BusinessPartnerAddressType">
        <Key>
          <PropertyRef Name="BusinessPartner"/>
          <PropertyRef Name="AddressID"/>
        </Key>
        <Property Name="BusinessPartner" Type="Edm.String" Nullable="false" sap:label="Business Partner"/>
        <Property Name="AddressID" Type="Edm.String" Nullable="false" sap:label="Address ID"/>
        <Property Name="CityName" Type="Edm.String" sap:label="城市" sap:quickinfo="城市"/>
      </EntityType>
      <EntityContainer Name="API_TEST_Entities" m:IsDefaultEntityContainer="true" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata">
        <EntitySet Name="A_BusinessPartner" EntityType="API_TEST.A_BusinessPartnerType"/>
        <EntitySet Name="A_BusinessPartnerAddress" EntityType="API_TEST.A_BusinessPartnerAddressType"/>
      </EntityContainer>
    </Schema>
  </edmx:DataServices>
</edmx:Edmx>
"""
    sample_openapi = {
        "openapi": "3.0.0",
        "info": {"title": "Business Partner", "version": "1.0.0"},
        "servers": [{"url": "https://example.com/sap/opu/odata/sap/API_TEST"}],
        "paths": {
            "/A_BusinessPartner": {"get": {"summary": "Read business partners", "tags": ["Business Partner"]}},
            "/A_BusinessPartnerAddress": {"get": {"summary": "Read business partner addresses", "tags": ["Business Partner"]}},
        },
        "components": {
            "schemas": {
                "API_TEST.A_BusinessPartnerType": {"properties": {"BusinessPartner": {}, "Supplier": {}}},
                "API_TEST.A_BusinessPartnerAddressType": {"properties": {"BusinessPartner": {}, "CityName": {}}},
            }
        },
    }

    parsed_metadata = metadata_parser.parse(sample_xml, "API_TEST", "http://sap.example.com/$metadata")
    parsed_openapi = openapi_parser.parse(sample_openapi, "<LOCAL_OPENAPI_FILE>")
    bundle = builder._merge(parsed_metadata, parsed_openapi, "API_TEST")

    path = next(
        item
        for item in bundle.lookup_paths
        if item.path_id == "supplier_list_by_cityname_via_a_businesspartneraddress"
    )
    assert path.path_kind == "attribute_filter_list"
    assert path.return_object == "Supplier"
    assert path.filter_fields == ["CityName"]
