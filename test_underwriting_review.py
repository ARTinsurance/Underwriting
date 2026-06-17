import tempfile
import unittest
from datetime import date
from pathlib import Path

from underwriting_review import (
    SanctionsSnapshot,
    extract_parties,
    render_markdown,
    review_listed_areas,
    review_offering,
    review_quotation,
    same_vessel_history,
)


class UnderwritingReviewTests(unittest.TestCase):
    def make_snapshot(self) -> SanctionsSnapshot:
        snapshot = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        snapshot.write(
            """{
              "generated_at": "2026-06-01T00:00:00Z",
              "records": [
                {"source": "eu", "name": "Listed EU Shipping Ltd", "program": "EU test", "reference": "EU1"},
                {"source": "uk", "name": "Blocked UK Owner", "program": "UK test", "reference": "UK1"},
                {"source": "ofac_sdn", "name": "OFAC Charterer LLC", "program": "SDN", "reference": "US1"}
              ]
            }"""
        )
        snapshot.close()
        self.addCleanup(lambda: Path(snapshot.name).unlink(missing_ok=True))
        return SanctionsSnapshot(Path(snapshot.name))

    def test_extracts_parties_from_multiple_slip_shapes(self):
        slip = {
            "parties": [{"role": "broker", "name": "Marine Broker Ltd"}],
            "assured": "Assured Co",
            "vessel": {"registered_owner": "Registered Owner Ltd"},
        }

        parties = extract_parties(slip)

        self.assertEqual(
            [(party.role, party.name) for party in parties],
            [
                ("broker", "Marine Broker Ltd"),
                ("assured", "Assured Co"),
                ("registered owner", "Registered Owner Ltd"),
            ],
        )

    def test_sanctions_results_are_grouped_by_eu_uk_us(self):
        snapshot = self.make_snapshot()
        slip = {
            "parties": [
                {"role": "owner", "name": "Listed EU Shipping Ltd"},
                {"role": "manager", "name": "Blocked UK Owner"},
                {"role": "charterer", "name": "OFAC Charterer LLC"},
            ]
        }

        report = review_quotation(slip, snapshot, [])
        results = report["sanctions_results"]

        self.assertEqual(results[0]["checks"]["EU"][0]["reference"], "EU1")
        self.assertEqual(results[1]["checks"]["UK"][0]["reference"], "UK1")
        self.assertEqual(results[2]["checks"]["US"][0]["reference"], "US1")

    def test_same_vessel_history_filters_to_previous_three_months(self):
        slip = {
            "quotation_date": "2026-06-17",
            "vessel": {"name": "Dubai Tower", "imo": "9433066"},
        }
        history = [
            {"quote_id": "Q1", "quotation_date": "2026-06-01", "vessel_imo": "9433066"},
            {"quote_id": "Q2", "quotation_date": "2026-03-17", "vessel_name": "DUBAI TOWER"},
            {"quote_id": "Q3", "quotation_date": "2026-03-16", "vessel_imo": "9433066"},
            {"quote_id": "Q4", "quotation_date": "2026-06-01", "vessel_name": "Other Vessel"},
        ]

        matches = same_vessel_history(slip, history, as_of=date(2026, 6, 17))

        self.assertEqual([item["quote_id"] for item in matches], ["Q1", "Q2"])

    def test_listed_area_review_uses_explicit_and_inferred_values(self):
        slip = {
            "listed_areas": ["Black Sea and Sea of Azov"],
            "trading_limits": "Including Ukraine calls, excluding sanctioned trades.",
        }

        review = review_listed_areas(slip)

        self.assertIn("Black Sea and Sea of Azov", review["explicit_listed_areas"])
        self.assertIn("Black Sea", review["inferred_listed_areas"])
        self.assertIn("Ukraine", review["inferred_listed_areas"])

    def test_offering_summary_builds_client_wording(self):
        review = review_offering(
            {
                "coverage": "war risks",
                "limit": "USD 10,000,000",
                "premium": "USD 25,000",
            }
        )

        self.assertIn("war risks", review["client_wording"])
        self.assertIn("USD 10,000,000", review["client_wording"])
        self.assertIn("deductible", review["missing_fields"])

    def test_markdown_renders_main_sections(self):
        snapshot = self.make_snapshot()
        report = review_quotation(
            {
                "quotation_date": "2026-06-17",
                "vessel": {"name": "Test Vessel", "imo": "1234567"},
                "parties": [{"role": "owner", "name": "Clear Owner"}],
                "coverage": "war risks",
            },
            snapshot,
            [],
        )

        markdown = render_markdown(report)

        self.assertIn("## Sanctions Check Results", markdown)
        self.assertIn("## Same-Vessel Quotation History", markdown)
        self.assertIn("## Listed Areas", markdown)
        self.assertIn("## Client Offering", markdown)


if __name__ == "__main__":
    unittest.main()
