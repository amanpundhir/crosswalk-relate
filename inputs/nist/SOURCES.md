# NIST data sources

All files below were authored by the National Institute of Standards and
Technology (NIST), a US government agency. In the United States they are not
subject to copyright (17 U.S.C. 105). NIST notes that foreign copyright may
apply to some NIST data. The OSCAL repository additionally waives copyright
worldwide under CC0 1.0. NIST asks users to acknowledge NIST as the source.
Source: National Institute of Standards and Technology, https://www.nist.gov.
NIST does not endorse this project. Content may differ from the official
publications; refer to the originals for authoritative text.

The files are stored unmodified in `raw/`. The three OSCAL catalogs and the MODERATE baseline profile were
fetched with raw URLs pinned to the commit below, not to the moving `main`
branch.

| File | Origin | Retrieved | Commit / version |
|---|---|---|---|
| NIST_SP-800-53_rev5_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/SP800-53/rev5/json) | 2026-11-22 | f0de6d8d8c059d374f15e0ae07508d82e370fc1d (committed 2026-10-22); catalog `metadata.version` 5.2.0 |
| NIST_SP800-171_rev3_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/SP800-171/rev3/json) | 2026-11-22 | f0de6d8d8c059d374f15e0ae07508d82e370fc1d; catalog `metadata.version` 1.1.0 |
| NIST_CSF_v2.0_catalog.json | https://github.com/usnistgov/oscal-content (nist.gov/CSF/v2.0/json) | 2026-11-22 | f0de6d8d8c059d374f15e0ae07508d82e370fc1d; catalog `metadata.version` 1.2.1 |
| NIST_SP-800-53_rev5_MODERATE-baseline_profile.json | https://github.com/usnistgov/oscal-content (nist.gov/SP800-53/rev5/json) | 2026-11-22 | f0de6d8d8c059d374f15e0ae07508d82e370fc1d; profile `metadata.version` 5.2.0; 287 control ids, all active in the catalog |
| csf2.xlsx (CSF 2.0 informative references) | https://csrc.nist.gov/extensions/nudp/services/json/csf/download?olirids=all | 2026-11-22 | n/a (the workbook states "Generated Date 2026-11-22 07:55:08", Change Log "Final") |
| sp800-171r3-cui-overlay.xlsx | https://csrc.nist.gov/files/pubs/sp/800/171/r3/final/docs/sp800-171r3-cui-overlay.xlsx | 2026-11-22 | n/a |

Raw URL pattern for the OSCAL files:
`https://raw.githubusercontent.com/usnistgov/oscal-content/f0de6d8d8c059d374f15e0ae07508d82e370fc1d/nist.gov/<path>`

## Integrity (SHA-256 and size of the files in `raw/`)

| File | Bytes | SHA-256 |
|---|---|---|
| NIST_SP-800-53_rev5_catalog.json | 10,448,237 | 64ca6b4161de51ab6af098a7d101d326f14c95e1abf721396cd8a049e8115eeb |
| NIST_SP800-171_rev3_catalog.json | 905,717 | fd68bad4c1fee98dd1b2511884b585fb1f14265d4c5693d0492a25dd66e73dde |
| NIST_CSF_v2.0_catalog.json | 341,930 | 0ac12904a4bcd877ec91be8e7ddc27278c88b0088c7db77d60ee24918e2563e2 |
| NIST_SP-800-53_rev5_MODERATE-baseline_profile.json | 10,498 | e3a0f11237cfaac24dfcf1586e07683f17423757fd84208deb33196b12e8f590 |
| csf2.xlsx | 146,546 | 59fa91abb7e7700e465bec1b14392bf15f9872803a9cd62c4341cb8392c41fc9 |
| sp800-171r3-cui-overlay.xlsx | 121,361 | c69914ac7d364b3ec6b661474102389072b5a293bc2dca156433dedd2d1e6da7 |

## Licence and copyright references

Licence of oscal-content: https://github.com/usnistgov/oscal-content/blob/main/LICENSE.md
NIST copyright statement: https://www.nist.gov/open/copyright-fair-use-and-licensing-statements-srd-data-software-and-technical-series-publications

The two xlsx files carry no licence text of their own; they are NIST-authored
publications covered by the NIST position above. The csf2.xlsx export also lists
third-party framework ids (ISO/IEC 27001, PCI DSS, CIS, CCM and others) in its
"Informative References" column. Crosswalk uses only the NIST rows from that
column (SP 800-53, SP 800-171, CSF) and does not copy third-party text.
