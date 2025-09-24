import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

MODULE_NAME = "src.steps.step_05_publish_coverage"
CACHE_UTILS_MODULE = "src.steps.cache_utils"


class Step05PublishCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.cache_root = Path(self.temp_dir.name)

        # Ensure clean imports
        for name in (
            MODULE_NAME,
            CACHE_UTILS_MODULE,
            "step_05_publish_coverage",
            "cache_utils",
        ):
            sys.modules.pop(name, None)

        # Point CACHE_ROOT to temp dir
        self.cache_utils = importlib.import_module(CACHE_UTILS_MODULE)
        self.cache_utils.CACHE_ROOT = self.cache_root

        # Import module under test
        self.module = importlib.import_module(MODULE_NAME)

    def tearDown(self) -> None:
        for name in (
            MODULE_NAME,
            CACHE_UTILS_MODULE,
            "step_05_publish_coverage",
            "cache_utils",
        ):
            sys.modules.pop(name, None)

    def _write_csv(self, rows: list[dict[str, str]]) -> Path:
        # Match Step 04 CSV header
        header = [
            "project",
            "repository",
            "branch",
            "package_json_path",
            "repo_key",
            "lock_signature",
            "lock_source",
            "package_lock_path",
            "package_path",
            "entry_type",
            "package_name",
            "current_spec",
            "target_version",
            "covered",
            "status",
            # Optional extra column used for highlighting
            "is_malicious",
        ]
        csv_path = self.cache_root / "package_lock_audit.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        import csv

        with csv_path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=header)
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return csv_path

    def test_builds_html_and_cobertura_from_csv(self) -> None:
        # Create small dataset with two repos and one not_covered row
        rows = [
            {
                "project": "proj-a",
                "repository": "RepoA",
                "branch": "main",
                "package_json_path": "/a/package.json",
                "repo_key": "1|main|/a/package.json",
                "lock_signature": "sig-a",
                "lock_source": "repository",
                "package_lock_path": "package_lock/sig-a.json",
                "package_path": ".",
                "entry_type": "dependency",
                "package_name": "left-pad",
                "current_spec": "^1.3.0",
                "target_version": "1.3.0",
                "covered": "true",
                "status": "covered",
                "is_malicious": "",
            },
            {
                "project": "proj-b",
                "repository": "RepoB",
                "branch": "develop",
                "package_json_path": "/b/package.json",
                "repo_key": "2|develop|/b/package.json",
                "lock_signature": "sig-b",
                "lock_source": "repository",
                "package_lock_path": "package_lock/sig-b.json",
                "package_path": "node_modules/foo",
                "entry_type": "peer",
                "package_name": "bar",
                "current_spec": "^3.0.0",
                "target_version": "2.0.0",
                "covered": "false",
                "status": "not_covered",
                "is_malicious": "",
            },
        ]

        csv_path = self._write_csv(rows)

        # Run the click callback directly to avoid invoking CLI
        out_dir = self.cache_root / "report-html"
        summary_xml = out_dir / "cobertura.xml"
        self.module.run.callback(
            csv_path=str(csv_path),
            out_dir=str(out_dir),
            summary_xml=str(summary_xml),
        )

        index_html = out_dir / "index.html"
        self.assertTrue(index_html.exists())
        self.assertTrue(summary_xml.exists())

        html = index_html.read_text(encoding="utf-8")
        # Has details/summary groups
        self.assertIn("<details", html)
        self.assertIn("<summary>RepoA", html)
        self.assertIn("<summary>RepoB", html)
        # Has headers for key columns
        for col in (
            "project",
            "repository",
            "package_name",
            "status",
            "covered",
        ):
            self.assertIn(f"<th>{col}</th>", html)
        # Not covered row highlighted
        self.assertIn("class=\"malicious\"", html)

        # Minimal Cobertura content
        xml = summary_xml.read_text(encoding="utf-8")
        self.assertIn("<coverage", xml)
        self.assertIn("report-html/index.html", xml)

    def test_missing_csv_raises(self) -> None:
        missing = self.cache_root / "does-not-exist.csv"
        with self.assertRaises(self.module.click.ClickException):
            self.module.run.callback(
                csv_path=str(missing),
                out_dir=str(self.cache_root / "report-html"),
                summary_xml=str(self.cache_root / "report-html" / "cobertura.xml"),
            )


if __name__ == "__main__":
    unittest.main()

