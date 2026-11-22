"""Load editable discussion instructions, independent of the working directory."""
from pathlib import Path
from string import Template
from contextvars import ContextVar
from contextlib import contextmanager

DIRECTORY = Path(__file__).resolve().parent.parent / 'prompts' / 'discussion'
_snapshot = ContextVar('prompt_snapshot', default=None)


def snapshot():
    root = DIRECTORY.parent
    return {str(p.relative_to(root)): p.read_text(encoding='utf-8').strip()
            for p in root.rglob('*.md') if p.name != 'README.md'}


@contextmanager
def frozen(values):
    token = _snapshot.set(values)
    try:
        yield
    finally:
        _snapshot.reset(token)


def load_prompt(group, name):
    if any(not x or any(c not in 'abcdefghijklmnopqrstuvwxyz_' for c in x) for x in (group,name)):
        raise ValueError('Invalid prompt name')
    key = f'{group}/{name}.md'
    values = _snapshot.get()
    text = values[key] if values is not None else (DIRECTORY.parent / key).read_text(encoding='utf-8').strip()
    if not text:
        raise ValueError(f'Empty prompt: {key}')
    return text


def read_prompt(prompt_name: str, **values: str) -> str:
    if not prompt_name or any(c not in 'abcdefghijklmnopqrstuvwxyz_' for c in prompt_name):
        raise ValueError('Invalid prompt name')
    text = load_prompt('discussion', prompt_name)
    if not text:
        raise ValueError(f'Empty prompt: {prompt_name}')
    return Template(text).substitute(values) if values else text
