from __future__ import annotations

import subprocess
import sys


def test_core_compilation_does_not_import_web_or_cli_dependencies():
    code = """
import sys
from prompt_selector.compiler import PromptCompiler
from prompt_selector.domain import ModelProfile, TaskProfile, TaskType
from prompt_selector.normalizer import normalize_description
from prompt_selector.registry import Registry
from prompt_selector.selector import Selector

registry = Registry.load()
task = TaskProfile(task_type=TaskType.structured_extraction, model=ModelProfile())
technique = registry.technique('direct.explicit-constraints')
PromptCompiler().compile(task, technique, 'Mara entered Veyr.')
Selector(registry).select(task)
normalize_description('Extract entities.', ModelProfile())
assert 'fastapi' not in sys.modules
assert 'typer' not in sys.modules
"""
    subprocess.run([sys.executable, "-c", code], check=True)
