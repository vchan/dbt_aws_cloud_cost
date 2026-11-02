"""Static configuration invariants for the demo.

These are fast, no-dbt-run checks that catch the ways a fresh clone silently
breaks: a missing seed column, an env var referenced by the config but
undocumented in `.env.example`, or leftover references to tooling that was
removed.

Run: uv run --with pytest pytest tests/test_demo_configuration.py -v
"""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class DemoConfigurationTest(unittest.TestCase):
    def read(self, rel: str) -> str:
        return (ROOT / rel).read_text()

    def test_required_artifacts_exist(self):
        for rel in [
            "profiles.yml",
            "dbt_project.yml",
            ".env.example",
            "scripts/setup.sh",
            "seeds/aws_cost_report.csv",
            "seeds/properties.yml",
            "catalogs.yml",
        ]:
            with self.subTest(present=rel):
                self.assertTrue((ROOT / rel).is_file(), f"missing required file: {rel}")
        # Tooling removed during simplification and the Snowflake port must stay gone.
        for gone in [
            "scripts/setup_env.sh",
            "scripts/generate_local_csv.sh",
            "scripts/start.sh",
            "scripts/stop.sh",
            "scripts/count_aws_cost_rows.sh",
            "scripts/polaris_shadowtraffic.py",
            "scripts/use_catalog.sh",
            "shadowtraffic",
            "local_files",
            "scripts/snowflake_sql_api.py",
            "scripts/set_network_policy.py",
            "scripts/refresh_horizon_token.sh",
            "scripts/configure_horizon_schema.sh",
            "scripts/doctor.sh",
            "macros/create_seed_db.sql",
            "macros/set_rsa_public_key.sql",
            "models/staging/src_aws_cloud_cost.yml",
            "models/staging/base/stg_aws_cloud_cost__report_base.sql",
        ]:
            with self.subTest(removed=gone):
                self.assertFalse((ROOT / gone).exists(), f"should have been removed: {gone}")

    def test_seed_has_report_columns(self):
        header = self.read("seeds/aws_cost_report.csv").splitlines()[0]
        for column in ["identity_line_item_id", "line_item_unblended_cost", "_modified", "_file"]:
            with self.subTest(column=column):
                self.assertIn(column, header)

    def test_env_example_covers_referenced_env_vars(self):
        def referenced(text: str) -> set:
            return set(re.findall(r"env_var\('([A-Z][A-Z0-9_]*)'", text))

        refs = referenced(self.read("profiles.yml"))
        documented = set(
            re.findall(r"^#? ?([A-Z][A-Z0-9_]*)=", self.read(".env.example"), re.M)
        )
        self.assertEqual(
            refs - documented,
            set(),
            "env vars referenced in profiles.yml but missing from .env.example",
        )

    def test_profiles_prod_target_has_exactly_one_default_adapter(self):
        # `prod` is a multi-adapter target: a YAML list of connections, exactly
        # one of which is `default: true` (the rest are opted into per-model via
        # `+adapter:`).
        profiles = self.read("profiles.yml")
        types = re.findall(r"- type:\s*(\w+)", profiles)
        self.assertEqual(
            sorted(types),
            ["bigquery", "lakecompute"],
            "prod target should declare exactly the bigquery + lakecompute connections",
        )
        self.assertEqual(
            profiles.count("default: true"),
            1,
            "exactly one connection in the prod target must be the default",
        )

    def test_profiles_have_no_snowflake_left(self):
        for rel in ["profiles.yml", "dbt_project.yml", "README.md", ".env.example"]:
            with self.subTest(file=rel):
                self.assertNotIn("SNOWFLAKE_", self.read(rel))

    def test_catalog_is_a_biglake_metastore(self):
        catalogs = self.read("catalogs.yml")
        self.assertIn("type: biglake_metastore", catalogs)
        self.assertIn("gs://", catalogs)

    def test_staging_reads_from_the_seed(self):
        staging = self.read("models/staging/stg_report.sql")
        self.assertIn("ref('aws_cost_report')", staging, "staging must read the committed seed")
        self.assertNotIn("read_csv", staging)
        self.assertNotIn("source(", staging)
        self.assertNotIn("env_var", staging)
        self.assertNotIn(" over (", staging.lower(), "staging must avoid window functions")
        self.assertIn("catalog_name='bigquery_iceberg'", staging)
        self.assertNotIn("table_format", staging.replace("catalog_name", ""))
        self.assertNotIn("try_cast", staging, "use dbt.safe_cast, not a Snowflake function")

    def test_daily_overview_routes_through_lakecompute(self):
        overview = self.read("models/daily_overview.sql")
        self.assertIn("else 'lakecompute'", overview)
        self.assertIn("aws_cloud_cost_reference", overview)
        self.assertNotIn("propagate", overview)

    def test_readme_documents_the_current_flow(self):
        readme = self.read("README.md")
        for snippet in [
            ".env.example",
            "dbt seed",
            "aws_cloud_cost_reference",
            "lakecompute",
            "daily_overview",
        ]:
            with self.subTest(present=snippet):
                self.assertIn(snippet, readme)
        for gone in [
            "use_catalog.sh",
            "local_files",
            "shadowtraffic",
            "setup_env.sh",
            "DBT_BIN",
        ]:
            with self.subTest(absent=gone):
                self.assertNotIn(gone, readme)

    def test_shell_scripts_use_uv_not_bare_python(self):
        for script in sorted(ROOT.glob("scripts/*.sh")):
            for line in script.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith("#") or "python" not in stripped:
                    continue
                with self.subTest(script=script.name, line=stripped):
                    self.assertIn("uv run", stripped, "invoke python via `uv run`, never bare")


if __name__ == "__main__":
    unittest.main()
