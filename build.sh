#!/bin/bash
set -e
. env/bin/activate
sigal build --debug albums
python minify.py theme/static _build/static
