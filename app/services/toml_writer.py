import json
from os import PathLike


def _format_value(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, PathLike):
        return json.dumps(str(value), ensure_ascii=False)
    raise TypeError(f'Unsupported TOML value: {type(value).__name__}')


def dumps(sections: dict[str, dict]):
    lines = []
    for section, options in sections.items():
        if lines:
            lines.append('')
        lines.append(f'[{section}]')
        for key, value in options.items():
            lines.append(f'{key} = {_format_value(value)}')
    return '\n'.join(lines) + '\n'


def dumps_values(values: dict):
    lines = [f'{key} = {_format_value(value)}' for key, value in values.items()]
    return '\n'.join(lines) + '\n'
