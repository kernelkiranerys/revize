#!/usr/bin/env bash
# ── Install + wire + start the revize book-watcher ─────────────────────
# Idempotent. Run:  bash ./setup-watcher.sh
set -euo pipefail
REVIZE=.
FLAKE=/etc/nixos/flake.nix

echo "════════ [1/3] place watcher.nix + wire into the flake ════════"
sudo cp "$REVIZE/nix-watcher.nix" /etc/nixos/watcher.nix
sudo python3 - <<'PY'
p = "/etc/nixos/flake.nix"; s = open(p).read()
if "./watcher.nix" in s:
    print("  ./watcher.nix already listed in flake.nix")
else:
    if "./revize.nix" in s:
        s = s.replace("./revize.nix", "./revize.nix\n        ./watcher.nix")
    elif "./ollama.nix" in s:
        s = s.replace("./ollama.nix", "./ollama.nix\n        ./watcher.nix")
    else:
        s = s.replace("./libvirt.nix", "./libvirt.nix\n        ./watcher.nix")
    open(p, "w").write(s)
    print("  added ./watcher.nix to flake.nix modules list")
PY

echo "════════ [2/3] nixos-rebuild switch ════════"
sudo nixos-rebuild switch --flake "/etc/nixos#nixos"

echo "════════ [3/3] enable + start revize-watcher ════════"
mkdir -p ./inbox
sudo systemctl enable --now revize-watcher
echo "--- status ---"
sudo systemctl status revize-watcher --no-pager 2>&1 | head -10 || true
echo
echo "Done. Drop a book into ./inbox/ — it will be ingested"
echo "end-to-end (convert → chunk+embed → 50 MCQs → inserted), and you'll get"
echo "a SimpleX text when it finishes. Watch live:"
echo "  sudo journalctl -u revize-watcher -f"
