"""Tests for the prompt rendering system (Jinja2-based)."""
import shutil
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import agent_prompting


class PromptingTests(unittest.TestCase):
    def setUp(self):
        self._tmp_root = ROOT / ".tmp-tests"
        self._tmp_root.mkdir(exist_ok=True)
        self._tmp = self._tmp_root / f"prompting-{uuid.uuid4().hex}"
        self._tmp.mkdir()

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)
        shutil.rmtree(self._tmp_root, ignore_errors=True)

    def test_load_project_context_prefers_known_files(self):
        root = self._tmp
        (root / "README.md").write_text("hola mundo", encoding="utf-8")

        context = agent_prompting.load_project_context(str(root))

        self.assertIn("Contexto del proyecto (README.md)", context)
        self.assertIn("hola mundo", context)

    def test_render_prompt_template_injects_shared_values(self):
        rendered = agent_prompting.render_prompt_template(
            "local_system_prompt.txt",
            work_dir="/tmp/proj",
            desktop="/tmp/Desktop",
            project_context="CTX",
            mode_section="MODO TEST",
        )
        self.assertIn("/tmp/proj", rendered)
        self.assertIn("CTX", rendered)
        self.assertIn("MODO TEST", rendered)

    def test_render_hybrid_prompt_injects_memories(self):
        rendered = agent_prompting.render_prompt_template(
            "hybrid_system_prompt.txt",
            work_dir="/tmp/proj",
            desktop="/tmp/Desktop",
            project_context="",
            memories="MEMORIA_TEST",
        )
        self.assertIn("/tmp/proj", rendered)
        self.assertIn("MEMORIA_TEST", rendered)

    def test_hybrid_prompt_skips_empty_sections(self):
        """Empty project_context and memories should not leave blank separator lines."""
        rendered = agent_prompting.render_prompt_template(
            "hybrid_system_prompt.txt",
            work_dir="/tmp/proj",
            desktop="/tmp/Desktop",
            project_context="",
            memories="",
        )
        # With Jinja2 {% if %} blocks, empty vars produce no content
        self.assertNotIn("None", rendered)

    def test_prompts_do_not_require_reasoning_tags(self):
        local_rendered = agent_prompting.render_prompt_template(
            "local_system_prompt.txt",
            work_dir="/tmp/proj",
            desktop="/tmp/Desktop",
            project_context="",
            mode_section="",
        )
        hybrid_rendered = agent_prompting.render_prompt_template(
            "hybrid_system_prompt.txt",
            work_dir="/tmp/proj",
            desktop="/tmp/Desktop",
            project_context="",
            memories="",
        )
        self.assertNotIn("<thought>", local_rendered)
        self.assertNotIn("<think>", local_rendered)
        self.assertNotIn("<thought>", hybrid_rendered)
        self.assertNotIn("<think>", hybrid_rendered)

    def test_hidden_reasoning_filter_strips_internal_blocks(self):
        flt = agent_prompting.HiddenReasoningFilter()
        part1 = flt.feed("visible <think>hidden")
        part2 = flt.feed(" more</think> text")
        part3 = flt.finish()
        self.assertEqual(part1, "visible ")
        self.assertEqual(part2, "")
        self.assertEqual(part3, " text")

    def test_build_system_prompt_uses_jinja2_override_template(self):
        class Logger:
            def error(self, *args, **kwargs):
                raise AssertionError(f"No esperaba error: {args!r} {kwargs!r}")

        override = self._tmp / "custom_prompt.txt"
        override.write_text("dir={{ work_dir }} | ctx={{ project_context }}", encoding="utf-8")

        rendered = agent_prompting.build_system_prompt(
            template_name="local_system_prompt.txt",
            work_dir="/repo",
            logger=Logger(),
            fallback_builder=lambda: "fallback",
            system_prompt_path=override,
            project_context="README",
        )
        self.assertEqual(rendered, "dir=/repo | ctx=README")

    def test_build_system_prompt_uses_legacy_override_template(self):
        """Override files using $variable (string.Template) still work."""
        class Logger:
            def error(self, *args, **kwargs):
                raise AssertionError(f"No esperaba error: {args!r} {kwargs!r}")

        override = self._tmp / "custom_prompt.txt"
        override.write_text("dir=$work_dir | ctx=$project_context", encoding="utf-8")

        rendered = agent_prompting.build_system_prompt(
            template_name="local_system_prompt.txt",
            work_dir="/repo",
            logger=Logger(),
            fallback_builder=lambda: "fallback",
            system_prompt_path=override,
            project_context="README",
        )
        self.assertEqual(rendered, "dir=/repo | ctx=README")


if __name__ == "__main__":
    unittest.main()
