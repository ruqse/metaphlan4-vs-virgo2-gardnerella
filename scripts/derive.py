#!/usr/bin/env python3
"""Derive every table under data/ from the pinned upstream inputs listed in ref/inputs.tsv.

Usage: python3 scripts/derive.py --inputs DIR --out DIR [--ref DIR]

Standard library only (Python >= 3.8). Output is deterministic: rows are sorted and no
timestamps are written, so `reproduce.sh --check` can diff it against the committed data/.
"""
import argparse
import bz2
import gzip
import os
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, OrderedDict, defaultdict

MPA25 = "mpa_vJan25_CHOCOPhlAnSGB_202503"
MPA26 = "mpa_vJan26_CHOCOPhlAnSGB_202605"
VMGC_XLSX = "41564_2024_1751_MOESM4_ESM.xlsx"
GVMG_XLSX = "41588_2026_2639_MOESM4_ESM.xlsx"
GTDB_RELEASES = ("207", "220", "226")

# A label counts as a *named species* when it is a plain binomial (Genus_epithet).
# Placeholders such as Gardnerella_sp_KA00735, Bifidobacteriaceae_bacterium_WP022,
# Gardnerella_SGB33639 or Streptococcus_sp_group_B do not.
NAMED_RE = re.compile(r"^[A-Z][a-z]+_[a-z]+$")
UNNAMED_EPITHETS = {"sp", "bacterium"}

# The 17 vaginal taxa of the broad check. Each entry: display name, member species labels.
BROAD_TAXA = [
    ("Lactobacillus iners", ["Lactobacillus_iners"]),
    ("Lactobacillus jensenii", ["Lactobacillus_jensenii"]),
    ("Lactobacillus crispatus", ["Lactobacillus_crispatus"]),
    ("Lactobacillus gasseri", ["Lactobacillus_gasseri"]),
    ("Gardnerella (four species of Vaneechoutte et al. 2019)",
     ["Gardnerella_vaginalis", "Gardnerella_piotii", "Gardnerella_leopoldii", "Gardnerella_swidsinskii"]),
    ("Fannyhessea vaginae", ["Fannyhessea_vaginae"]),
    ("Prevotella bivia", ["Prevotella_bivia"]),
    ("Prevotella amnii", ["Prevotella_amnii"]),
    ("Prevotella disiens", ["Prevotella_disiens"]),
    ("Sneathia vaginalis (BVAB1)", ["Sneathia_vaginalis"]),
    ("Sneathia sanguinegens", ["Sneathia_sanguinegens"]),
    ("Megasphaera lornae", ["Megasphaera_lornae"]),
    ("Mobiluncus curtisii", ["Mobiluncus_curtisii"]),
    ("Mobiluncus mulieris", ["Mobiluncus_mulieris"]),
    ("Ureaplasma parvum", ["Ureaplasma_parvum"]),
    ("Ureaplasma urealyticum", ["Ureaplasma_urealyticum"]),
    ("Streptococcus agalactiae", ["Streptococcus_agalactiae"]),
]

# GTDB species tracked across releases: every Gardnerella-derived name that appears in the MetaPhlAn
# SGB2GTDB maps, in VIRGO2 or among the named species. GTDB has no subgenus, so the list is explicit.
GTDB_GARDNERELLA_RE = re.compile(
    r"^Bifidobacterium (vaginale(_[A-Z])?|piotii|leopoldii|swidsinskii|greenwoodii|"
    r"sp003585735|sp003585845|sp946891915|sp947292085)$")

LPSN_TO_GTDB_EPITHET = {"vaginalis": "vaginale"}


# ----------------------------------------------------------------------------- helpers
def is_named(label):
    if not NAMED_RE.match(label):
        return False
    return label.split("_", 1)[1] not in UNNAMED_EPITHETS


def sgb_key(sgb):
    return int(sgb[3:])


def write_tsv(path, comments, header, rows):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for c in comments:
            fh.write("# " + c + "\n" if c else "#\n")
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(x) for x in r) + "\n")


def read_ref_tsv(path):
    rows = []
    header = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if header is None:
                header = parts
            else:
                rows.append(dict(zip(header, parts)))
    return rows


# ----------------------------------------------------------------------------- MetaPhlAn
def read_species_index(path):
    """Return OrderedDict SGB -> list of species labels (s__ names), plus the raw lines in file order."""
    sgbs = OrderedDict()
    raw = []
    with bz2.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            sgb, clades = line.split("\t", 1)
            labels = [c.rsplit("|s__", 1)[1] for c in clades.split(",")]
            sgbs[sgb] = labels
            raw.append(line)
    return sgbs, raw


def read_printed_names(path, sgbs):
    """clade_name MetaPhlAn prints for each SGB: the s__ node directly above t__SGB in marker_info."""
    wanted = set(sgbs)
    pat = re.compile(r"s__([A-Za-z0-9_]+)\|t__(SGB\d+)\b")
    found = defaultdict(set)
    with bz2.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if "Gardnerella" not in line:
                continue
            for name, sgb in pat.findall(line):
                if sgb in wanted:
                    found[sgb].add(name)
    out = {}
    for sgb in sgbs:
        names = found.get(sgb, set())
        if len(names) != 1:
            sys.exit("expected exactly one printed name for %s, got %r" % (sgb, sorted(names)))
        out[sgb] = names.pop()
    return out


def read_sgb2gtdb(path):
    out = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) >= 2:
                out[parts[0]] = parts[1].rsplit(";s__", 1)[-1]
    return out


# ----------------------------------------------------------------------------- xlsx (stdlib)
# The workbooks are parsed only after reproduce.sh has verified their pinned SHA-256 (ref/inputs.tsv), so the
# XML content is fixed and known; stdlib ElementTree is used to keep the pipeline dependency-free.
_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_rows(path, sheet):
    """Yield (row_number, [cell values]) with cells placed at their true column positions."""
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.parse(z.open("xl/sharedStrings.xml")).getroot()
        shared = ["".join(t.text or "" for t in si.iter(_M + "t")) for si in root.findall(_M + "si")]
    wb = ET.parse(z.open("xl/workbook.xml")).getroot()
    rels = {r.get("Id"): r.get("Target") for r in ET.parse(z.open("xl/_rels/workbook.xml.rels")).getroot()}
    target = None
    for s in wb.find(_M + "sheets"):
        if s.get("name") == sheet:
            target = rels[s.get(_R + "id")]
    if target is None:
        sys.exit("sheet %r not found in %s" % (sheet, path))
    target = target.lstrip("/")
    if not target.startswith("xl/"):
        target = "xl/" + target
    for _, el in ET.iterparse(z.open(target)):
        if el.tag != _M + "row":
            continue
        vals = {}
        for c in el.findall(_M + "c"):
            i = _col_index(c.get("r"))
            t = c.get("t")
            if t == "inlineStr":
                is_ = c.find(_M + "is")
                vals[i] = "".join(x.text or "" for x in is_.iter(_M + "t")) if is_ is not None else ""
            else:
                v = c.find(_M + "v")
                if v is not None:
                    vals[i] = shared[int(v.text)] if t == "s" else v.text
        n = max(vals) + 1 if vals else 0
        yield int(el.get("r")), [vals.get(i, "").strip() for i in range(n)]
        el.clear()


def cell(row, i):
    return row[i] if i < len(row) else ""


def read_vmgc_s6(path):
    """VMGC Tab.S6: SGB, GTDB r214.1 species, FastANI reference, other references >=95% ANI."""
    out = []
    for r, row in xlsx_rows(path, "Tab.S6"):
        if r <= 4 or not cell(row, 0).startswith("SGB"):
            continue
        out.append({"sgb": cell(row, 0), "species": cell(row, 11),
                    "fastani_ref": cell(row, 3), "other_refs": cell(row, 4)})
    return out


def read_gvmg(path):
    """GVMG S7 (SGB -> GTDB R220 species) and S4 (genome -> SGB, Kraken profile-library flag)."""
    s7 = {}
    for r, row in xlsx_rows(path, "S7"):
        if r <= 3 or not cell(row, 0).startswith("SGB"):
            continue
        s7[cell(row, 0)] = cell(row, 16)
    genome_sgb, genome_lib, sgb_in_lib = {}, {}, defaultdict(bool)
    for r, row in xlsx_rows(path, "S4"):
        if r <= 2 or not cell(row, 22).startswith("SGB"):
            continue
        g, sgb, lib = cell(row, 0), cell(row, 22), cell(row, 24).lower() == "yes"
        genome_sgb[g] = sgb
        genome_lib[g] = lib
        sgb_in_lib[sgb] = sgb_in_lib[sgb] or lib
    # S20: ANI between each VMGC SGB representative and GVMG SGB representatives; keep the best hit per VMGC SGB.
    s20 = {}
    for r, row in xlsx_rows(path, "S20"):
        if r <= 2 or not cell(row, 5).startswith("SGB"):
            continue
        vmgc_sgb, gvmg_sgb, ani = cell(row, 5), cell(row, 2), float(cell(row, 6))
        if vmgc_sgb not in s20 or ani > s20[vmgc_sgb][1]:
            s20[vmgc_sgb] = (gvmg_sgb, ani)
    return s7, genome_sgb, genome_lib, sgb_in_lib, s20


# ----------------------------------------------------------------------------- GTDB
def read_gtdb(path):
    """genome accession (without RS_/GB_) -> GTDB species name."""
    out = {}
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            acc, tax = line.rstrip("\n").split("\t")
            out[acc[3:]] = tax.rsplit(";s__", 1)[1]
    return out


# ----------------------------------------------------------------------------- outputs
def out_grep(sp_raw, out):
    lines = [l for l in sp_raw if "gardnerella" in l.lower()]
    with open(os.path.join(out, "mpa_vJan25_Gardnerella_grep.txt"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def out_sgb_crosswalk(g25, g26, printed25, printed26, map220, map226, out):
    rows = []
    for sgb in sorted(set(g25) | set(g26), key=sgb_key):
        labels25 = g25.get(sgb, [])
        named = [l for l in labels25 if is_named(l)]
        other = [l for l in labels25 if not is_named(l)]
        rows.append([
            sgb,
            printed25.get(sgb, "absent"),
            printed26.get(sgb, "absent"),
            "; ".join(named) or "-",
            "; ".join(other) or "-",
            "yes" if g25.get(sgb) == g26.get(sgb) else "no",
            map220.get(sgb, "unmapped"),
            map226.get(sgb, "unmapped"),
        ])
    comments = [
        "MetaPhlAn 4 Gardnerella SGBs: what each prints, which genome labels it holds, and MetaPhlAn's own GTDB mapping.",
        "Sources (pinned in ref/inputs.tsv):",
        "  printed_clade_name_*   %s / %s marker_info.txt, the s__ node directly above t__<SGB>" % (MPA25, MPA26),
        "  *_labels_in_SGB         %s species.txt (all genome labels MetaPhlAn assigns to the SGB)" % MPA25,
        "  gtdb_r220 / gtdb_r226   MetaPhlAn utils/%s_SGB2GTDB_r220.tsv and %s_SGB2GTDB_r226.tsv" % (MPA25, MPA26),
        "                          (the tables MetaPhlAn's sgb_to_gtdb_profile.py uses)",
        "named = plain binomial label; placeholders (Genus_sp_*, *_bacterium_*, Genus_SGBnnnn) are listed as other labels.",
        "Labels are NCBI names attached to member genomes; legacy genomes deposited as 'G. vaginalis' predate the 2019+ species descriptions.",
        "GTDB alphabetic suffixes are release-specific placeholders; compare gtdb_r220 with gtdb_r226 (e.g. SGB17302).",
    ]
    header = ["SGB", "printed_clade_name_vJan25", "printed_clade_name_vJan26", "named_labels_in_SGB_vJan25",
              "other_labels_in_SGB_vJan25", "labels_identical_in_vJan26", "gtdb_r220_mpa_map", "gtdb_r226_mpa_map"]
    write_tsv(os.path.join(out, "mpa_Gardnerella_SGB_crosswalk.tsv"), comments, header, rows)


def out_broad_check(sgbs, out):
    by_label = defaultdict(list)
    for sgb, labels in sgbs.items():
        for l in set(labels):
            by_label[l].append(sgb)
    rows, tally = [], Counter()
    for display, members in BROAD_TAXA:
        member_sgbs = sorted({s for m in members for s in by_label.get(m, [])}, key=sgb_key)
        if not member_sgbs:
            sys.exit("no SGB found for %s" % display)
        split = any(len(by_label.get(m, [])) > 1 for m in members)
        named_in = sorted({l for s in member_sgbs for l in sgbs[s] if is_named(l)})
        others = sorted(set(named_in) - set(members))
        named_merge = any(len({l for l in sgbs[s] if is_named(l)}) > 1 for s in member_sgbs)
        unnamed = sum(1 for s in member_sgbs for l in sgbs[s] if not is_named(l))
        if split and named_merge:
            cat = "E"
        elif named_merge:
            cat = "C"
        elif split:
            cat = "D"
        elif unnamed:
            cat = "B"
        else:
            cat = "A"
        tally[cat] += 1
        rows.append([display, ", ".join(member_sgbs), "; ".join(others) or "-", unnamed,
                     "yes" if split else "no", "yes" if named_merge else "no", cat])
    n = len(rows)
    comments = [
        "Broad check: 17 commonly studied vaginal taxa vs the MetaPhlAn 4 %s species index (species.txt)." % MPA25,
        "split       = a member species is a label in more than one SGB",
        "named_merge = an SGB holding a member also holds a second named species (plain binomial label)",
        "category    A clean one-to-one | B one SGB shared only with unnamed placeholder labels | C named-species merge, one SGB",
        "            D split only (MetaPhlAn sums these SGBs under one s__ row, so the species row is not mixed)",
        "            E split and named-species merge",
        "Tally: A %d, B %d, C %d, D %d, E %d of %d. Named-species merges (C+E): %d of %d." % (
            tally["A"], tally["B"], tally["C"], tally["D"], tally["E"], n, tally["C"] + tally["E"], n),
    ]
    header = ["taxon", "SGBs", "other_named_species_in_SGBs", "unnamed_labels_in_SGBs", "split", "named_merge", "category"]
    write_tsv(os.path.join(out, "broad_check_vaginal_taxa.tsv"), comments, header, rows)
    return tally


def read_virgo2_counts(path):
    counts = Counter()
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        next(fh)
        for line in fh:
            parts = line.split("\t", 3)
            if len(parts) > 2 and "Gardnerella" in parts[2]:
                counts[parts[2]] += 1
    return counts


def out_virgo2(counts, out):
    rows = []
    for label, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        rows.append([label, n, "genus" if label == "Gardnerella" else "species"])
    comments = [
        "VIRGO2 Gardnerella taxon labels and the number of non-redundant genes carrying each (1.VIRGO2.taxon.txt, column Taxa).",
        "VIRGO2 assigned taxonomy with GTDB-Tk (GTDB release 207) and renamed Bifidobacterium back to Gardnerella (France et al. 2025, Methods).",
        "Suffixed labels (vaginalis_A ... _H) and spNNNNNNNNN labels are therefore GTDB species clusters, not sub-clades of G. vaginalis.",
        "France et al. 2025 describe these as 15 recognized Gardnerella species; the genus-only label 'Gardnerella' is the 16th label.",
    ]
    write_tsv(os.path.join(out, "VIRGO2_Gardnerella_labels.tsv"), comments, ["label", "n_genes", "level"], rows)


def out_named_species(types, g25, printed25, virgo2, gtdb, vmgc, gvmg, out):
    s7, genome_sgb, genome_lib, sgb_in_lib, s20 = gvmg
    by_label = defaultdict(list)
    for sgb, labels in g25.items():
        for l in set(labels):
            by_label[l].append(sgb)
    vmgc_by_sgb = {r["sgb"]: r for r in vmgc}
    rows = []
    for t in types:
        lpsn = t["lpsn_species"]
        epithet = lpsn.split()[1]
        gtdb_name = "Bifidobacterium " + LPSN_TO_GTDB_EPITHET.get(epithet, epithet)
        acc = t["type_genome"]
        strain_token = re.sub(r"[^A-Za-z0-9]+", "_", t["type_strain"]).strip("_")

        mpa_label = "Gardnerella_" + epithet
        mpa_sgbs = sorted(by_label.get(mpa_label, []), key=sgb_key)
        strain_sgbs = sorted({s for s, labels in g25.items() for l in labels
                              if strain_token and l.endswith("_" + strain_token)}, key=sgb_key)
        def fmt_sgbs(sgbs):
            return "; ".join("%s (printed %s)" % (s, printed25[s]) for s in sgbs) or "-"

        vmgc_labelled = sorted((r["sgb"] for r in vmgc if r["species"] == gtdb_name), key=sgb_key)
        vmgc_ref = sorted((r["sgb"] for r in vmgc if r["fastani_ref"] == acc), key=sgb_key)
        vmgc_other = sorted((r["sgb"] for r in vmgc if acc in re.split(r"[;,\s]+", r["other_refs"])), key=sgb_key)
        def fmt_vmgc(sgbs):
            return "; ".join("%s (%s)" % (s, vmgc_by_sgb[s]["species"].replace("Bifidobacterium ", "B. "))
                             for s in sgbs) or "-"

        vmgc_suffixed = [r["sgb"] for r in vmgc if re.match(re.escape(gtdb_name) + r"_[A-Z]$", r["species"])]
        gvmg_labelled = sorted((s for s, sp in s7.items() if sp == gtdb_name), key=sgb_key)
        gvmg_suffixed = [s for s, sp in s7.items() if re.match(re.escape(gtdb_name) + r"_[A-Z]$", sp)]
        gsgb = genome_sgb.get(acc)
        s20_hits = "; ".join("%s->%s %s (%.1f%% ANI)" % (v, s20[v][0], s7.get(s20[v][0], "?").replace("Bifidobacterium ", "B. "),
                                                        s20[v][1]) for v in vmgc_labelled if v in s20) or "-"

        rows.append([
            lpsn, t["authority"], acc,
            gtdb.get("207", {}).get(acc, "not in release"),
            gtdb.get("220", {}).get(acc, "not in release"),
            gtdb.get("226", {}).get(acc, "not in release"),
            fmt_sgbs(mpa_sgbs),
            fmt_sgbs(strain_sgbs) if strain_sgbs != mpa_sgbs else ("same" if strain_sgbs else "-"),
            virgo2.get(mpa_label, 0),
            len(vmgc_labelled),
            len(vmgc_suffixed),
            fmt_vmgc(vmgc_ref),
            fmt_vmgc(vmgc_other),
            len(gvmg_labelled),
            len(gvmg_suffixed),
            gsgb or "not in catalog",
            s7.get(gsgb, "-") if gsgb else "-",
            ("yes" if sgb_in_lib.get(gsgb) else "no") if gsgb else "-",
            s20_hits,
        ])
    comments = [
        "Each validly published Gardnerella species (LPSN, ref/gardnerella_type_genomes.tsv) traced through every reference via its type-strain genome.",
        "gtdb_r207/r220/r226         GTDB species of the type genome in each release (bac120_taxonomy_r*.tsv.gz)",
        "mpa_vJan25_SGBs_with_label  MetaPhlAn SGBs whose genome labels include Gardnerella_<epithet>, with the clade_name each prints",
        "mpa_vJan25_type_strain_SGBs SGBs holding a label that ends in the type-strain designation (e.g. Gardnerella_sp_Marseille_Q2328)",
        "virgo2_genes                genes labelled Gardnerella_<epithet> in VIRGO2 (0 = no VIRGO2 label of that name)",
        "vmgc_r214_SGBs_labelled     VMGC Tab.S6 SGBs whose GTDB r214.1 species is exactly B. <epithet> (vaginalis -> vaginale)",
        "*_SGBs_suffixed             SGBs labelled B. <epithet>_<letter>: separate GTDB species clusters with placeholder names",
        "vmgc_SGBs_type_is_fastani_ref / _other_ref_95ANI   VMGC Tab.S6 SGBs listing the type genome as FastANI reference / other reference at >=95% ANI",
        "gvmg_r220_SGBs_labelled     GVMG S7 SGBs whose GTDB R220 species is exactly B. <epithet>",
        "gvmg_SGB_of_type_genome     GVMG S4 SGB (95% ANI) that contains the type genome, its S7 label, and whether that SGB",
        "                            contributes genomes to the GVMG Kraken profile library (S4 'Profile library')",
        "vmgc_labelled_SGB_best_gvmg_match  best GVMG SGB match (and ANI) of each VMGC SGB labelled B. <epithet>, from GVMG S20",
    ]
    header = ["lpsn_species", "authority", "type_genome", "gtdb_r207", "gtdb_r220", "gtdb_r226",
              "mpa_vJan25_SGBs_with_label", "mpa_vJan25_type_strain_SGBs", "virgo2_genes",
              "vmgc_r214_SGBs_labelled", "vmgc_r214_SGBs_suffixed", "vmgc_SGBs_type_is_fastani_ref", "vmgc_SGBs_type_is_other_ref_95ANI",
              "gvmg_r220_SGBs_labelled", "gvmg_r220_SGBs_suffixed", "gvmg_SGB_of_type_genome", "gvmg_label_of_that_SGB", "gvmg_SGB_in_kraken_library",
              "vmgc_labelled_SGB_best_gvmg_match"]
    write_tsv(os.path.join(out, "gardnerella_named_species_crosswalk.tsv"), comments, header, rows)


def out_gtdb_letters(gtdb, vmgc, s7, virgo2, out):
    """Genome-level transitions of Gardnerella-derived GTDB species across releases, plus letters per catalog."""
    genomes = set()
    for rel in GTDB_RELEASES:
        genomes |= {g for g, sp in gtdb[rel].items() if GTDB_GARDNERELLA_RE.match(sp)}
    trans = Counter()
    for g in genomes:
        key = tuple(gtdb[rel].get(g, "not in release").replace("Bifidobacterium ", "B. ") for rel in GTDB_RELEASES)
        trans[key] += 1
    rows = [list(k) + [n] for k, n in sorted(trans.items(), key=lambda kv: (kv[0][1], kv[0][2], kv[0][0]))]

    def letters(names):
        ls = sorted({m.group(1) for n in names for m in [re.match(r".*vaginal[ie]s?_([A-Z])$", n)] if m})
        return " ".join(ls) or "-"
    comments = [
        "GTDB species of every genome GTDB assigns to a Gardnerella-derived species, in releases 207, 220 and 226 (bac120_taxonomy_r*.tsv.gz).",
        "One row per release-to-release path; n_genomes = genomes following that path. A suffix letter is a placeholder:",
        "GTDB states a suffix is kept between releases on a best-effort basis but 'this is not guaranteed'.",
        "B. vaginale_<letter> sets used by each catalog (letters alone do not identify the same cluster across GTDB releases):",
        "  VIRGO2 (GTDB r207)      %s" % letters(virgo2.keys()),
        "  VMGC   (GTDB r214.1)    %s" % letters(r["species"] for r in vmgc),
        "  GVMG   (GTDB R220)      %s" % letters(s7.values()),
    ]
    write_tsv(os.path.join(out, "gtdb_Gardnerella_species_by_release.tsv"), comments,
              ["gtdb_r207", "gtdb_r220", "gtdb_r226", "n_genomes"], rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--inputs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ref", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ref"))
    a = ap.parse_args()
    inp = lambda f: os.path.join(a.inputs, f)
    os.makedirs(a.out, exist_ok=True)

    g25, raw25 = read_species_index(inp(MPA25 + "_species.txt.bz2"))
    g26, _ = read_species_index(inp(MPA26 + "_species.txt.bz2"))
    gard25 = OrderedDict((s, l) for s, l in g25.items() if any("Gardnerella" in x for x in l))
    gard26 = OrderedDict((s, l) for s, l in g26.items() if any("Gardnerella" in x for x in l))
    printed25 = read_printed_names(inp(MPA25 + "_marker_info.txt.bz2"), gard25)
    printed26 = read_printed_names(inp(MPA26 + "_marker_info.txt.bz2"), gard26)
    map220 = read_sgb2gtdb(inp(MPA25 + "_SGB2GTDB_r220.tsv"))
    map226 = read_sgb2gtdb(inp(MPA26 + "_SGB2GTDB_r226.tsv"))
    virgo2 = read_virgo2_counts(inp("1.VIRGO2.taxon.txt.gz"))
    gtdb = {rel: read_gtdb(inp("bac120_taxonomy_r%s.tsv.gz" % rel)) for rel in GTDB_RELEASES}
    vmgc = read_vmgc_s6(inp(VMGC_XLSX))
    gvmg = read_gvmg(inp(GVMG_XLSX))
    types = read_ref_tsv(os.path.join(a.ref, "gardnerella_type_genomes.tsv"))

    out_grep(raw25, a.out)
    out_sgb_crosswalk(gard25, gard26, printed25, printed26, map220, map226, a.out)
    tally = out_broad_check(g25, a.out)
    out_virgo2(virgo2, a.out)
    out_named_species(types, gard25, printed25, virgo2, gtdb, vmgc, gvmg, a.out)
    out_gtdb_letters(gtdb, vmgc, gvmg[0], virgo2, a.out)

    print("MetaPhlAn vJan25 Gardnerella SGBs: %d (vJan26: %d)" % (len(gard25), len(gard26)))
    print("VIRGO2 Gardnerella labels: %d" % len(virgo2))
    print("Broad check categories: %s" % ", ".join("%s=%d" % (k, tally[k]) for k in "ABCDE"))


if __name__ == "__main__":
    main()
