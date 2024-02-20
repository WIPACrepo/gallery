#!/bin/bash
set -e
SRC=${SRC:-albums}
BUILD=${BUILD:-_build}
THEME=${THEME:-src/gallery/data/theme}

sigal build --debug $SRC $BUILD $@
python minify.py $THEME/static $BUILD/static

cp $THEME/static/favicon.ico $BUILD/

chmod -R +r $BUILD
find $BUILD -type d -exec chmod 2755 {} +
