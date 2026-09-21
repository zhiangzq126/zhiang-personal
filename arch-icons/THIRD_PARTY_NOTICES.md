# Third-party notices

## Scope

The MIT license in this project applies to original software and documentation, not to third-party artwork, logos, trademarks, source libraries, or embedded copies of that material. File format conversion, normalization and content-based deduplication do not change the original rights or imply vendor endorsement.

Each catalog variant records source file paths, original entry names and original SHA-256 values in `origins`; `catalog/sources.json` records checksums of archived source files. Those records document provenance, not a blanket grant of redistribution rights.

## DrawIO-derived AWS material

The local collection was extracted from draw.io 22.1.2. Upstream: https://github.com/jgraph/drawio and https://www.drawio.com/ . Provider/product names and trademarks are associated with their respective owners, including Amazon Web Services.

The archived package includes:

- DrawIO code license: [Apache License 2.0](sources/aws/drawio-22.1.2/source/DRAWIO-CODE-LICENSE).
- Stencil license: [Creative Commons Attribution 4.0](sources/aws/drawio-22.1.2/source/stencils/LICENSE), also available at https://creativecommons.org/licenses/by/4.0/ .

Converted icons preserve attribution to their upstream sources. Changes include conversion of stencil geometry to standalone SVG, application of sidebar palettes and tile backgrounds, SVG normalization, internal-ID rewriting and hash-based storage. No AWS endorsement, current-version certification or additional trademark permission is claimed.

## Other supplied icon packs

The local collection also contains user-supplied Alibaba Cloud, Tencent Cloud, Huawei Cloud and component icon packs. Their provider names identify provenance and do not constitute a MIT license grant. Applicable asset terms must be established separately from this project's code license. The maintainer has confirmed that the supplied materials may be publicly redistributed. This confirmation does not relicense third-party artwork under MIT or grant additional trademark rights. The public scope is recorded in [catalog/release-manifest.json](catalog/release-manifest.json).
