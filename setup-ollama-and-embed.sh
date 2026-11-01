#!/usr/bin/env bash
# ── Steps 1 & 2: install Ollama (CUDA) + embed the 16 textbooks ─────────
# Run this from your terminal:  bash ./setup-ollama-and-embed.sh
# It will prompt for your sudo password (for the nixos-rebuild parts).
set -euo pipefail

REVIZE=.
FLAKE=/etc/nixos/flake.nix
HOST=nixos          # the flake attribute (nixosConfigurations.nixos)

echo "════════ [1/4] place ollama.nix + wire it into the flake ════════"
sudo cp "$REVIZE/nix-ollama.nix" /etc/nixos/ollama.nix
sudo python3 - <<'PY'
p = "/etc/nixos/flake.nix"
s = open(p).read()
if "./ollama.nix" in s:
    print("  ./ollama.nix already listed in flake.nix")
else:
    s = s.replace("./libvirt.nix", "./libvirt.nix\n        ./ollama.nix")
    open(p, "w").write(s)
    print("  added ./ollama.nix to flake.nix modules list")
PY

echo "════════ [2/4] nixos-rebuild switch  ════════"
echo "  NOTE: first rebuild compiles ollama from source + fetches ~314 MiB of"
echo "  CUDA blobs from NVIDIA. Expect ~10-20 min. Do not interrupt."
sudo nixos-rebuild switch --flake "/etc/nixos#$HOST"

echo "════════ [3/4] wait for ollama, then pull models ════════"
for i in $(seq 1 60); do
  if systemctl is-active --quiet ollama; then echo "  ollama service: active"; break; fi
  sleep 2
done
systemctl is-active --quiet ollama || { echo "  ollama not active — check: sudo journalctl -u ollama -n 50"; exit 1; }

# the nixos ollama module adds the CLI to environment.systemPackages; use the
# active system profile's binary directly (bulletproof, no PATH/hash issues)
hash -r 2>/dev/null || true
if [ -x /run/current-system/sw/bin/ollama ]; then
  OCMD=(/run/current-system/sw/bin/ollama)
elif command -v ollama >/dev/null 2>&1; then
  OCMD=(ollama)
else
  echo "  ollama CLI not found after rebuild (module should have installed it)"; exit 1
fi
export OLLAMA_HOST=127.0.0.1:11434

echo "  pulling qwen2.5:7b-instruct-q4_K_M  (~4.4 GB, please wait)..."
"${OCMD[@]}" pull qwen2.5:7b-instruct-q4_K_M
echo "  pulling nomic-embed-text  (~0.27 GB)..."
"${OCMD[@]}" pull nomic-embed-text
echo "  --- models installed ---"
"${OCMD[@]}" list

echo "════════ [4/4] chunk + embed the 16 markdown books into revize.db ════════"
cd "$REVIZE"
"$REVIZE/.venv/bin/python" -m src.chunker

echo ""
echo "════════ DONE. Next steps: ════════"
echo "  3) bash $REVIZE/setup-quizbot.sh   (one-time: /c, scan QR on phone, /q)"
echo "  4) add ./revize.nix to flake.nix too, then: sudo nixos-rebuild switch --flake /etc/nixos#nixos"
echo "     sudo systemctl enable --now revize-bot"
