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

2. **Set up environment variables**:
   ```bash
   cp env.example .env
   # Edit .env: set MYSQL_PASSWORD, MYSQL_ROOT_PASSWORD (and optional JWT_SECRET_KEY for production)
   ```

3. **Deploy with Docker Compose**:
   ```bash
   docker compose build --no-cache
   docker compose up -d
   ```
   If the database was initialized with an older password, reset volumes once:  
   `docker compose down -v` then `docker compose up -d` again.

4. **Access the application**:
   - App: `http://localhost:8000`
   - phpMyAdmin (optional): `http://localhost:8888`
   - Or configure your reverse proxy (Nginx, Traefik, etc.)

### Restore a SQL dump (Docker)

1. Copy your export to **`sqldumps/20260406.sql`** (or pass another path: `./scripts/import_sqldump_docker.sh /path/to/file.sql`).
2. If the database volume already has tables from a failed import, reset it: `docker compose down -v`.
3. Start MariaDB: `docker compose up -d db` and wait until it is healthy.
4. Run `./scripts/import_sqldump_docker.sh` from the project root (add **`--fresh`** if tables already exist from `init.sql` or a failed import — it drops and recreates the `db` schema first).  
   It imports that dump, then runs `sqldumps/reassign_isaac.sql` so all boards, sections, and pins belong to **isaac@leemail.com.au**.
5. Bring up the rest: `docker compose up -d`.

Root password defaults to `scrapbook_local_root_dev` unless you set `MYSQL_ROOT_PASSWORD` in `.env`.

The app and `reassign_isaac.sql` expect the logical database name **`db`**. If your dump targets another name, import into `db` (edit the dump’s `CREATE DATABASE` / `USE` lines, or create `db` and import only the tables).

## Building and Deployment

### Docker Registry Information

**Docker Hub Repository**: `staugustine1/scrapbook`
**Supported Architectures**: `linux/amd64`, `linux/arm64`

### Building Multi-Architecture Images

To build and push new versions to Docker Hub:

1. **Set up Docker buildx** (if not already done):
   ```bash
   docker buildx create --name multiarch-builder --driver docker-container --use
   ```

2. **Build and push for multiple architectures**:
   ```bash
   # Build and push a specific version (replace vX.X.X with actual version)
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     --tag staugustine1/scrapbook:vX.X.X \
     --tag staugustine1/scrapbook:latest \
     --push .
   ```

3. **For local testing only** (build without pushing):
   ```bash
   docker buildx build \
     --platform linux/amd64,linux/arm64 \
     --tag staugustine1/scrapbook:test \
     --load .
   ```

### Version Management

- **Git tags**: Create semantic version tags (e.g., `v1.1.2`)
- **Docker tags**: Mirror git tags for consistency
- **Latest tag**: Always points to the most recent stable version

Example release workflow:
```bash
# Commit changes
git add -A
git commit -m "v1.1.2: Description of changes"

# Tag the release
git tag -a v1.1.2 -m "Release v1.1.2: Description"

# Push to GitHub
git push origin main
git push origin --tags

# Build and push Docker image
docker buildx build --platform linux/amd64,linux/arm64 --tag staugustine1/scrapbook:v1.1.2 --tag staugustine1/scrapbook:latest --push .
```

### Configuration

1. **Set up environment variables**:
   ```bash
   cp env.example .env
   ```

2. **Edit the environment file**:
   - Change `your_secure_password_here` to a strong password
   - Change `your_secure_root_password_here` to a strong root password
   - Adjust other settings as needed

3. **For production deployment**:
   - Copy `docker-compose.example.yml` to `docker-compose.prod.yml` if needed
   - Adjust ports and network configuration as required

### Environment Variables

The application uses the following environment variables:

- `DB_HOST`: Database host (default: `db`)
- `DB_USER`: Database username (default: `db`)
- `DB_PASSWORD`: Database password (change this!)
- `DB_NAME`: Database name (default: `db`)
- `REDIS_HOST`: Redis host (default: `redis`)
- `REDIS_PORT`: Redis port (default: `6379`)
- `DEBUG_MODE`: Debug mode setting (default: `production`)
  - Set to `development` to enable debugging and URL health checking
  - Set to `production` (or leave unset) for production mode
- `FLASK_ENV`: Flask environment (automatically set based on `DEBUG_MODE`)

## Project Structure

```
scrapbook/
├── app.py                 # Main Flask application
├── Dockerfile            # Docker configuration
├── docker-compose.yml    # Development Docker Compose
├── docker-compose.prod.yml # Production Docker Compose
├── env.example           # Example environment variables
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
- Automatic Wayback Machine integration for broken links
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

### Debug Mode

To enable debugging and URL health checking in Docker:

1. **Set the DEBUG_MODE environment variable**:
   ```bash
   export DEBUG_MODE=development
   docker compose up -d
   ```

   Or create a `.env` file:
   ```bash
   echo "DEBUG_MODE=development" >> .env
   docker compose up -d
   ```

2. **What debug mode enables**:
   - Flask debug mode (auto-reload, detailed error pages)
   - Background URL health checking
   - More verbose logging

3. **For production**:
   - Leave `DEBUG_MODE` unset or set to `production`
   - This disables debugging and URL health checking for better performance

### Database Schema

The application uses the following main tables:
- `boards`: Stores board information
- `sections`: Organizes content within boards
- `pins`: Stores individual pin data
- `url_health`: Tracks URL status and archives

## Security

### Environment Variables
- **Never commit `.env` files** - they contain sensitive information
- Use `env.example` as a template for your environment configuration
- All database passwords and sensitive configuration should be stored in environment variables

### Password Management
- Use strong, unique passwords for database access
- Regularly rotate database passwords
- Consider using a password manager for production deployments

### Git History
- Sensitive information has been removed from git history
- If you accidentally commit sensitive data, use `git filter-repo` to remove it

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