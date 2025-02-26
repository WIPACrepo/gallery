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

  * GET  - Search page
  * POST - Form submit for search

/_src/<path>

  * GET  - Read-only media handled by nginx

/<path>

  * GET  - Formatted album page, or redirect to src for media
