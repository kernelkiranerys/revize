#!/usr/bin/env bash
# ── Reset the bank + re-ingest every book from the topic folders ─────────
# Run:  sudo bash ./reset-and-reingest.sh
#   - stops bot + watcher
#   - removes the week_1/ duplicate copies; makes the whole inbox user-owned
#   - renames Penstesting -> Pentesting
#   - wipes revize.db (re-inits empty), the converted .md, the watcher state
#   - copies the 17 originals into their topic folders
#   - starts the watcher (recursive, folder-as-topic) -> ~2.5h unattended batch
set -uo pipefail   # not -e: a missing source file shouldn't abort the whole batch

WATCH=./inbox
QDATA=./data
REVIZE=.
VENV="$REVIZE/.venv/bin/python"

echo "=== [1/8] stop bot + watcher ==="
systemctl stop revize-watcher 2>/dev/null || true
systemctl stop revize-bot      2>/dev/null || true

echo "=== [2/8] remove week_1/ duplicates + fix inbox ownership ==="
rm -rf "$WATCH/uni/web_engineering/week_1" 2>/dev/null || true
chown -R user:users "$WATCH"

echo "=== [3/8] rename Penstesting -> Pentesting ==="
[ -d "$WATCH/Penstesting" ] && mv "$WATCH/Penstesting" "$WATCH/Pentesting"

echo "=== [4/8] wipe DB + converted .md + watcher state ==="
rm -f "$REVIZE/revize.db" "$REVIZE/revize.db-wal" "$REVIZE/revize.db-shm"
rm -f "$QDATA"/*.md
rm -f ~/.revize-watcher/state.json

echo "=== [5/8] re-init DB (empty, valid schema, user-owned) ==="
sudo -u user "$VENV" -m src.db

echo "=== [6/8] copy the 17 originals into their topic folders ==="
copy() {  # copy <src> <dest-dir>
  if [ -f "$1" ]; then cp -n -- "$1" "$2/" && echo "  ok   $1"; else echo "  MISS $1"; fi
}
echo " -- Networking (4) --"
copy "./books/CompTIA_Network__Practice_Tests_7th_Craig_Zacker.epub"                 "$WATCH/Networking"
copy "./books/Jon Buhagiar - CompTIA Network+ Review Guide, Exam N10-007 , 4th Ed.epub" "$WATCH/Networking"
copy "./books/The Official CompTIA Network+ Student Guide 2019 Update (Exam N10-007).epub" "$WATCH/Networking"
copy "./inbox/done/zero-trust-networks-secure-2nd.pdf"                          "$WATCH/Networking"
echo " -- CPSA (7) --"
copy "./books/CompTIA CySA+ Study Guide Exam CS0-002 by Mike Chapple David Seidl.epub" "$WATCH/CPSA"
copy "./books/comptia-cysa-study-cs0-003-3rd.epub"                                       "$WATCH/CPSA"
copy "./books/CompTIA Cybersecurity Analyst (CSA+) Cert Guide.pdf"                      "$WATCH/CPSA"
copy "./books/IP Specialist - CompTIA Security+ All in One Complete Training Guide with Exam Practice Questions & Labs_ Exam SY0-501.epub" "$WATCH/CPSA"
copy "./books/Packt Publishing - CompTIA Security+ Certification Guide.pdf"            "$WATCH/CPSA"
copy "./books/CompTIA Security+ SY0-701 by Nikolaos Gorgotsias.pdf"                    "$WATCH/CPSA"
copy "./books/CompTIA Security+ Study Guide - Exam SY0-501 (7th Edition).pdf"         "$WATCH/CPSA"
echo " -- opnsense (2) --"
copy "./books/downloads/Julio Cesar Bueno de Camargo - OPNsense Beginner to Professional.epub" "$WATCH/opnsense"
copy "./books/downloads/Practical OPNsense_ Building Enterprise Firewalls With Open Source/Practical OPNsense_ Building Enterprise Firewalls With Open Source - Markus Stubbig.epub" "$WATCH/opnsense"
echo " -- Pentesting (4) --"
# McNab filename has a curly apostrophe — match via glob to avoid quoting hell
find ./books/downloads -maxdepth 1 -name 'Chris McNab-Network Security Assessment_*.epub' -exec cp -n -- {} "$WATCH/Pentesting/" \;
copy "./books/downloads/Nmap Network Scanning/Nmap Network Scanning.pdf" "$WATCH/Pentesting"
copy "./books/Practical.Malware.Analysis.epub"                          "$WATCH/Pentesting"
copy "./books/downloads/RTFM_ Red Team Field Manual v2 - Ben Clark & Nick Downer.epub" "$WATCH/Pentesting"
# copies were made as root -> make user-owned; tidy the old done/ copy of Zero Trust
chown -R user:users "$WATCH"
rm -f "$WATCH/done/zero-trust-networks-secure-2nd.pdf"

echo "=== [7/8] inbox now ==="
find "$WATCH" -maxdepth 3 -type f | sort

echo "=== [8/8] start watcher + bot (batch begins; ~2.5h, texts per book) ==="
systemctl start revize-watcher
systemctl start revize-bot
echo "DONE. Watch live:  sudo journalctl -u revize-watcher -f"
echo "Bank as it grows:  cd $REVIZE && .venv/bin/python -m src.stats"
