#!/bin/bash
# Quick demo recorder for Prompt Playoff
# Records 20 seconds of your screen and converts to GIF

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

OUTPUT_GIF="assets/demo-cli.gif"
TEMP_MOV="/tmp/prompt-playoff-demo.mov"

echo "🎬 Prompt Playoff Demo Recorder"
echo "================================"
echo ""
echo "Instructions:"
echo "1. Start Prompt Playoff: ./start.command"
echo "2. Open http://localhost:8000 in browser"
echo "3. Click Record below when ready"
echo "4. Perform the demo flow (20 seconds)"
echo "5. Stop recording with Ctrl-C"
echo ""
echo "Demo flow:"
echo "  • Show homepage (2s)"
echo "  • Enter task: 'Extract entities from text' (3s)"
echo "  • Click Recommend (3s)"
echo "  • Review techniques (3s)"
echo "  • Click Compile (3s)"
echo "  • Click Benchmark (3s)"
echo "  • Show results (3s)"
echo ""

read -p "Press Enter to start recording..."

# Start screen recording
# Note: On macOS 10.15+, you need to grant Terminal screen recording permission
# System Preferences → Security & Privacy → Privacy → Screen Recording
echo "📹 Recording started... (Ctrl-C to stop)"
echo "⏱️  Recording for 20 seconds..."

timeout 20 screencapture -C -v -T 0 "$TEMP_MOV" || true

if [ ! -f "$TEMP_MOV" ]; then
    echo "❌ Recording failed. Make sure Terminal has screen recording permission."
    echo "   Go to: System Preferences → Security & Privacy → Privacy → Screen Recording"
    exit 1
fi

echo "🎞️  Converting to GIF..."

# Convert to GIF with optimization
ffmpeg -i "$TEMP_MOV" \
    -vf "fps=10,scale=820:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128[p];[s1][p]paletteuse" \
    -loop 0 \
    -y "$OUTPUT_GIF" \
    2>/dev/null

# Clean up
rm -f "$TEMP_MOV"

# Show result
if [ -f "$OUTPUT_GIF" ]; then
    SIZE=$(ls -lh "$OUTPUT_GIF" | awk '{print $5}')
    DIMS=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 "$OUTPUT_GIF")
    echo ""
    echo "✅ Demo GIF created!"
    echo "   File: $OUTPUT_GIF"
    echo "   Size: $SIZE"
    echo "   Dimensions: $DIMS"
    echo ""
    echo "To update README, this line is already correct:"
    echo '  <img src="assets/demo-cli.gif" alt="Prompt Playoff demo" width="820">'
else
    echo "❌ Failed to create GIF"
    exit 1
fi
