#!/usr/bin/env bash
# ── ONE-TIME QuizBot profile + contact setup ───────────────────────────
# Creates the isolated simplex-chat profile for the QuizBot and gives you
# an invite link/QR to scan from your phone. Run this BEFORE starting the
# revize-bot service. The revize-bot daemon must NOT be running (it locks
# this DB). After you finish setup (step 6), quit and start the service.
set -e
DB=./state/simplex_v1
mkdir -p ./state/files
echo ">>> Launching simplex-chat as the QuizBot profile."
echo ">>> In the prompt that appears:"
echo "    1. It will create the profile 'QuizBot' (name set via --user-display-name)."
echo "    2. Type:  /c        (creates a contact invitation)"
echo "    3. It prints an smp::  invite link (and may show a QR)."
echo "    4. On your phone SimpleX app: Add contact -> paste/open that link."
echo "    5. Send 'hi' from your phone; you should see it appear here."
echo "    6. Type:  /q        (quit - profile is saved)"
echo "    Then start the bot:  sudo systemctl enable --now revize-bot"
echo
exec simplex-chat -y -d "$DB" --files-folder ./state/files \
     --user-display-name "QuizBot"
