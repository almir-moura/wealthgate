#!/bin/bash
# Wealthgate — Deploy to Railway via GitHub
# Run this script from the project root: ./deploy.sh
set -e

echo "🚀 Wealthgate Deployment"
echo "========================"
echo ""

# ── Step 1: GitHub CLI ──────────────────────────────────────────────
GH_BIN="/tmp/gh/gh_2.87.3_macOS_arm64/bin/gh"
if [ ! -f "$GH_BIN" ]; then
    echo "📦 Downloading GitHub CLI..."
    curl -sL -o /tmp/gh.zip "https://github.com/cli/cli/releases/download/v2.87.3/gh_2.87.3_macOS_arm64.zip"
    unzip -oq /tmp/gh.zip -d /tmp/gh
fi
GH="$GH_BIN"

# Check auth
if ! $GH auth status &>/dev/null; then
    echo ""
    echo "🔑 GitHub authentication required."
    echo "   A browser window will open. Log in and authorize."
    echo ""
    $GH auth login --hostname github.com --git-protocol https --web
fi

echo "✅ GitHub authenticated"

# ── Step 2: Create repo + push ──────────────────────────────────────
REPO_NAME="wealthgate"

if ! $GH repo view "$(git config user.name)/$REPO_NAME" &>/dev/null; then
    echo ""
    echo "📁 Creating GitHub repository: $REPO_NAME"
    $GH repo create "$REPO_NAME" --public --source=. --remote=origin --push
    echo "✅ Repository created and pushed"
else
    echo "📁 Repository already exists. Pushing latest changes..."
    git push -u origin main 2>/dev/null || git push origin main
    echo "✅ Pushed to GitHub"
fi

REPO_URL=$($GH repo view --json url -q ".url" 2>/dev/null || echo "https://github.com/$(git config user.name)/$REPO_NAME")
echo ""
echo "🔗 GitHub repo: $REPO_URL"

# ── Step 3: Railway ─────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Next: Deploy on Railway"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "1. Go to https://railway.com/new"
echo "2. Click 'Deploy from GitHub repo'"
echo "3. Select '$REPO_NAME'"
echo "4. Railway auto-detects Python + Procfile"
echo "5. Add variable: PORT = 8000 (Settings → Variables)"
echo "6. Go to Settings → Networking → Generate Domain"
echo ""
echo "Your app will be live at: https://<your-domain>.up.railway.app"
echo ""
echo "Or install Railway CLI: npm install -g @railway/cli"
echo "Then: railway login && railway init && railway up"
echo ""
echo "Done! 🎉"
