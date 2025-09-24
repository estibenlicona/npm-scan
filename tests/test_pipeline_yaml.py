import unittest
from pathlib import Path
import yaml


class PipelineYamlTests(unittest.TestCase):
    def test_pipeline_yaml_parses_and_has_force_blocks(self) -> None:
        content = Path('azure-pipelines.yml').read_text(encoding='utf-8')
        data = yaml.safe_load(content)

        self.assertIn('parameters', data)
        stages = data.get('stages')
        self.assertIsInstance(stages, list)
        self.assertGreaterEqual(len(stages), 1)

        jobs = stages[0].get('jobs')
        self.assertIsInstance(jobs, list)
        self.assertGreaterEqual(len(jobs), 1)

        steps = jobs[0].get('steps')
        self.assertIsInstance(steps, list)

        forced_scripts = []
        default_scripts = []

        for entry in steps:
            if not isinstance(entry, dict):
                continue
            if len(entry) != 1:
                continue
            key = next(iter(entry.keys()))
            if not isinstance(key, str):
                continue
            nested_steps = entry[key]
            if not isinstance(nested_steps, list):
                continue
            for nested in nested_steps:
                if not isinstance(nested, dict):
                    continue
                script = nested.get('script')
                if not isinstance(script, str):
                    continue
                if '--force' in script:
                    forced_scripts.append(script)
                else:
                    default_scripts.append(script)

        self.assertEqual(len(forced_scripts), 4, 'Expected forced scripts for steps 01-04')
        self.assertEqual(len(default_scripts), 4, 'Expected default scripts for steps 01-04')
        for script in default_scripts:
            self.assertNotIn('--force', script)


if __name__ == '__main__':
    unittest.main()
