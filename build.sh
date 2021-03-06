#!/bin/bash
set -e
SRC=${SRC:-albums}
BUILD=${BUILD:-_build}

sigal build --debug $SRC $BUILD $@
python minify.py theme/static $BUILD/static

cp theme/static/favicon.ico $BUILD/

chmod -R +r $BUILD
find $BUILD -type d -exec chmod 2755 {} +
