from __future__ import annotations

from argparse import ArgumentParser, FileType
from dataclasses import dataclass
from io import StringIO
from typing import Tuple, List, Any, TextIO, Dict, Iterator, Optional, TypedDict

import yaml
from jinja2 import Environment, TemplateSyntaxError

from make_ssh_config.util import CIDict, dict_gets

display = print


def warning(*args, **kwargs):
    import sys
    kwargs['file'] = sys.stdout
    print(*args, **kwargs)


def yaml_str_list(o) -> List[str]:
    """
    Convert and flatten input to a list of str.

    the input may be None, str, a list of str, or a list of them recursively.
    """
    if o is None:
        return []
    elif isinstance(o, str):
        return [o]
    else:
        r = []
        for s in o:
            r.extend(yaml_str_list(s))
        return r


def merge_config(a, b) -> CIDict:
    """
    Merge two str-keyed dicts case-insensitively

    keys whose value are None is popped
    """
    o = CIDict()

    for k, v in a.items():
        if v is not None:
            o[k] = v

    for k, v in b.items():
        if v is None:
            o.pop(k)
        else:
            o[k] = v

    return o


class Keyword:
    IdentityFile = 'IdentityFile'.casefold()


class MatchDict(TypedDict):
    all: bool
    canonical: bool
    host: List[str]
    originalhost: List[str]
    user: List[str]
    localuser: List[str]
    exec: Optional[str]


@dataclass
class Layer:
    config: CIDict[str, Any]
    vars: Dict[str, Any]
    host: Optional[List[str]]
    match: Optional[MatchDict]

    def __post_init__(self):
        if self.host is not None and self.match is not None:
            raise ValueError

    def iter_decls(self) -> Iterator[Tuple[str, str]]:
        """Generate ssh_config pairs in (keyword, value)"""
        for option, value in self.config.items():
            if isinstance(value, (str, int)):
                yield option, str(value)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, (str, int)):
                        yield option, str(item)
                    else:
                        raise ValueError(f"Bad type {type(item)!r} in option {option} at index {i}")
            else:
                raise ValueError(f"Bad type {type(value)!r} in option {option}")

    def header_line(self) -> str:
        """Return the header line with trailing newline, eg. Host localhost, Match user root"""
        if self.host is not None:
            return 'Host %s\n' % ' '.join(self.host)
        elif self.match is not None:
            all_, canonical, exec_, host, originalhost, user, localuser = dict_gets(
                self.match,
                'all', 'canonical', 'exec', 'host', 'originalhost', 'user', 'localuser',
            )

            if all_ and (canonical or exec_ or host or originalhost or user or localuser):
                raise ValueError("The 'all' token must be alone or immediately after 'canonical'")

            args = []

            if canonical:
                args.append('canonical')

            if all_:
                args.append('all')

            if host:
                args.extend(('host', ','.join(host)))

            if originalhost:
                args.extend(('originalhost', ','.join(originalhost)))

            if user:
                args.extend(('user', ','.join(user)))

            if localuser:
                args.extend(('localuser', ','.join(localuser)))

            if exec_:
                args.extend(('exec', exec_))

            return 'Match %s\n' % ' '.join(args)

    def write(self, out: TextIO):
        """Write this entry to the output"""

        out.write(self.header_line())

        for option, value in self.iter_decls():
            out.write(f'    {option} {maybe_quote(value)}\n')

        out.write('\n')


def maybe_quote(s: str):
    """
    Quote the SSH option value if needed

    TODO Check the character escape logic behind OpenSSH?
    """

    parts = s.split()
    if len(parts) < 2:
        return s

    if '"' in s:
        raise ValueError(f"Double quote character in {s!r}")

    return '"%s"' % s


def normalize_host(host) -> List[str]:
    host = yaml_str_list(host)
    assert isinstance(host, list) and all(isinstance(s, str) for s in host), host
    return host


def normalize_match(match) -> MatchDict:
    keys = ('all', 'canonical', 'exec', 'host', 'originalhost', 'user', 'localuser')
    bad_key = next((k for k in match.keys() if k not in keys), None)
    if bad_key:
        raise ValueError(f"Unknown match key {bad_key!r}")

    all_, canonical, exec_, host, originalhost, user, localuser = dict_gets(match, *keys)
    del keys, bad_key

    return MatchDict(
        all=bool(all_),
        canonical=bool(canonical),
        host=yaml_str_list(host),
        originalhost=yaml_str_list(originalhost),
        user=yaml_str_list(user),
        localuser=yaml_str_list(localuser),
        exec=exec_,
    )


class ConfigMaker:
    def __init__(self):
        self.registry: Dict[str, Layer] = {}
        self.entries: List[Layer] = []
        self.jinja_env = Environment()

    def _check_record_keys(self, record):
        valid = {
            'config',
            'host',
            'match',
            'merge',
            'name',
            'vars',
        }
        bad_key = next((k for k in record.keys() if k not in valid), None)
        if bad_key:
            raise ValueError(f"Invalid layer attribute {bad_key}")

    def render_value(self, value, locals_, memo: Dict[int, Any] = None):
        """
        Take a mixture of str, int, bool, list, and dict, and substitute str values accordingly

        If the string are surrounded by double open and close curl brackets (eg, "{{ expr }}"),
        try to substitute the str value by the evaluation result of the Jinja expression. Otherwise, the string is rendered
        as Jinja template.
        """
        if isinstance(value, str):
            if value.startswith('{{') and value.endswith('}}'):
                # Try to interpret the expr result if possible, fallback to template string
                try:
                    tpl_expr = self.jinja_env.compile_expression(value[2:-2])
                except TemplateSyntaxError:
                    pass
                else:
                    return tpl_expr(locals_)

            template = self.jinja_env.from_string(value)
            return template.render(locals_)
        elif isinstance(value, (list, dict)):
            if memo is None:
                memo = {}

            id_ = id(value)

            if id_ in memo:
                return memo[id_]

            if isinstance(value, list):
                result = memo[id_] = []

                for item in value:
                    result.append(self.render_value(item, locals_, memo=memo))
            else:
                result = memo[id_] = {}
                for key, val in value.items():
                    result[key] = self.render_value(val, locals_, memo=memo)

            return result
        elif value is None or isinstance(value, (int, bool)):
            return value
        else:
            raise ValueError(f"Bad value type {type(value)!r}")

    def add_record(self, record):
        self._check_record_keys(record)

        name, merge, raw_vars = dict_gets(record, 'name', 'merge', 'vars')

        merged_vars = {}
        merged_config = CIDict()

        merge = yaml_str_list(merge)

        for lower_name in merge:
            try:
                lower_layer = self.registry[lower_name]
            except KeyError:
                raise ValueError(f"Undefined record '{lower_name}'")
            else:
                merged_config = merge_config(merged_config, lower_layer.config)
                merged_vars.update(lower_layer.vars)

        if raw_vars:
            merged_vars.update(self.render_value(raw_vars, {
                **merged_vars,
                'name': name,
            }))

        raw_config, raw_host, raw_match = dict_gets(record, 'config', 'host', 'match')

        host = match = None

        if raw_host is not None:
            if raw_match is not None:
                raise ValueError('Specifying both host and match is prohibited')

            host = yaml_str_list(self.render_value(raw_host, {
                **merged_vars,
                'name': name,
            }))

            if not isinstance(host, list):
                raise ValueError(f'host must be a str or list, got {type(host)!r}')
        elif raw_match is not None:
            match = normalize_match(self.render_value(raw_match, {
                **merged_vars,
                'name': name,
            }))

        config = None
        if raw_config:
            # Substitute values with merged_vars and merged_config
            config = self.render_value(raw_config, {
                **merged_vars,
                'name': name,
                'host': host,
                'match': match,
            })
            merged_config = merge_config(merged_config, config)

        layer = Layer(
            config=merged_config,
            vars=merged_vars,
            host=host,
            match=match,
        )

        if name:
            self.registry[name] = layer

        if host or match:
            self.entries.append(layer)


def main():
    p = ArgumentParser()
    p.add_argument(
        '--output', nargs='?', default='-', type=FileType('w', encoding='utf-8'),
        help='default to standard output',
    )
    p.add_argument(
        'input', nargs='?', default='config.yaml', type=FileType('rb'),
        help='default to %(default)s',
    )

    args = p.parse_args()

    records = yaml.safe_load(args.input.read())
    config_maker = ConfigMaker()

    for record in records:
        config_maker.add_record(record)

    with StringIO() as out:
        for entry in config_maker.entries:
            entry.write(out)

        args.output.write(out.getvalue())
        args.output.flush()


if __name__ == '__main__':
    main()
