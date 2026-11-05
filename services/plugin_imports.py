"""Fresh source imports for each plugin generation, including relative helpers."""
import importlib.abc
import importlib.machinery
import importlib.util
from pathlib import Path
import sys


class SourceLoader(importlib.machinery.SourceFileLoader):
    def get_code(self, fullname):
        return self.source_to_code(self.get_data(self.path), self.path)


class PluginFinder(importlib.abc.MetaPathFinder):
    def __init__(self):
        self.roots: dict[str, Path] = {}

    def find_spec(self, fullname, path=None, target=None):
        root = self.roots.get(fullname.split('.')[0])
        if root is None or path is None:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec and isinstance(spec.loader, importlib.machinery.SourceFileLoader):
            source = Path(spec.origin).resolve()
            if not source.is_relative_to(root):
                raise ImportError('Relative plugin imports must stay inside the plugin folder')
            spec.loader = SourceLoader(fullname, str(source))
        return spec


finder = PluginFinder()


def load(name: str, entry: Path, folder: Path):
    if finder not in sys.meta_path:
        sys.meta_path.insert(0, finder)
    finder.roots[name] = folder
    loader = SourceLoader(name, str(entry))
    spec = importlib.util.spec_from_file_location(name, entry, loader=loader,
                                                submodule_search_locations=[str(folder)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    return module, loader


def forget(name: str):
    finder.roots.pop(name, None)
    for key in list(sys.modules):
        if key == name or key.startswith(name + '.'):
            sys.modules.pop(key, None)
