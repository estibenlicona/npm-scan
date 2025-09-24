import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

MODULE_NAME = "src.steps.step_01_get_repositories"


class Step01RepositoriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        cache_dir = Path(self.temp_dir.name) / ".npm_scan_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        if MODULE_NAME in sys.modules:
            del sys.modules[MODULE_NAME]
        self.module = importlib.import_module(MODULE_NAME)
        self.module.CACHE_DIR = str(cache_dir)
        self.module.CACHE_FILE = str(cache_dir / "repos_cache.json")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_save_and_load_repos_cache(self) -> None:
        sample = [{"repository": {"name": "sample"}}]
        self.module.save_repos_cache(sample)
        loaded = self.module.load_repos_cache()
        self.assertEqual(sample, loaded)

    def test_get_repositories_uses_cache_when_available(self) -> None:
        cached = [{"repository": {"name": "cached"}}]
        self.module.save_repos_cache(cached)
        with mock.patch.object(self.module, "fetch_repositories") as mocked_fetch:
            result = self.module.get_repositories(force=False)
        self.assertEqual(cached, result)
        mocked_fetch.assert_not_called()

    def test_get_repositories_forces_refresh_with_pagination(self) -> None:
        page_size_original = self.module.CODESEARCH_PAGE_SIZE
        self.module.CODESEARCH_PAGE_SIZE = 1
        self.addCleanup(lambda: setattr(self.module, "CODESEARCH_PAGE_SIZE", page_size_original))

        first_page = [{"repository": {"name": "fresh-1"}}]
        second_page = [{"repository": {"name": "fresh-2"}}]
        with mock.patch.object(
            self.module,
            "fetch_repositories",
            side_effect=[first_page, second_page, []],
        ) as mocked_fetch:
            repos = self.module.get_repositories(force=True)

        self.assertEqual(
            mocked_fetch.call_args_list,
            [
                mock.call(skip=0, top=1),
                mock.call(skip=1, top=1),
                mock.call(skip=2, top=1),
            ],
        )
        self.assertEqual(first_page + second_page, repos)
        self.assertEqual(first_page + second_page, self.module.load_repos_cache())

    def test_fetch_all_repositories_accumulates_until_last_page(self) -> None:
        results_pages = [
            [{"repository": {"name": "r1"}}, {"repository": {"name": "r2"}}],
            [{"repository": {"name": "r3"}}],
        ]
        with mock.patch.object(
            self.module,
            "fetch_repositories",
            side_effect=list(results_pages),
        ) as mocked_fetch:
            aggregated = self.module.fetch_all_repositories(page_size=2)

        self.assertEqual(
            mocked_fetch.call_args_list,
            [mock.call(skip=0, top=2), mock.call(skip=2, top=2)],
        )
        self.assertEqual(sum(results_pages, []), aggregated)


if __name__ == "__main__":
    unittest.main()
