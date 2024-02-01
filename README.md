# Gallery
Internal Media Gallery

## URL Structure

/edit/<album_path>

  * GET  - Editable page for album contents/metadata
  * POST - Form submit for changes to an album

/edit/<album_path>/<image>

  * GET  - Editable page for image metadata
  * POST - Form submit for changes to an image
  
/edit/<album_path>/_upload

  * GET  - Page to upload images to an album
  * POST - Form submit for uploading images to an album

/search

  * GET  - search page
  * POST - Form submit for search

/*  - read-only albums/images handled by nginx
