from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, g
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
import os
import replicate
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import base64
import requests
from io import BytesIO
import time
import psycopg2
from psycopg2 import sql
from werkzeug.security import generate_password_hash, check_password_hash

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')  # Load from .env
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL')  # Load from .env

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, email, password):
        self.id = id
        self.email = email
        self.password = password

@login_manager.user_loader
def load_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user:
        return User(user[0], user[1], user[2])
    return None

def get_db_connection():
    conn = psycopg2.connect(app.config['DATABASE_URL'])
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(120) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            url VARCHAR(255) NOT NULL
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

# Remove this decorator
# @app.before_first_request
# def create_tables():
#     init_db()

# Instead, call init_db() when the app starts
with app.app_context():
    init_db()

@app.before_request
def before_request():
    g.db = get_db_connection()

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/check_login')
def check_login():
    return jsonify({"logged_in": current_user.is_authenticated})

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        if cur.fetchone():
            flash('Email already exists')
            return redirect(url_for('signup'))
        hashed_password = generate_password_hash(password)
        cur.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_password))
        conn.commit()
        cur.close()
        conn.close()
        flash('Account created successfully')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        cur.close()
        conn.close()
        if user and check_password_hash(user[2], password):
            user_obj = User(user[0], user[1], user[2])
            login_user(user_obj)
            return redirect(url_for('index'))
        flash('Invalid email or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('login'))

@app.route('/transform', methods=['POST'])
def transform_image():
    image_size = int(request.form.get('image_size', 512))
    style = request.form.get('style', 'art style')
    color = request.form.get('color', 'vibrant colors')
    prompt = request.form.get('prompt', '')

    input_data = {
        "detect_resolution": image_size,
        "image_resolution": image_size,
        "return_width": image_size,
        "return_height": image_size,
        "prompt": f"{prompt}, {style}, {color}",
        "num_samples": 1,  # Generate 1 image per API call
        "num_inference_steps": 20,
        "guidance_scale": 9,
        "nsfw": True  # Ensure the API knows you want NSFW content
    }

    if 'file' in request.files:
        file = request.files['file']
        if file and file.filename != '':
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            with open(filepath, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
            input_data["image"] = f"data:image/png;base64,{encoded_string}"

            try:
                os.remove(filepath)
            except Exception as e:
                app.logger.error(f"Error removing file: {str(e)}")

    try:
        image_urls = []
        for _ in range(4):  # Make 4 API calls to get 4 images
            output = replicate.run(
                "black-forest-labs/flux-schnell",
                input=input_data
            )
            app.logger.info(f"API Output: {output}")  # Log the API output

            if isinstance(output, str):
                image_urls.append(output)
            elif isinstance(output, list) and len(output) > 0:
                image_urls.append(output[0])

            if len(image_urls) == 4:
                break

            time.sleep(1)  # Add a short delay between API calls

            # Save each generated image URL to the database
            for url in image_urls:
                if url:
                    cur = g.db.cursor()
                    cur.execute("INSERT INTO images (url) VALUES (%s)", (url,))
                    g.db.commit()
                    cur.close()

        # Pad the image_urls list to always have 4 items
        image_urls = image_urls + [None] * (4 - len(image_urls))

        return jsonify({
            "image_urls": image_urls,
            "generated_count": len([url for url in image_urls if url is not None])
        })
    except Exception as e:
        app.logger.error(f"API Error: {str(e)}")  # Log any errors
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Image generation failed"}), 500

@app.route('/download', methods=['GET'])
def download_image():
    image_url = request.args.get('url')
    if not image_url:
        return jsonify({"error": "No image URL provided"}), 400

    try:
        response = requests.get(image_url)
        response.raise_for_status()
        image_data = BytesIO(response.content)
        return send_file(image_data, mimetype='image/png', as_attachment=True, download_name='generated_image.png')
    except Exception as e:
        return jsonify({"error": f"Failed to download image: {str(e)}"}), 500

@app.route('/previous_images', methods=['GET'])
def previous_images():
    cur = g.db.cursor()
    cur.execute("SELECT url FROM images")
    images = cur.fetchall()
    cur.close()
    return jsonify({"images": [img[0] for img in images]})

if __name__ == '__main__':
    app.run(debug=True, port=4000)