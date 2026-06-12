# Notice

This repository contains original analysis by Faruk Dube comparing how
MetaPhlAn 4 vJan25 and VIRGO2 represent named *Gardnerella* species.

Licensing scope:

- Code and scripts, including `reproduce.sh`, are licensed under the MIT
  License. See `LICENSE`.
- Original written analysis, figures, diagrams, and report content are licensed
  under CC BY 4.0. See `LICENSE-CONTENT.md`.
- Small committed files under `data/` are reproducibility outputs derived from
  upstream MetaPhlAn 4 and VIRGO2 catalog files. They are included to document
  the exact database-content checks used in the analysis. Upstream database and
  software terms still apply to those source materials.

Upstream sources used by the reproducibility workflow:

- MetaPhlAn 4 vJan25 CHOCOPhlAnSGB database files distributed by the
  bioBakery/MetaPhlAn project.
- VIRGO2 taxonomic annotation table distributed by the Ravel Lab VIRGO2
  project.
- VMGC Supplementary Table S6 (GTDB r214.1 species roster), from Huang et al.
  2024, *Nature Microbiology*, DOI 10.1038/s41564-024-01751-5. Used only to read
  the ex-Gardnerella (GTDB *Bifidobacterium*) species counts in
  `data/gardnerella_gtdb_catalogs.tsv`.
- GVMG Supplementary Table S7 (GTDB R220 species roster), from Jie et al. 2026,
  *Nature Genetics*, DOI 10.1038/s41588-026-02639-2. Used only to read the
  ex-Gardnerella species counts in `data/gardnerella_gtdb_catalogs.tsv`.

The repository's licenses apply only to material that Faruk Dube has the right
to license. They do not imply endorsement by MetaPhlAn, bioBakery, VIRGO2, the
Ravel Lab, or any cited publication authors.
