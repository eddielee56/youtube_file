"""Prevent scheduled selection and rendering from reading different projects."""
from pathlib import Path
import json
import tempfile
import unittest

import autorender_v43 as scheduler


class RuntimePaths(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root=Path(self.directory.name)
        self.source=self.root/'checkout'/'AutoRender_V43'
        self.source.mkdir(parents=True)
        self.live=self.root/'live'
        for version in ('38','43'):
            folder=self.live/('AutoRender_V'+version)
            folder.mkdir(parents=True)
            (folder/('autorender_v'+version+'.py')).touch()

    def configure(self,project):
        (self.source/'runtime_config.json').write_text(json.dumps({'runtime_project':str(project)}),encoding='utf-8-sig')

    def test_checkout_default_is_preserved(self):
        self.assertEqual(scheduler.runtime_project(self.source),self.source.parent)

    def test_explicit_live_project_replaces_stale_checkout(self):
        self.configure(self.live)
        self.assertEqual(scheduler.runtime_project(self.source),self.live)
        weekly=scheduler.runtime_project(self.source)/'AutoRender_V38/output/weekly_topic_review.json'
        self.assertTrue(weekly.is_relative_to(self.live))

    def test_relative_project_is_resolved_from_checkout_not_working_directory(self):
        self.configure('../live')
        self.assertEqual(scheduler.runtime_project(self.source),self.live)

    def test_incomplete_configuration_fails_instead_of_using_old_topic(self):
        (self.live/'AutoRender_V38/autorender_v38.py').unlink()
        self.configure(self.live)
        with self.assertRaisesRegex(ValueError,'runtime_project missing'):
            scheduler.runtime_project(self.source)


if __name__=='__main__':
    unittest.main()
