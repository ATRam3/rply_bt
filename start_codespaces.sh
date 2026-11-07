#!/bin/bash
# Quick start script for GitHub Codespaces

echo "=================================================="
echo "🚀 Replay Bot - Codespaces Startup"
echo "=================================================="
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found!"
    echo ""
    echo "Creating from template..."
    cp .env.codespaces .env
    echo "✅ Created .env file"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env with your actual credentials:"
    echo "   1. Open .env in the editor"
    echo "   2. Replace 'your_api_id_here' with your Telegram API ID"
    echo "   3. Replace 'your_api_hash_here' with your Telegram API hash"
    echo "   4. Replace 'your_gemini_key_here' with your Gemini API key"
    echo "   5. Save the file"
    echo ""
    read -p "Press Enter after you've updated .env..."
fi

# Check if mt5_prices.json exists
if [ ! -f mt5_prices.json ]; then
    echo "❌ CRITICAL: mt5_prices.json not found!"
    echo ""
    echo "This file contains price data for the quiz."
    echo ""
    echo "To fix:"
    echo "1. On your Windows PC, run: python generate_prices.py"
    echo "2. Commit the file: git add mt5_prices.json"
    echo "3. Push to GitHub: git push"
    echo "4. Restart this Codespace"
    echo ""
    exit 1
fi

echo "✅ mt5_prices.json found"

# Show price data info
GENERATED_AT=$(jq -r '.generated_at' mt5_prices.json)
PRICE_COUNT=$(jq '.prices | length' mt5_prices.json)

echo "   Generated: $GENERATED_AT"
echo "   Prices loaded: $PRICE_COUNT symbols"
echo ""

# Check if Tesseract is installed
if command -v tesseract &> /dev/null; then
    TESS_VERSION=$(tesseract --version 2>&1 | head -1)
    echo "✅ Tesseract OCR: $TESS_VERSION"
else
    echo "⚠️  Tesseract not found, installing..."
    sudo apt-get update && sudo apt-get install -y tesseract-ocr
    echo "✅ Tesseract installed"
fi

echo ""
echo "=================================================="
echo "🎯 Ready to start bot!"
echo "=================================================="
echo ""
echo "Run: python bot.py"
echo ""
