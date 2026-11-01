# ── revize book-watcher systemd service ─────────────────────────────────
# Watches ./inbox; hands settled new ebooks to ai-agent for
# end-to-end ingestion (convert → chunk+embed → author 50 MCQs → insert into
# revize.db), then texts your phone via the ai-agent bridge outbox.
# Install:  bash ./setup-watcher.sh
{ config, pkgs, lib, ... }:
let proj = "."; in {
  systemd.services.revize-watcher = {
    description = "revize book-watcher (inbox -> ai-agent ingest)";
    after = [ "network-online.target" "ollama.service" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];      # auto-start at boot
    environment = { PYTHONUNBUFFERED = "1"; HOME = "~"; };
    # nix: for `nix shell nixpkgs#pandoc`/`poppler-utils` inside convert-book.sh
    # procps: pkill (if ever needed). ai-agent is resolved absolutely in watcher.py.
    path = [ pkgs.nix pkgs.procps ];
    serviceConfig = {
      User = "user";
      Group = "users";
      WorkingDirectory = proj;
      ExecStart = "${proj}/.venv/bin/python -m src.watcher";
      Restart = "on-failure";
      RestartSec = "10";
    };
  };
}
