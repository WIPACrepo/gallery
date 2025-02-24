# CHANGELOG


## v0.0.6 (2025-02-24)

### R

- Really delete things from the cache when they change
  ([#16](https://github.com/WIPACrepo/gallery/pull/16),
  [`6445506`](https://github.com/WIPACrepo/gallery/commit/64455065a160574e93aa4da6f4a959b18a7be2b2))


## v0.0.5 (2025-02-24)

### F

- Fix deleting items ([#15](https://github.com/WIPACrepo/gallery/pull/15),
  [`bb56e86`](https://github.com/WIPACrepo/gallery/commit/bb56e86ccc02b2f7200b92fe03e80985bad39c12))

* fix deleting items

* remove excess try/except


## v0.0.4 (2025-02-21)

### F

- Fix media redirect ([#14](https://github.com/WIPACrepo/gallery/pull/14),
  [`55afd50`](https://github.com/WIPACrepo/gallery/commit/55afd50e015c57ae999b9a8daf096b3f84883df8))


## v0.0.3 (2025-02-21)

### A

- Automatic thumbnails when uploading ([#13](https://github.com/WIPACrepo/gallery/pull/13),
  [`263871e`](https://github.com/WIPACrepo/gallery/commit/263871ea5400c0ecd8711f27619329135787b3ff))

* automatically make a thumbnail when an image is uploaded * if uploading a custom thumbnail, make
  sure it's resized and auto-rotated from exif * make search faster by removing the photoswipe hash
  lookup, replacing with image hashes in the album page


## v0.0.2 (2025-02-20)

### W

- We need the async version of elasticsearch
  ([`6025f31`](https://github.com/WIPACrepo/gallery/commit/6025f317ce06a91c13931d9f33a16d14435c4ac3))


## v0.0.1 (2025-02-19)

### 

- Initial commit
  ([`52e9305`](https://github.com/WIPACrepo/gallery/commit/52e9305dde210fb2a39017cb8034d741dbc1df35))

- Merge pull request #11 from WIPACrepo/make-editor
  ([`fbddb53`](https://github.com/WIPACrepo/gallery/commit/fbddb53e2f846e2c04e4d015f60d663f26ff1de4))

web editor

- Merge pull request #12 from WIPACrepo/better-editing
  ([`101a9d1`](https://github.com/WIPACrepo/gallery/commit/101a9d1e67728995639d0d218ad210e5bb5eb490))

add thumbnail editing and deleting albums

### A

- A few upgrades and fixes for new conversion
  ([`e761977`](https://github.com/WIPACrepo/gallery/commit/e761977eedb53080ef9fccb525b7b4bef4e47911))

- Add dockerfile
  ([`a309a88`](https://github.com/WIPACrepo/gallery/commit/a309a883d3c7a057415f170209c60e6c4d9f6db7))

- Add ES indexing
  ([`629b456`](https://github.com/WIPACrepo/gallery/commit/629b456cc3533230f90ad5850abbd20aa50be201))

- Add ffmpeg to container
  ([`1d013f4`](https://github.com/WIPACrepo/gallery/commit/1d013f4411490951696c60b7de6279b1e692151a))

- Add fonts to container
  ([`6671c5c`](https://github.com/WIPACrepo/gallery/commit/6671c5c8b14844f890419de00fb3f5ac5a7e28e5))

- Add non-media files. copy thumbnails for gifs and videos. closes #6
  ([`c7a33f3`](https://github.com/WIPACrepo/gallery/commit/c7a33f3ace238831cac8bc12eb717fea30eec36c))

- Add thumbnail editing and deleting albums
  ([`fb15ab7`](https://github.com/WIPACrepo/gallery/commit/fb15ab7991e84bd662ddc2ee431a379936f348c6))

- Album urls should end in /
  ([`63fda43`](https://github.com/WIPACrepo/gallery/commit/63fda43a2560cc1053680dc5393ec278feb21cf1))

- Allow build process to take dynamic src and build dirs
  ([`4d88d70`](https://github.com/WIPACrepo/gallery/commit/4d88d70658497b6773f1fdacfd3d7b3d50be56c4))

- Assume building in the correct env
  ([`a7280f6`](https://github.com/WIPACrepo/gallery/commit/a7280f6735810a3b7c5e87ef5623e12f1cffb295))

- Auto-orientation on conversion, and ignore a few more files
  ([`c544c62`](https://github.com/WIPACrepo/gallery/commit/c544c62d4f8b5c100b8a484beb466777c8061e14))

### B

- Basic prototype done
  ([`63a34b1`](https://github.com/WIPACrepo/gallery/commit/63a34b1c998ba3c72ca0e58d4d9aa5e91534a84e))

### D

- Do not modify .md files if they already exist
  ([`f5b5bc6`](https://github.com/WIPACrepo/gallery/commit/f5b5bc6fc35a5f0d8c80b0b629fbb98115c7617d))

- Docker image fixups. add tests
  ([`dffd34a`](https://github.com/WIPACrepo/gallery/commit/dffd34aebd354413d6a987116624fba3042e670e))

### F

- First commit for editor, with lots of py project things
  ([`b9f1718`](https://github.com/WIPACrepo/gallery/commit/b9f1718fd067faea629d067f2e872a89aef24e81))

- First pass at getting data out of the gallery DB. basic functions are there, but need to be strung
  together
  ([`6e595cc`](https://github.com/WIPACrepo/gallery/commit/6e595cc5da7285b7d0813ccf29fa734e3643d2b5))

- Fix docker build
  ([`d6a2871`](https://github.com/WIPACrepo/gallery/commit/d6a287107c369cedb66ab8a8c600132b1f930478))

- Fix dockerfile name
  ([`3ec0c9e`](https://github.com/WIPACrepo/gallery/commit/3ec0c9e7caf4c9e4c828d4847a53d634e8903dac))

- Fix hosts param
  ([`cd09987`](https://github.com/WIPACrepo/gallery/commit/cd099872e6b33179e9c16a4e3184b7ae42dbb921))

- Fix ruff and docker
  ([`6ca7d8b`](https://github.com/WIPACrepo/gallery/commit/6ca7d8b56cc429b74e1d78c0c5e4b11239a69a43))

### G

- Get video downloads working, and also build in support for previewing smaller images than the
  original. minify the js files at build time.
  ([`6c1887a`](https://github.com/WIPACrepo/gallery/commit/6c1887ab1d74b80fab60d2a542686b3e1b1b0256))

### I

- Integrate search into theme. improve mobile support
  ([`9fadd5e`](https://github.com/WIPACrepo/gallery/commit/9fadd5e67189268a2e9e74fbb3999d5c93ad6784))

### M

- Move everything into python server, and remove sigal
  ([`40d77c0`](https://github.com/WIPACrepo/gallery/commit/40d77c0cc5621a68641ff5c1b9a08e3bcd801b87))

- Move two files ruff is checking
  ([`3cdd7a4`](https://github.com/WIPACrepo/gallery/commit/3cdd7a43edc669281021470a2d4e3ba43fce3974))

### N

- New ES requres args to be kwargs
  ([`70a61ed`](https://github.com/WIPACrepo/gallery/commit/70a61ed562f27b1ea7992ad0134c759db7c118d2))

- New upload and search page
  ([`7f1ae89`](https://github.com/WIPACrepo/gallery/commit/7f1ae896d56fb4c89e549d867b09383d7e0d454d))

### P

- Pass args on to sigal
  ([`e974791`](https://github.com/WIPACrepo/gallery/commit/e97479114753313448fd4b0c55966cdb96f52ba3))

### R

- Remove setup action and switch to ruff
  ([`d5d7609`](https://github.com/WIPACrepo/gallery/commit/d5d760943fd48df57ca683645990d810e8585d29))

### S

- Stylized font for page title
  ([`d5e4ee3`](https://github.com/WIPACrepo/gallery/commit/d5e4ee325c7c496b0eca8a2cad783c455181841b))

- Switch to sigal branch to test speedup
  ([`9313089`](https://github.com/WIPACrepo/gallery/commit/9313089de16f889f34a7d803284280edeeea0f28))

### T

- Try better git url
  ([`ee0d4c6`](https://github.com/WIPACrepo/gallery/commit/ee0d4c68b969525246c76725d583501526de6fc0))

- Try making new releases better
  ([`71ff753`](https://github.com/WIPACrepo/gallery/commit/71ff753690e3b03fcdcaffd64122930ac3d74f63))

- Try switching to cached version of sigal
  ([`bd42f2d`](https://github.com/WIPACrepo/gallery/commit/bd42f2df8f1170e5d03663337ad8aeaa03b5f210))

### U

- Use devel version of sigal
  ([`b237e35`](https://github.com/WIPACrepo/gallery/commit/b237e354485212b75a74b0545f04d53b297cb95e))

- Use full scheme and kwargs for search ES
  ([`f4d43ed`](https://github.com/WIPACrepo/gallery/commit/f4d43edf227539774b845ff055b16a7bb3b3ba05))
