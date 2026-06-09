#!/usr/bin/env bash
# Reproduce the MetaPhlAn 4 vs VIRGO2 Gardnerella database-content comparison.
# Downloads ~85 MB total, runs in about 1 minute, and prints the three results.
# Verified outputs are committed under data/ for offline checking.
set -euo pipefail
cd "$(dirname "$0")"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT; cd "$work"

base="http://cmprod1.cibio.unitn.it/biobakery4/metaphlan_databases"

echo "== 1) MetaPhlAn 4 vJan25: Gardnerella SGBs (species index, ~1 MB) =="
curl -s -o sp.bz2 "$base/mpa_vJan25_CHOCOPhlAnSGB_202503_species.txt.bz2"
bunzip2 sp.bz2
echo "Gardnerella SGB lines: $(grep -ic Gardnerella sp)  (expected: 12)"

echo "== 1b) Broad check: 17 canonical vaginal taxa (same species index; backs data/broad_check_vaginal_taxa.tsv) =="
grep -iP 's__Lactobacillus_(crispatus|iners|jensenii|gasseri|paragasseri)\b' sp || true
grep -iE 'g__Gardnerella' sp || true
grep -i  'Fannyhessea' sp || true
grep -iP 's__Prevotella_(bivia|amnii|disiens)\b' sp || true
grep -i  'Sneathia' sp || true
grep -iE 's__Megasphaera_lornae' sp || true
grep -i  'Mobiluncus' sp || true
grep -iE 's__Ureaplasma_(urealyticum|parvum)' sp || true
grep -iE 's__Streptococcus_agalactiae' sp || true

echo "== 2) clade_name MetaPhlAn prints per SGB (marker DB, 70 MB) =="
curl -s -o mi.txt.bz2 "$base/mpa_vJan25_CHOCOPhlAnSGB_202503_marker_info.txt.bz2"
bzcat mi.txt.bz2 \
  | grep -oE "s__[A-Za-z0-9_]+\|t__SGB(17301|17302|17305|17306|17307|17308|17309|17310|21500|33639|152030|152034)\b" \
  | sort -u

echo "== 3) VIRGO2: Gardnerella labels =="
curl -sL -o virgo2.txt.gz "https://media.githubusercontent.com/media/ravel-lab/VIRGO2/main/AnnotationTables/1.VIRGO2.taxon.txt.gz"
# use gzip -dc, not zcat: macOS/BSD zcat expects a .Z file and fails on .gz
gzip -dc virgo2.txt.gz | awk -F'\t' '$3 ~ /Gardnerella/ {print $3}' | sort | uniq -c | sort -rn
echo "VIRGO2 Gardnerella labels: $(gzip -dc virgo2.txt.gz | awk -F'\t' '$3 ~ /Gardnerella/ {print $3}' | sort -u | wc -l | tr -d ' ')  (expected: 16)"
