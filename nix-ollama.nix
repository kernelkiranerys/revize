# ── Ollama for revize (CUDA on Quadro RTX 4000) ─────────────────────────
# nixos-26.05 module API: services.ollama.acceleration is gone;
# use services.ollama.package = pkgs.ollama-cuda instead.
#
# This file is installed + wired into flake.nix by:
#   bash ./setup-ollama-and-embed.sh
# (which also runs nixos-rebuild switch --flake /etc/nixos#nixos and pulls models)
# Models land in /var/lib/ollama (root fs, ~209 GB free — plenty).
{ config, pkgs, ... }:
{
  services.ollama = {
    enable = true;
    package = pkgs.ollama-cuda;      # Quadro RTX 4000, NVIDIA driver already configured
    # host/port default to 127.0.0.1:11434 — exactly what revize's config.py uses
  };
}
