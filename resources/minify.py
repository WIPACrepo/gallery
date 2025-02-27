import argparse
from pathlib import Path
import os
import shutil
import glob
from io import open, StringIO

from jsmin import jsmin as minify


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('src', type=Path)
    parser.add_argument('dest', type=Path)
    args = parser.parse_args()

    for root,dirs,files in os.walk(args.src):
        for f in files:
            src = Path(root) / f
            if src.suffix == '.js' and '.min.js' not in src.name:
                if src.with_stem(src.stem + '.min').exists():
                    print(f'skipping {src}, already minified')
                    continue
                dest = Path(root.replace(str(args.src), str(args.dest))) / f
                dest = dest.with_stem(dest.stem + '.min')
                print(f'minifying {src} to {dest}')
                with open(src) as f_src, open(dest, 'w') as f_dest:
                    f_dest.write(minify(f_src.read(), quote_chars="'\"`"))


if __name__ == '__main__':
    main()
