"""Bundle the sibling local core package without copying numerical source into Git."""
from pathlib import Path
import argparse
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--core', type=Path, default=ROOT.parent / 'AirfoilFit')
args = parser.parse_args()
core = args.core.resolve()
if not (core / 'pyproject.toml').is_file():
    parser.error(f'Local AirfoilFit project not found: {core}')
# Finish building before replacing the generated bundle. A clean directory also
# prevents removed modules or old distribution metadata surviving an upgrade.
with tempfile.TemporaryDirectory(prefix='airfoil-core-') as directory:
    staged = Path(directory) / 'bundle'
    subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps',
                    '--target', str(staged), str(core)], check=True)
    if not (staged / 'airfoil_fit' / '__init__.py').is_file():
        raise RuntimeError('The built package is missing airfoil_fit.')
    target = ROOT / '_vendor'
    if target.resolve().parent != ROOT or target.is_symlink():
        raise RuntimeError('Unexpected generated bundle path.')
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(staged, target)
