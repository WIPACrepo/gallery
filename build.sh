#!/bin/bash
set -e
. env/bin/activate
SRC=${SRC:-albums}
BUILD=${BUILD:-_build}
sigal build --debug $SRC $BUILD
python minify.py theme/static $BUILD/static
