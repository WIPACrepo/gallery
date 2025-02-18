# Gallery
Internal Media Gallery

## URL Structure

/edit/<album_path>

  * GET  - Editable page for album contents/metadata
  * POST - Form submit for changes to an album

/edit/<album_path>/<media>

  * GET  - Editable page for media metadata
  * POST - Form submit for changes to a media file

/edit/_upload

  * POST - Form submit for uploading media to an album

/search

  * GET  - search page
  * POST - Form submit for search

/*

  * GET  - read-only albums/media handled by nginx
