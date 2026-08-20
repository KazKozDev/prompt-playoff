# YouTube Analytics — AI-Powered Video Analysis Application

Modular YouTube analytics application for extracting and analyzing comprehensive data from YouTube videos through their URL. Independent service blocks with well-defined interfaces, local LLM integration via Ollama, and persistent storage.

```bash
# Clone and setup
git clone https://github.com/yourusername/youtube-analytics.git && cd youtube-analytics
pip install -r requirements.txt
python main.py
```

<p align="center">
  <a href="#"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python" height="20"></a>
  <a href="#"><img src="https://img.shields.io/badge/ollama-gemma3-green.svg" alt="Ollama" height="20"></a>
  <a href="#"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" height="20"></a>
</p>

---

## Quick start

1. **Clone the repository** and install dependencies:
   ```bash
   git clone https://github.com/yourusername/youtube-analytics.git
   cd youtube-analytics
   pip install -r requirements.txt
   ```

2. **Configure API keys** in `config.py`:
   ```python
   YOUTUBE_API_KEY = "your_api_key"
   OLLAMA_MODEL = "gemma3:12b"
   ```

3. **Install Ollama** with Gemma 3:12b model:
   ```bash
   ollama pull gemma3:12b
   ```

4. **Run tests** (optional):
   ```bash
   pytest
   ```

5. **Start the application**:
   ```bash
   python main.py
   ```

6. **Open your browser** at `http://localhost:8000`

## Analyze YouTube videos with AI

Paste a YouTube video URL and get comprehensive analysis:

```text
→ Video metadata (title, description, tags, statistics)
→ Channel information (subscribers, total views, video count)
→ Comments analysis (sentiment, topics, engagement patterns)
→ Transcript extraction and summarization
→ Related content recommendations
→ AI-powered insights via local LLM
```

All data is stored locally in SQLite database for offline access and historical analysis.

## Eight independent modules

The application is built as independent, testable blocks:

<table>
  <tr>
    <td align="center"><strong>Video Metadata</strong><br>Extract title, description, tags, duration, view count, likes, comments</td>
    <td align="center"><strong>Channel Info</strong><br>Subscriber count, total views, video count, channel description</td>
    <td align="center"><strong>Comments Analysis</strong><br>Sentiment analysis, topic extraction, engagement patterns</td>
  </tr>
  <tr>
    <td align="center"><strong>Transcript</strong><br>Automatic transcript extraction, timestamp alignment, summarization</td>
    <td align="center"><strong>Related Content</strong><br>Similar videos, recommendations, trend analysis</td>
    <td align="center"><strong>LLM Integration</strong><br>Local Gemma 3:12b via Ollama for insights and summaries</td>
  </tr>
  <tr>
    <td align="center"><strong>Data Storage</strong><br>SQLite database, persistent storage, query interface</td>
    <td align="center"><strong>Web Interface</strong><br>FastAPI backend, responsive frontend, real-time updates</td>
  </tr>
</table>

## Use with local LLM for privacy

All AI processing runs locally on your machine via Ollama:

```text
YouTube API → Data Extraction → Local Storage → Ollama (Gemma 3:12b) → AI Insights
```

No cloud dependencies for LLM processing. Your data stays private.

Configure the model in `config.py`:
```python
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:12b"
```

## How it works

The application uses a modular architecture with independent service blocks:

```text
YouTube URL → Metadata Extractor → Channel Analyzer → Comments Processor
                                      ↓
                            Transcript Extractor → Related Content
                                      ↓
                              Local LLM (Ollama) → AI Summary & Insights
                                      ↓
                              SQLite Database → Web Interface
```

<details>
<summary>Technical architecture</summary>

### Module architecture

1. **Video Metadata Module** (`modules/video_metadata.py`)
   - YouTube Data API v3 integration
   - Extracts: title, description, tags, duration, statistics
   - Caching for repeated requests

2. **Channel Information Module** (`modules/channel_info.py`)
   - Channel statistics and metadata
   - Historical data tracking
   - Competitor analysis support

3. **Comments Analysis Module** (`modules/comments_analysis.py`)
   - Batch comment extraction
   - Sentiment analysis via LLM
   - Topic clustering and keyword extraction

4. **Transcript Module** (`modules/transcript.py`)
   - Automatic caption extraction
   - Timestamp alignment
   - Text summarization

5. **Related Content Module** (`modules/related_content.py`)
   - Similar video recommendations
   - Trend analysis
   - Content gap identification

6. **LLM Integration Module** (`modules/llm_integration.py`)
   - Ollama API client
   - Prompt templates for analysis
   - Streaming responses

7. **Data Storage Module** (`modules/data_storage.py`)
   - SQLite database schema
   - CRUD operations
   - Query optimization

8. **Web Interface Module** (`modules/web_interface.py`)
   - FastAPI REST API
   - WebSocket for real-time updates
   - Responsive HTML/CSS/JS frontend

### Database schema

```sql
videos (id, url, title, description, tags, duration, view_count, like_count, comment_count, created_at)
channels (id, video_id, channel_id, channel_title, subscriber_count, total_views, video_count)
comments (id, video_id, author, text, like_count, sentiment, created_at)
transcripts (id, video_id, text, language, timestamps)
analysis (id, video_id, ai_summary, topics, keywords, created_at)
```

</details>

## Installation

### Requirements

- Python 3.9 or higher
- Ollama with Gemma 3:12b model
- YouTube Data API v3 key
- 8GB RAM minimum (16GB recommended for LLM)

### Step-by-step

1. **Clone repository**:
   ```bash
   git clone https://github.com/yourusername/youtube-analytics.git
   cd youtube-analytics
   ```

2. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # macOS/Linux
   venv\Scripts\activate     # Windows
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Install Ollama**:
   ```bash
   # macOS
   brew install ollama
   
   # Windows/Linux
   # Download from https://ollama.ai
   
   ollama pull gemma3:12b
   ```

5. **Configure environment**:
   ```bash
   cp .env.example .env
   # Edit .env with your API keys
   ```

6. **Run application**:
   ```bash
   python main.py
   ```

## Configuration

Edit `config.py` or `.env` file:

```python
# YouTube API
YOUTUBE_API_KEY = "your_api_key_here"

# Ollama settings
OLLAMA_BASE_URL = "http://localhost:11434"
OLLAMA_MODEL = "gemma3:12b"
OLLAMA_TIMEOUT = 300

# Database
DATABASE_URL = "sqlite:///youtube_analytics.db"

# Server
HOST = "0.0.0.0"
PORT = 8000
DEBUG = False
```

## Usage examples

### Analyze a single video

```python
from modules.integration import VideoAnalyzer

analyzer = VideoAnalyzer()
results = analyzer.analyze("https://youtube.com/watch?v=VIDEO_ID")

print(results.metadata.title)
print(results.channel.subscriber_count)
print(results.analysis.ai_summary)
```

### Batch analysis

```python
video_urls = [
    "https://youtube.com/watch?v=ID1",
    "https://youtube.com/watch?v=ID2",
    "https://youtube.com/watch?v=ID3"
]

for url in video_urls:
    results = analyzer.analyze(url)
    print(f"{results.metadata.title}: {results.analysis.sentiment}")
```

### Export data

```python
from modules.data_storage import DataExporter

exporter = DataExporter()
exporter.to_csv(video_id="VIDEO_ID", output_path="analysis.csv")
exporter.to_json(video_id="VIDEO_ID", output_path="analysis.json")
```

## Development

### Project structure

```
youtube-analytics/
├── config.py                # Configuration management
├── modules/
│   ├── video_metadata.py    # Video metadata extraction
│   ├── channel_info.py      # Channel information analysis
│   ├── comments_analysis.py # Comments extraction and analysis
│   ├── transcript.py        # Transcript extraction
│   ├── related_content.py   # Related content analysis
│   ├── llm_integration.py   # LLM processing via Ollama
│   ├── data_storage.py      # Database operations
│   └── web_interface.py     # User interface
├── integration.py           # Module integration framework
├── tests/                   # Test directory
│   ├── test_video_metadata.py
│   ├── test_channel_info.py
│   ├── test_comments_analysis.py
│   ├── test_transcript.py
│   └── ...
├── requirements.txt         # Python dependencies
├── .env.example            # Environment variables template
└── main.py                 # Application entry point
```

### Running tests

```bash
# Install test dependencies
pip install -r requirements-dev.txt

# Run all tests
pytest

# Run with coverage
pytest --cov=modules

# Run specific test file
pytest tests/test_video_metadata.py
```

### Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/new-feature`
3. Commit changes: `git commit -am 'Add new feature'`
4. Push to branch: `git push origin feature/new-feature`
5. Submit a Pull Request

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

### Code style

```bash
# Format code
black modules/ tests/

# Lint code
ruff check modules/ tests/

# Type checking
mypy modules/
```

## API Reference

### REST Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/analyze` | POST | Analyze a YouTube video |
| `/api/video/{id}` | GET | Get video metadata |
| `/api/channel/{id}` | GET | Get channel information |
| `/api/comments/{id}` | GET | Get comments analysis |
| `/api/transcript/{id}` | GET | Get video transcript |
| `/api/export/{id}` | GET | Export analysis data |

### WebSocket

Connect to `ws://localhost:8000/ws/analyze` for real-time analysis updates.

## Troubleshooting

### Common issues

**Ollama not responding**:
```bash
ollama serve  # Start Ollama server
ollama list   # Verify model is installed
```

**YouTube API quota exceeded**:
- Check quota at https://console.cloud.google.com
- Reduce batch size or wait for quota reset

**Database locked**:
```bash
# Close other applications using the database
# Or delete the database file to reset
rm youtube_analytics.db
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Acknowledgments

- YouTube Data API v3 by Google
- Ollama for local LLM inference
- Gemma models by Google
- FastAPI framework
- SQLite database

---

<p align="center">
  <strong>YouTube Analytics</strong> — Local, private, AI-powered video analysis
</p>
