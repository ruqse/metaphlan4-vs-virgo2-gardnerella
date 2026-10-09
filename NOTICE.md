# Notice

This repository contains original analysis by Faruk Dube comparing how
MetaPhlAn 4, VIRGO2, VMGC and GVMG represent named *Gardnerella* species.

Licensing scope:

- Code and scripts, including `reproduce.sh`, are licensed under the MIT
  License. See `LICENSE`.
- Original written analysis, figures, diagrams, and report content are licensed
  under CC BY 4.0. See `LICENSE-CONTENT.md`.
- Small committed files under `data/` are reproducibility outputs derived from
  the upstream files listed below (pinned with checksums in `ref/inputs.tsv`).
  They are included to document the exact database-content checks used in the
  analysis. Upstream database and software terms still apply to those source
  materials.

Upstream sources used by the reproducibility workflow:

- MetaPhlAn 4 vJan25 and vJan26 CHOCOPhlAnSGB database files (species index,
  marker info) distributed by the bioBakery/MetaPhlAn project, and the
  SGB-to-GTDB mapping tables from the MetaPhlAn repository (`metaphlan/utils`).
- VIRGO2 taxonomic annotation table distributed by the Ravel Lab VIRGO2
  project.
- GTDB bacterial taxonomy files for releases 207, 220 and 226 (Genome Taxonomy
  Database, CC BY-SA 4.0).
- VMGC Supplementary Table S6 (GTDB r214.1 species roster), from Huang et al.
  2024, *Nature Microbiology*, DOI 10.1038/s41564-024-01751-5.
- GVMG Supplementary Tables S4 (genome roster), S7 (GTDB R220 species roster)
  and S20 (VMGC-to-GVMG ANI), from Jie et al. 2026, *Nature Genetics*,
  DOI 10.1038/s41588-026-02639-2.
- Type-strain genome accessions in `ref/gardnerella_type_genomes.tsv`, curated
  from NCBI Datasets and LPSN.

Only Gardnerella-related rows are extracted from these sources.

The repository's licenses apply only to material that Faruk Dube has the right
to license. They do not imply endorsement by MetaPhlAn, bioBakery, VIRGO2, the
Ravel Lab, GTDB, or any cited publication authors.
