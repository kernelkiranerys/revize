# ── revize QuizBot systemd service ─────────────────────────────────────
# Apply after ollama + after the one-time QR setup:
#   sudo cp ./nix-revize.nix /etc/nixos/revize.nix
#   # add  ./revize.nix  to imports in /etc/nixos/configuration.nix
#   sudo nixos-rebuild switch
#   sudo systemctl enable --now revize-bot
# Logs:  sudo journalctl -u revize-bot -f
{ config, pkgs, lib, ... }:
let
  proj = ".";
in {
  systemd.services.revize-bot = {
    description = "revize spaced-revision QuizBot (SimpleX)";
    after = [ "network-online.target" "ollama.service" ];
    wants = [ "network-online.target" ];
    wantedBy = [ "multi-user.target" ];   # auto-start at boot + survive reboot
    environment = {
      PYTHONUNBUFFERED = "1";
      HOME = "~";
    };
    path = [ pkgs.procps ];   # pkill
    serviceConfig = {
      User = "user";
      Group = "users";
      WorkingDirectory = proj;
      ExecStart = "${proj}/.venv/bin/python -m src.bot";
      Restart = "on-failure";
      RestartSec = "5";
    };
  };
}
