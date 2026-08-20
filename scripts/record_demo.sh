#!/bin/bash
# Record a new demo GIF of the updated Prompt Playoff UI.
# Requires: ffmpeg, images2gif (or gifsicle), and a running Ollama instance.

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1

OUTPUT_GIF="assets/demo-cli.gif"
TEMP_DIR=$(mktemp -d)
FRAMES_DIR="$TEMP_DIR/frames"
mkdir -p "$FRAMES_DIR"

echo "🎬 Recording Prompt Playoff demo..."
echo "📁 Frames will be saved to: $FRAMES_DIR"
echo "🎞️  Output GIF: $OUTPUT_GIF"
echo ""
echo "Steps to record manually:"
echo "1. Start Prompt Playoff: ./start.command"
echo "2. Open browser at http://localhost:8000"
echo "3. Record your screen with QuickTime or screen recording tool"
echo "4. Save as demo.mov in assets/"
echo "5. Run: ffmpeg -i assets/demo.mov -vf 'fps=10,scale=820:-1:flags=lanczos' -gifflags 0 assets/demo-cli.gif"
echo ""
echo "Or use this automated approach with screenshots:"
echo ""

# Automated screenshot approach
echo "Starting automated demo recording..."

# Start the server in background
python -m prompt_playoff serve --port 8123 &
SERVER_PID=$!
sleep 5

# Check if server is running
if ! curl -s http://localhost:8123/health > /dev/null; then
    echo "❌ Server failed to start"
    kill $SERVER_PID 2>/dev/null || true
    exit 1
fi

echo "✅ Server started at http://localhost:8123"
echo ""
echo "Now open your browser and perform these steps:"
echo "1. Go to http://localhost:8123"
echo "2. Enter a task description (e.g., 'Extract entities from text')"
echo "3. Click 'Recommend' to see ranked techniques"
echo "4. Click 'Compile' to see the compiled prompt"
echo "5. Click 'Benchmark' to measure quality"
echo ""
echo "While you do this, take screenshots every 2 seconds:"
echo "  for i in {1..15}; do screencapture -x \"$FRAMES_DIR/frame_\$(printf '%03d' \$i).png\"; sleep 2; done"
echo ""
echo "Then convert to GIF:"
echo "  ffmpeg -framerate 2 -i $FRAMES_DIR/frame_%03d.png -vf 'scale=820:-1:flags=lanczos' -gifflags 0 $OUTPUT_GIF"
echo ""

# Cleanup function
cleanup() {
    echo "Cleaning up..."
    kill $SERVER_PID 2>/dev/null || true
    rm -rf "$TEMP_DIR"
}

trap cleanup EXIT

echo "Press Enter when ready to start recording..."
read -r

# Start taking screenshots
echo "📸 Taking screenshots every 2 seconds (Ctrl-C to stop)..."
for i in $(seq 1 15); do
    screencapture -x "$FRAMES_DIR/frame_$(printf '%03d' $i).png"
    echo "  Frame $i captured"
    sleep 2
done

# Convert to GIF
echo "🎞️  Converting to GIF..."
if command -v ffmpeg &> /dev/null; then
    ffmpeg -framerate 2 -i "$FRAMES_DIR/frame_%03d.png" \
        -vf "scale=820:-1:flags=lanczos" \
        -gifflags 0 \
        -y "$OUTPUT_GIF"
    
    echo "✅ Demo GIF created: $OUTPUT_GIF"
    echo "📊 File size: $(ls -lh "$OUTPUT_GIF" | awk '{print $5}')"
else
    echo "❌ ffmpeg not found. Install with: brew install ffmpeg"
    echo "Frames saved in: $FRAMES_DIR"
fi
