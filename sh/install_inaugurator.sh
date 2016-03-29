#!/bin/bash
set -e
PRODUCT=inaugurator
INSTALLATION_CMD="make install IMAGES_SOURCE=remote"
REPOSITORY_LOCATION="https://github.com/stratoscale"
REQUIREMENTS_FILE="requirements.txt"

PIP_REQUIREMENT=`cat $REQUIREMENTS_FILE | grep $PRODUCT`
echo "Validating installation of $PIP_REQUIREMENT"
REQUIRED_VERSION=`echo $PIP_REQUIREMENT | cut -d "=" -f 3`
ACTUAL_VERSION=`pip show $PRODUCT | grep -E "^Version: " | cut -d " " -f 2`
REQUIRED_GIT_COMMITREF="v$REQUIRED_VERSION"
if [ "$REQUIRED_VERSION" == "$ACTUAL_VERSION" ]; then
    echo "Already installed."
else
    echo "Installing $PIP_REQUIREMENT"
    TMPDIR=`mktemp -d`
    git clone $REPOSITORY_LOCATION/$PRODUCT $TMPDIR/$PRODUCT
    if [ ! -z "$REQUIRED_VERSION" -a "$REQUIRED_VERSION" != " " ]; then
        (cd $TMPDIR/$PRODUCT && git checkout $REQUIRED_GIT_COMMITREF && cd - ) || { echo "Cannot continue; Apparently, there is no branch/tag named '$REQUIRED_GIT_COMMITREF' in $PRODUCT. as required in $REQUIREMENTS_FILE." ; exit 1; }
    fi
    cd $TMPDIR/$PRODUCT && $INSTALLATION_CMD && cd -
fi
