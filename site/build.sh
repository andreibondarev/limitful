#!/bin/sh
# Assemble the website into _site/: the pages in site/ plus the video, poster and
# logos that live elsewhere in the repo, so nothing is kept twice.
#   sh site/build.sh && open _site/index.html
set -e
cd "$(dirname "$0")/.."
rm -rf _site
mkdir -p _site
cp -R site/index.html site/img site/fonts _site/
cp assets/wordmark.svg assets/wordmark-dark.svg _site/
cp assets/logo.svg _site/favicon.svg
cp assets/promo/limitful-promo.mp4 assets/promo/poster.jpg _site/
cp assets/promo/limitless-mark.svg assets/promo/limitless-pendant.webp _site/img/
printf 'limitful.ai\n' > _site/CNAME
printf 'User-agent: *\nAllow: /\n' > _site/robots.txt
echo "Built _site/"
