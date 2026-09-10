"""Python child read audit. This detects omitted project inputs; it is not a sandbox."""
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    config = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    root = Path(config['root']).resolve()
    allowed = {os.path.normcase(str((root / p).resolve())) for p in config['allowed']}
    ignored = [Path(p).resolve() for p in config['ignored']]
    prefix = Path(sys.prefix).resolve()
    if prefix.is_relative_to(root) and prefix != root:
        ignored.append(prefix)

    def audit(event, args):
        if event != 'open' or not isinstance(args[0], (str, bytes, os.PathLike)):
            return
        mode = args[1]
        if isinstance(mode, str) and any(x in mode for x in 'wax+'):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if not path.is_relative_to(root) or any(path.is_relative_to(p) for p in ignored):
            return
        if '__pycache__' in path.parts or not path.is_file():
            return
        if os.path.normcase(str(path)) not in allowed:
            raise RuntimeError(f'undeclared project read: {path.relative_to(root)}')

    sys.addaudithook(audit)
    argv = config['argv']
    sys.argv = argv
    if argv[0] == '-c':
        sys.argv = ['-c', *argv[2:]]
        exec(compile(argv[1], '<task>', 'exec'), {'__name__': '__main__'})
    elif argv[0] == '-m':
        sys.argv = argv[1:]
        runpy.run_module(argv[1], run_name='__main__', alter_sys=True)
    else:
        sys.path.insert(0, str(Path(argv[0]).resolve().parent))
        runpy.run_path(argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
