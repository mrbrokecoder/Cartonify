# AI Image Generation Web Application

Welcome to the AI Image Generation Web Application! This application allows users to generate images based on textual prompts, manage their image galleries, and subscribe to premium services for enhanced features. Built with Flask, PostgreSQL, Redis, Stripe, and Replicate, this application offers a robust and scalable solution for AI-driven image synthesis.

## Table of Contents

- [Features](#features)
- [Technologies Used](#technologies-used)
- [Installation](#installation)
  - [Local Installation](#local-installation)
  - [Docker Installation](#docker-installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [API Documentation](#api-documentation)
- [Contributing](#contributing)
- [License](#license)

## Features

- **User Authentication**: Secure registration and login system with email and OTP verification.
- **Image Generation**: Generate images based on user-provided prompts using AI technology.
- **Image Management**: View, download, and manage generated images in a user-friendly gallery.
- **Premium Subscriptions**: Subscribe to premium services for unlimited image generation and other benefits.
- **API Management**: Generate and manage API keys for programmatic access to image generation services.
- **Background Task Scheduling**: Automated tasks for managing user quotas and subscription benefits.

## Technologies Used

- **Flask**: Micro web framework for Python.
- **PostgreSQL**: Relational database for storing user data and image metadata.
- **Redis**: In-memory data store for caching and rate limiting.
- **Stripe**: Payment processing for premium subscriptions.
- **Replicate**: AI platform for image generation.
- **APScheduler**: Background task scheduling for periodic operations.

## Installation

### Local Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/ai-image-gen-app.git
   cd ai-image-gen-app
   ```

2. **Set up a virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up the database:**
   - Install PostgreSQL and create a database.
   - Update the database URL in the `.env` file.

5. **Set up Redis:**
   - Install Redis and ensure it is running.
   - Update the Redis URL in the `.env` file.

6. **Set up Stripe:**
   - Create a Stripe account and obtain the API keys.
   - Update the Stripe keys in the `.env` file.

7. **Set up Replicate:**
   - Create a Replicate account and obtain the API token.
   - Update the Replicate token in the `.env` file.

### Docker Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/yourusername/ai-image-gen-app.git
   cd ai-image-gen-app
   ```

2. **Build the Docker image:**
   ```bash
   docker build -t ai-image-gen-app .
   ```

3. **Run the Docker container:**
   ```bash
   docker run -d -p 5000:5000 --env-file .env ai-image-gen-app
   ```

## Configuration

Create a `.env` file in the root directory with the following variables:

```env
SECRET_KEY=your_secret_key
DATABASE_URL=postgresql://username:password@localhost/dbname
REDIS_URL=redis://localhost:6379/0
STRIPE_PUBLIC_KEY=your_stripe_public_key
STRIPE_SECRET_KEY=your_stripe_secret_key
REPLICATE_API_TOKEN=your_replicate_api_token
UPLOAD_FOLDER=uploads
MAX_CONTENT_LENGTH=16777216  # 16MB
SMTP_SERVER=your_smtp_server
SMTP_PORT=your_smtp_port
SMTP_USERNAME=your_smtp_username
SMTP_PASSWORD=your_smtp_password
```

## Usage

1. **Run the application:**
   ```bash
   flask run
   ```

2. **Access the application:**
   Open your browser and navigate to `http://127.0.0.1:5000/`.

3. **Register and log in:**
   - Register a new account or log in with existing credentials.
   - Generate images by submitting prompts.
   - Manage your image gallery and subscribe to premium services.

## API Documentation

The application provides an API for programmatic access to image generation services. To use the API:

1. **Generate an API key:**
   - Log in to the application and navigate to the API management section.
   - Generate a new API key and copy it.

2. **Make API requests:**
   - Use the API key to authenticate requests to the `/api/transform` endpoint.
   - Submit prompts and receive generated image data in response.

## Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository.
2. Create a new branch for your feature or bug fix.
3. Make your changes and commit them.
4. Push to your branch and submit a pull request.

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

---

Thank you for using the AI Image Generation Web Application! If you have any questions or need assistance, please open an issue or contact the maintainers.
