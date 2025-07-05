# Scrapbook - Personal Image Collection Manager

A Flask-based web application for organizing and managing personal image collections, similar to Pinterest but self-hosted.

## Features

- **Board Management**: Create and organize boards to categorize your images
- **Section Organization**: Add sections within boards for better organization
- **Image Scraping**: Automatically extract images from websites
- **Search Functionality**: Search through boards and pins
- **URL Health Monitoring**: Track broken links and find archived versions
- **Redis Caching**: Fast performance with Redis caching
- **Docker Ready**: Complete Docker setup for easy deployment

## Tech Stack

- **Backend**: Flask 3.0.0
- **Database**: MariaDB 11.6.2
- **Cache**: Redis 7
- **Container**: Docker & Docker Compose
- **Frontend**: HTML, CSS, JavaScript

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Git

### Deployment

1. **Clone the repository**:
   ```bash
   git clone <your-repo-url>
   cd scrapbook
   ```

2. **Deploy with Docker Compose**:
   ```bash
   docker compose -f docker-compose.prod.yml up -d
   ```

3. **Access the application**:
   - Open your browser and navigate to `http://localhost:8000`
   - Or configure your reverse proxy (Nginx, Traefik, etc.)

### Environment Variables

The application uses the following environment variables:

- `DB_HOST`: Database host (default: `db`)
- `DB_USER`: Database username (default: `db`)
- `DB_PASSWORD`: Database password
- `DB_NAME`: Database name (default: `db`)
- `REDIS_HOST`: Redis host (default: `redis`)
- `REDIS_PORT`: Redis port (default: `6379`)
- `FLASK_ENV`: Flask environment (default: `production`)

## Project Structure

```
scrapbook/
├── app.py                 # Main Flask application
├── Dockerfile            # Docker configuration
├── docker-compose.prod.yml # Production Docker Compose
├── requirements.txt      # Python dependencies
├── init.sql             # Database initialization
├── templates/           # HTML templates
├── static/              # Static files (CSS, JS, images)
├── scripts/             # Utility scripts
└── pins/                # Pin data (if any)
```

## Features in Detail

### Board Management
- Create, rename, and delete boards
- Organize content with custom sections
- Move pins between boards and sections

### Image Scraping
- Automatically extract images from URLs
- Support for lazy-loaded images
- Meta tag extraction (og:image, twitter:image)

### Search
- Search across board names and pin content
- Real-time search results
- Filter by boards or pins

### URL Health Monitoring
- Background monitoring of pin URLs
- Automatic archive.is integration
- Status tracking (live, broken, archived)

## Development

### Local Development

1. **Set up virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Run the application**:
   ```bash
   python app.py
   ```

### Database Schema

The application uses the following main tables:
- `boards`: Stores board information
- `sections`: Organizes content within boards
- `pins`: Stores individual pin data
- `url_health`: Tracks URL status and archives

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is open source and available under the [MIT License](LICENSE).

## Support

For issues and questions, please open an issue on GitHub. 