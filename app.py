from flask import Flask, render_template, request, jsonify, send_file, redirect, url_for, flash, session
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
from datetime import datetime, timedelta
import secrets  # Add this import at the top of the file
import razorpay
from apscheduler.schedulers.background import BackgroundScheduler
import atexit
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import random
import redis
from flask_session import Session
from flask import send_from_directory


load_dotenv()

from dotenv import load_dotenv
import os

load_dotenv()  # This loads the variables from .env

app = Flask(__name__, static_folder='static')
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_CONTENT_LENGTH'))  # 16MB max upload size
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY')
app.config['DATABASE_URL'] = os.getenv('DATABASE_URL')
app.config['RAZORPAY_KEY_ID'] = os.getenv('RAZORPAY_KEY_ID')
app.config['RAZORPAY_KEY_SECRET'] = os.getenv('RAZORPAY_KEY_SECRET')
razorpay_client = razorpay.Client(auth=(app.config['RAZORPAY_KEY_ID'], app.config['RAZORPAY_KEY_SECRET']))
app.config['SESSION_TYPE'] = 'filesystem'

# Add these configurations
app.config['SMTP_SERVER'] = os.getenv('SMTP_SERVER')
app.config['SMTP_PORT'] = int(os.getenv('SMTP_PORT'))
app.config['SMTP_USERNAME'] = os.getenv('SMTP_USERNAME')
app.config['SMTP_PASSWORD'] = os.getenv('SMTP_PASSWORD')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
app.config['SESSION_TYPE'] = 'filesystem'

# Redis Configuration
app.config['REDIS_URL'] = os.getenv('REDIS_URL', 'redis://127.0.0.1:4000')
app.config['SESSION_TYPE'] = 'redis'
app.config['SESSION_PERMANENT'] = False
app.config['SESSION_USE_SIGNER'] = True
app.config['SESSION_REDIS'] = redis.from_url(app.config['REDIS_URL'])

# Initialize Redis
redis_client = redis.from_url(app.config['REDIS_URL'])

# Initialize Flask-Session
Session(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, email, password, username=None, is_premium=False, prompt_count=0, subscription_start=None, monthly_quota=0, is_admin=False):
        self.id = id
        self.email = email
        self.password = password
        self.username = username
        self.is_premium = is_premium
        self.prompt_count = prompt_count
        self.subscription_start = subscription_start
        self.monthly_quota = monthly_quota
        self.is_admin = is_admin

@login_manager.user_loader
def load_user(user_id):
    user_key = f'user:{user_id}'
    user_data = redis_client.hgetall(user_key)
    
    if user_data:
        return User(
            int(user_data[b'id']),
            user_data[b'email'].decode('utf-8'),
            user_data[b'password'].decode('utf-8'),
            user_data.get(b'username', b'').decode('utf-8') or None,
            bool(int(user_data[b'is_premium'])),
            int(user_data[b'prompt_count']),
            datetime.fromisoformat(user_data[b'subscription_start'].decode('utf-8')) if user_data[b'subscription_start'] else None,
            int(user_data[b'monthly_quota']),
            bool(int(user_data.get(b'is_admin', b'0')))
        )
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, password, username, COALESCE(is_premium, FALSE) as is_premium, COALESCE(prompt_count, 0) as prompt_count, subscription_start, monthly_quota, COALESCE(is_admin, FALSE) as is_admin FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        # Cache user data in Redis
        redis_client.hmset(user_key, {
            'id': user[0],
            'email': user[1],
            'password': user[2],
            'username': user[3] or '',
            'is_premium': int(user[4]),
            'prompt_count': user[5],
            'subscription_start': user[6].isoformat() if user[6] else '',
            'monthly_quota': user[7],
            'is_admin': int(user[8])
        })
        redis_client.expire(user_key, 3600)  # Cache for 1 hour
        
        return User(user[0], user[1], user[2], user[3], user[4], user[5], user[6], user[7], user[8])
    return None

def get_db_connection():
    conn = psycopg2.connect(app.config['DATABASE_URL'])
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Create users table if it doesn't exist
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(120) UNIQUE NOT NULL,
            password VARCHAR(255) NOT NULL
        )
    """)
    
    # Add is_premium column if it doesn't exist
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='users' AND column_name='is_premium') THEN
                ALTER TABLE users ADD COLUMN is_premium BOOLEAN DEFAULT FALSE;
            END IF;
        END $$;
    """)
    
    # Add prompt_count column if it doesn't exist
    cur.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                           WHERE table_name='users' AND column_name='prompt_count') THEN
                ALTER TABLE users ADD COLUMN prompt_count INTEGER DEFAULT 0;
            END IF;
        END $$;
    """)
    
    # Create images table with all necessary columns
    cur.execute("""
        CREATE TABLE IF NOT EXISTS images (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            url VARCHAR(255) NOT NULL,
            prompt TEXT,
            style VARCHAR(255),
            color VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add columns if they don't exist
    columns_to_add = [
        ('user_id', 'INTEGER REFERENCES users(id)'),
        ('prompt', 'TEXT'),
        ('style', 'VARCHAR(255)'),
        ('color', 'VARCHAR(255)'),
        ('created_at', 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    ]
    
    for column_name, column_type in columns_to_add:
        cur.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns 
                               WHERE table_name='images' AND column_name='{column_name}') THEN
                    ALTER TABLE images ADD COLUMN {column_name} {column_type};
                END IF;
            END $$;
        """)
    
    # Add api_key column to users table
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS api_key VARCHAR(64) UNIQUE;
    """)
    
    # Add subscription_start and monthly_quota columns
    cur.execute("""
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS subscription_start TIMESTAMP,
        ADD COLUMN IF NOT EXISTS monthly_quota INTEGER DEFAULT 0;
    """)
    
    # Add is_admin column to users table
    cur.execute("""
        ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE;
    """)
    
    # Create api_usage table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS api_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            usage_date DATE NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            UNIQUE (user_id, usage_date)
        )
    """)
    
    # Create videos table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            url VARCHAR(255) NOT NULL,
            prompt TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Add username column to users table
    cur.execute("""
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS username VARCHAR(50) UNIQUE;
    """)
    
    conn.commit()
    cur.close()
    conn.close()


with app.app_context():
    init_db()

def safe_get(data, index, default=None):
    if isinstance(data, dict):
        return data.get(index, default)
    elif isinstance(data, (list, tuple)):
        return data[index] if index < len(data) else default
    return default

@app.template_filter('custom_datetime')
def custom_datetime(value):
    if isinstance(value, str):
        try:
            return datetime.strptime(value, '%Y-%m-%d %H:%M:%S.%f')
        except ValueError:
            try:
                return datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return value
    return value

@app.route('/')
def home():
    if current_user.is_authenticated:
        user = get_user_data(current_user.id)
        user['credits_percentage'] = (user['credits_used'] / user['total_credits']) * 100
    else:
        user = {
            'username': 'Guest',
            'avatar_url': '/static/default_avatar.png',
            'points': 0,
            'credits_used': 0,
            'total_credits': 0,
            'credits_percentage': 0,
            'profile_url': '/login'
        }
    
    # Fetch the most recent generated images with all necessary information
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT url, prompt, style, color, created_at 
        FROM images 
        ORDER BY created_at DESC 
        LIMIT 12
    """)
    images = [
        {
            'url': row[0],
            'prompt': row[1],
            'style': row[2],
            'color': row[3],
            'created_at': row[4]
        } for row in cur.fetchall()
    ]
    cur.close()
    conn.close()
    
    return render_template('home.html', images=images, user=user)



def get_user_data(user_id):
    # Connect to your database and fetch user data
    # This is a simplified example; adjust according to your database setup
    connection = get_db_connection()
    cursor = connection.cursor()
    
    cursor.execute("SELECT username, avatar_url, points, credits_used, total_credits FROM users WHERE id = %s", (user_id,))
    user_data = cursor.fetchone()
    
    connection.close()
    
    return {
        'username': user_data[0],
        'avatar_url': user_data[1],
        'points': user_data[2],
        'credits_used': user_data[3],
        'total_credits': user_data[4],
        'profile_url': f"/user/{user_data[0]}"
    }

# Update the login manager to use the new home page
login_manager.login_view = 'home'

@app.route('/dashboard')
@login_required
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT url, prompt, style, color, created_at FROM images WHERE user_id = %s ORDER BY created_at DESC", (current_user.id,))
    images = cur.fetchall()
    
    # Get user's premium status and remaining credits
    cur.execute("SELECT is_premium, prompt_count, monthly_quota FROM users WHERE id = %s", (current_user.id,))
    user_data = cur.fetchone()
    is_premium, prompt_count, monthly_quota = user_data
    
    cur.close()
    conn.close()
    
    # Calculate remaining credits
    if is_premium:
        remaining_credits = monthly_quota
    else:
        remaining_credits = 5 - prompt_count
    
    user_agent = request.user_agent.string.lower()
    if 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent or 'ipad' in user_agent:
        return render_template('mobile.html', images=images, safe_get=safe_get, remaining_credits=remaining_credits, is_premium=is_premium)
    else:
        return render_template('index.html', images=images, safe_get=safe_get, remaining_credits=remaining_credits, is_premium=is_premium)

@app.route('/api_dashboard')
@login_required
def api_dashboard():
    if not current_user.is_authenticated:
        flash('Please log in to access the API dashboard.', 'warning')
        return redirect(url_for('login'))
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch user's API key
    cur.execute("SELECT api_key FROM users WHERE id = %s", (current_user.id,))
    api_key = cur.fetchone()[0]
    
    # Fetch API usage
    cur.execute("""
        SELECT COUNT(*) FROM images 
        WHERE user_id = %s AND created_at >= NOW() - INTERVAL '30 days'
    """, (current_user.id,))
    api_usage = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    return render_template('dashboard.html', api_key=api_key, api_usage=api_usage)

@app.route('/generate_api_key', methods=['POST'])
@login_required
def generate_api_key():
    new_api_key = secrets.token_urlsafe(32)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET api_key = %s WHERE id = %s", (new_api_key, current_user.id))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"api_key": new_api_key})

@app.route('/revoke_api_key', methods=['POST'])
@login_required
def revoke_api_key():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET api_key = NULL WHERE id = %s", (current_user.id,))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({"message": "API key revoked successfully"})

# Update the existing api_transform_image function to track usage
@app.route('/api/transform', methods=['POST'])
def api_transform_image():
    api_key = request.headers.get('X-API-Key')
    if not api_key:
        return jsonify({"error": "API key is required"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE api_key = %s", (api_key,))
    user = cur.fetchone()

    if not user:
        cur.close()
        conn.close()
        return jsonify({"error": "Invalid API key"}), 401

    user_id = user[0]

    # Get request data
    data = request.json
    prompt = data.get('prompt')
    image_size = data.get('image_size', 512)
    style = data.get('style', 'art style')
    color = data.get('color', 'vibrant colors')

    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400

    # Prepare input data for the image generation model
    input_data = {
        "detect_resolution": image_size,
        "image_resolution": image_size,
        "return_width": image_size,
        "return_height": image_size,
        "prompt": f"{prompt}, {style}, {color}",
        "num_samples": 1,
        "num_inference_steps": 20,
        "guidance_scale": 9,
        "nsfw": True
    }

    try:
        # Use the image generation model (replace with your actual model)
        output = replicate.run(
            "stability-ai/stable-diffusion:db21e45d3f7023abc2a46ee38a23973f6dce16bb082a930b0c49861f96d1e5bf",
            input=input_data
        )

        # Process the output
        image_urls = output if isinstance(output, list) else [output]

        # Save image information to the database
        for url in image_urls:
            cur.execute("""
                INSERT INTO images (user_id, url, prompt, style, color, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
            """, (user_id, url, prompt, style, color))

        conn.commit()

        # Update API usage count
        cur.execute("""
            INSERT INTO api_usage (user_id, usage_date, count)
            VALUES (%s, CURRENT_DATE, 1)
            ON CONFLICT (user_id, usage_date)
            DO UPDATE SET count = api_usage.count + 1
        """, (user_id,))
        conn.commit()

        cur.close()
        conn.close()

        return jsonify({"image_urls": image_urls})

    except Exception as e:
        cur.close()
        conn.close()
        return jsonify({"error": str(e)}), 500

    # ... (return the generated image URLs)

# Add this new route to get API usage statistics
@app.route('/api_usage_stats')
@login_required
def api_usage_stats():
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch daily API usage for the last 30 days
    cur.execute("""
        SELECT usage_date, count
        FROM api_usage
        WHERE user_id = %s AND usage_date >= CURRENT_DATE - INTERVAL '30 days'
        ORDER BY usage_date
    """, (current_user.id,))
    
    usage_stats = cur.fetchall()
    
    cur.close()
    conn.close()
    
    return jsonify(usage_stats)

@app.route('/check_login')
def check_login():
    return jsonify({"logged_in": current_user.is_authenticated})


@app.route('/api/user_profile')
def user_profile_api():
    if current_user.is_authenticated:
        user = get_user_data(current_user.id)
        user['credits_percentage'] = (user['credits_used'] / user['total_credits']) * 100
    else:
        user = {
            'username': 'Guest',
            'avatar_url': '/static/default_avatar.png',
            'points': 0,
            'credits_used': 0,
            'total_credits': 0,
            'credits_percentage': 0,
            'profile_url': '/login'
        }
    return jsonify(user)

def send_otp_email(email, otp):
    msg = MIMEMultipart()
    msg['From'] = app.config['SMTP_USERNAME']
    msg['To'] = email
    msg['Subject'] = 'Your OTP for Cartonify Signup'
    
    html = f"""
    <html>
        <body>
            <h2>Welcome to Cartonify!</h2>
            <p>Thank you for signing up. To complete your registration, please use the following One-Time Password (OTP):</p>
            <h1 style="color: #4B0082; font-size: 24px;">{otp}</h1>
            <p>This OTP is valid for 10 minutes. If you didn't request this, please ignore this email.</p>
            <p>Best regards,<br>The Image Garden Team</p>
        </body>
    </html>
    """
    msg.attach(MIMEText(html, 'html'))
    
    with smtplib.SMTP_SSL(app.config['SMTP_SERVER'], app.config['SMTP_PORT']) as server:
        server.login(app.config['SMTP_USERNAME'], app.config['SMTP_PASSWORD'])
        server.send_message(msg)

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        if 'otp' in request.form:
            # OTP verification step
            email = session.get('signup_email')
            otp = request.form['otp']
            
            if otp != session.get('signup_otp'):
                flash('Invalid OTP')
                return render_template('signup.html', email=email, show_otp=True)
            
            # OTP is valid, create the user
            password = session.get('signup_password')
            hashed_password = generate_password_hash(password)
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO users (email, password) VALUES (%s, %s)", (email, hashed_password))
            conn.commit()
            cur.close()
            conn.close()
            
            # Clear session data
            session.pop('signup_otp', None)
            session.pop('signup_email', None)
            session.pop('signup_password', None)
            
            flash('Account created successfully')
            return redirect(url_for('login'))
        else:
            # Initial signup step
            email = request.form['email']
            password = request.form['password']
            
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                flash('Email already exists')
                cur.close()
                conn.close()
                return redirect(url_for('signup'))
            cur.close()
            conn.close()
            
            # Add error handling and logging here
            try:
                # Generate OTP
                otp = str(random.randint(100000, 999999))
                
                # Store OTP and user details in session
                session['signup_otp'] = otp
                session['signup_email'] = email
                session['signup_password'] = password
                
                # Send OTP via email
                send_otp_email(email, otp)
                
                flash('OTP sent to your email. Please enter it to complete signup. check Spam')
                return render_template('signup.html', email=email, show_otp=True)
            except Exception as e:
                app.logger.error(f"Error sending OTP: {str(e)}")
                flash("An error occurred while sending OTP. Please try again.")
                return render_template('signup.html', show_otp=False)

    
    return render_template('signup.html', show_otp=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
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
            user_obj = User(user[0], user[1], user[2], user[3], user[4], user[5], user[6], user[7], user[8])
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

def check_user_quota(user):
    if not user.is_premium:
        return user.prompt_count < 5
    else:
        # Check if the subscription has expired
        if user.subscription_start and datetime.now() - user.subscription_start > timedelta(days=30):
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("""
                UPDATE users 
                SET is_premium = FALSE, 
                    subscription_start = NULL, 
                    monthly_quota = 0 
                WHERE id = %s
            """, (user.id,))
            conn.commit()
            cur.close()
            conn.close()
            return False
        return user.monthly_quota > 0
    
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('.', 'service-worker.js')

@app.route('/transform', methods=['POST'])
@login_required
def transform_image():
    rate_limit_key = f'rate_limit:{current_user.id}'
    current_count = redis_client.get(rate_limit_key)
    
    if current_count is None:
        redis_client.setex(rate_limit_key, 3600, 1)  # Set initial count with 1 hour expiry
    elif int(current_count) >= 10:
        return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
    else:
        redis_client.incr(rate_limit_key)
    
    # Check user quota before proceeding with image generation
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT is_premium, prompt_count, monthly_quota, subscription_start FROM users WHERE id = %s", (current_user.id,))
    user_data = cur.fetchone()
    is_premium, prompt_count, monthly_quota, subscription_start = user_data

    if is_premium:
        # Check if the subscription has expired
        if subscription_start and datetime.now() - subscription_start > timedelta(days=30):
            cur.execute("""
                UPDATE users 
                SET is_premium = FALSE, 
                    subscription_start = NULL, 
                    monthly_quota = 0 
                WHERE id = %s
            """, (current_user.id,))
            conn.commit()
            is_premium = False
            monthly_quota = 0
        elif monthly_quota <= 0:
            cur.close()
            conn.close()
            return jsonify({
                'quota_exceeded': True,
                'is_premium': True
            }), 403
    else:
        if prompt_count >= 5:
            cur.close()
            conn.close()
            return jsonify({
                'quota_exceeded': True,
                'is_premium': False
            }), 403
    
    operation = request.form.get('operation', 'generate')

    if operation == 'enhance':
        if 'file' not in request.files:
            return jsonify({"error": "No file uploaded"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "No file selected"}), 400
        
        if file:
            # Save the file temporarily
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

            with open(filepath, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

            # Use a model for image enhancement
            model = "tencentarc/gfpgan:0fbacf7afc6c144e5be9767cff80f25aff23e52b0708f17e20f9879b2f21516c"
            input_data = {
                "img": f"data:image/png;base64,{encoded_string}",
                "version": "v1.4",
                "scale": 2
            }

            try:
                output = replicate.run(model, input=input_data)
                return jsonify({"image_urls": [output]})
            except Exception as e:
                return jsonify({"error": str(e)}), 500
            finally:
                # Clean up the temporary file
                os.remove(filepath)

    prompt = request.form.get('prompt')
    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400

    # Check for NSFW content (implement your own NSFW detection logic)
    if is_nsfw(prompt):
        return jsonify({'nsfw_content': True}), 400

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
        "num_samples": 1,
        "num_inference_steps": 20,
        "guidance_scale": 9,
        "nsfw": True
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

    # Check if image editing is requested
    if request.form.get('edit_image') == 'true':
        model = "tencentarc/gfpgan:0fbacf7afc6c144e5be9767cff80f25aff23e52b0708f17e20f9879b2f21516c"
        input_data = {
            "img": input_data["image"],
            "version": "v1.4",
            "scale": 2
        }
    else:
        # Use the regular image generation model
        model = "black-forest-labs/flux-schnell"

    # Check if inpainting is requested
    if 'mask' in request.files:
        mask_file = request.files['mask']
        if mask_file and mask_file.filename != '':
            mask_filename = secure_filename(mask_file.filename)
            mask_filepath = os.path.join(app.config['UPLOAD_FOLDER'], mask_filename)
            mask_file.save(mask_filepath)

            with open(mask_filepath, "rb") as mask_file:
                mask_encoded_string = base64.b64encode(mask_file.read()).decode('utf-8')
            input_data["mask"] = f"data:image/png;base64,{mask_encoded_string}"

            try:
                os.remove(mask_filepath)
            except Exception as e:
                app.logger.error(f"Error removing mask file: {str(e)}")

            # Use the inpainting model
            model = "stability-ai/stable-diffusion-inpainting"

    try:
        image_urls = []
        for _ in range(2):
            output = replicate.run(
                model,
                input=input_data
            )
            app.logger.info(f"API Output: {output}")

            if isinstance(output, str):
                image_urls.append(output)
            elif isinstance(output, list) and len(output) > 0:
                image_urls.append(output[0])

            if len(image_urls) == 4:
                break

            time.sleep(1)

        image_urls = image_urls + [None] * (2 - len(image_urls))

        # Save image information to the database
        for url in image_urls:
            if url:
                cur.execute("""
                    INSERT INTO images (user_id, url, prompt, style, color, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (current_user.id, url, prompt, style, color, datetime.now()))

        # Update quota after successful generation
        if is_premium:
            cur.execute("UPDATE users SET monthly_quota = monthly_quota - 1 WHERE id = %s", (current_user.id,))
        else:
            cur.execute("UPDATE users SET prompt_count = prompt_count + 1 WHERE id = %s", (current_user.id,))

        conn.commit()
        cur.close()
        conn.close()

        return jsonify({
            "image_urls": image_urls,
            "generated_count": len([url for url in image_urls if url is not None]),
            "quota_exceeded": False,
            "is_premium": is_premium
        })
    except Exception as e:
        cur.close()
        conn.close()
        app.logger.error(f"API Error: {str(e)}")
        return jsonify({"error": str(e)}), 500

    return jsonify({"error": "Image generation failed"}), 500

# Implement these functions based on your specific requirements
def is_nsfw(prompt):
    # Implement NSFW detection logic
    pass

def update_user_quota(user):
    # Update user's quota in the database
    pass

def update_users_with_admin_field():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin = FALSE WHERE is_admin IS NULL")
    conn.commit()
    cur.close()
    conn.close()

# Run this function once to update all existing users
update_users_with_admin_field()

def create_user(email, password):
    hashed_password = generate_password_hash(password)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO users (email, password, is_admin) VALUES (%s, %s, %s)", 
                (email, hashed_password, False))
    conn.commit()
    cur.close()
    conn.close()

@app.route('/download', methods=['GET'])
@login_required
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

@app.route('/debug')
@login_required
def debug():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM images WHERE user_id = %s ORDER BY created_at DESC", (current_user.id,))
    images = cur.fetchall()
    cur.close()
    conn.close()
    
    debug_info = {
        "image_count": len(images),
        "first_image_type": str(type(images[0])) if images else None,
        "first_image_length": len(images[0]) if images else None,
        "first_image_data": str(images[0]) if images else None,
    }
    
    return jsonify(debug_info)

@app.route('/api_management')
@login_required
def api_management():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT api_key FROM users WHERE id = %s", (current_user.id,))
    api_key = cur.fetchone()[0]
    cur.close()
    conn.close()
    return render_template('api_management.html', api_key=api_key)

@app.route('/premium')
@login_required
def premium():
    return render_template('premium.html', razorpay_key_id=app.config['RAZORPAY_KEY_ID'])

@app.route('/create-checkout-session', methods=['POST'])
@login_required
def create_checkout_session():
    try:
        checkout_session = razorpay_client.order.create({
            'amount': 50000,  # Amount in paise (500 INR)
            'currency': 'INR',
            'payment_capture': 1,
            'notes': {
                'user_id': current_user.id
            }
        })
        return jsonify({'id': checkout_session['id']})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/premium-success', methods=['POST'])
@login_required
def premium_success():
    try:
        # Verify the payment signature
        params_dict = {
            'razorpay_order_id': request.json.get('razorpay_order_id'),
            'razorpay_payment_id': request.json.get('razorpay_payment_id'),
            'razorpay_signature': request.json.get('razorpay_signature')
        }
        razorpay_client.utility.verify_payment_signature(params_dict)
        
        # Payment successful, update user to premium
        conn = get_db_connection()
        cur = conn.cursor()
        subscription_start = datetime.now()
        cur.execute("""
            UPDATE users 
            SET is_premium = TRUE, 
                subscription_start = %s, 
                monthly_quota = 1600 
            WHERE id = %s
        """, (subscription_start, current_user.id))
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({'success': True})
    except Exception as e:
        app.logger.error(f"Payment verification failed: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 400

# Add a background task to reset monthly quota
def reset_monthly_quota():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id FROM users 
        WHERE is_premium = TRUE AND subscription_start IS NOT NULL 
        AND subscription_start + INTERVAL '30 days' > NOW()
    """)
    premium_users = cur.fetchall()
    cur.close()
    conn.close() 
    for user in premium_users:
        user_key = f'user:{user[0]}'
        redis_client.hset(user_key, 'monthly_quota', 1600)
        redis_client.expire(user_key, 3600)  # Refresh cache expiry

# Initialize the scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(reset_monthly_quota, 'cron', day=1, hour=0, minute=0)
scheduler.start()

# Make sure to shut down the scheduler when the app is closing
atexit.register(lambda: scheduler.shutdown())

@app.route('/admin')
@login_required
def admin_dashboard():
    if current_user.email == 'gptadarsh1@gmail.com' or current_user.is_admin:
        if current_user.email == 'gptadarsh1@gmail.com':
            # Ensure this user is always set as admin
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("UPDATE users SET is_admin = TRUE WHERE email = %s", (current_user.email,))
            conn.commit()
            cur.close()
            conn.close()
            current_user.is_admin = True  # Update the current user object
            flash('Admin access granted.', 'success')
        
        # Fetch all users
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, email, is_premium, prompt_count, monthly_quota FROM users")
        users = cur.fetchall()
        cur.close()
        conn.close()
        
        # Convert to list of dictionaries for easier use in template
        users = [
            {
                'id': user[0],
                'email': user[1],
                'is_premium': user[2],
                'prompt_count': user[3],
                'monthly_quota': user[4]
            } for user in users
        ]
        
        return render_template('admin_dashboard.html', users=users)
    else:
        flash('You do not have permission to access the admin dashboard.', 'error')
        return redirect(url_for('index'))


@app.route('/promote_to_admin/<email>')
@login_required
def promote_to_admin(email):
    if not current_user.is_admin:
        flash('You do not have permission to perform this action.', 'error')
        return redirect(url_for('index'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE users SET is_admin = TRUE WHERE email = %s", (email,))
    affected_rows = cur.rowcount
    conn.commit()
    cur.close()
    conn.close()

    if affected_rows > 0:
        flash(f'User {email} has been promoted to admin.', 'success')
    else:
        flash(f'User {email} not found or already an admin.', 'error')

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/user_prompts/<int:user_id>')
@login_required
def get_user_prompts(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT prompt, created_at FROM images WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    prompts = cur.fetchall()
    cur.close()
    conn.close()

    return jsonify({
        'prompts': [
            {'prompt': prompt[0], 'created_at': prompt[1].isoformat()}
            for prompt in prompts
        ]
    })

@app.route('/admin/update_credits/<int:user_id>', methods=['PUT'])
@login_required
def update_user_credits(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        data = request.json
        new_credits = data.get('monthly_quota')

        if new_credits is None:
            return jsonify({'error': 'Invalid data: monthly_quota is missing'}), 400

        new_credits = int(new_credits)  # Ensure it's an integer

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "UPDATE users SET monthly_quota = %s WHERE id = %s",
            (new_credits, user_id)
        )
        affected_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()

        if affected_rows == 0:
            return jsonify({'error': 'User not found or no changes made'}), 404

        return jsonify({'message': 'User credits updated successfully'})
    except Exception as e:
        app.logger.error(f"Error updating credits: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/convert_to_premium/<int:user_id>', methods=['POST'])
@login_required
def convert_to_premium(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # First, check if the user exists and is not already premium
        cur.execute("SELECT is_premium FROM users WHERE id = %s", (user_id,))
        user = cur.fetchone()
        
        if not user:
            cur.close()
            conn.close()
            return jsonify({'error': 'User not found'}), 404
        
        if user[0]:  # If user is already premium
            cur.close()
            conn.close()
            return jsonify({'error': 'User is already premium'}), 400
        
        # Convert user to premium
        subscription_start = datetime.now()
        cur.execute("""
            UPDATE users 
            SET is_premium = TRUE, 
                subscription_start = %s, 
                monthly_quota = 1600 
            WHERE id = %s
        """, (subscription_start, user_id))
        
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({'message': 'User successfully converted to premium'})
    except Exception as e:
        app.logger.error(f"Error converting user to premium: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/revoke_premium/<int:user_id>', methods=['POST'])
@login_required
def revoke_premium(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE users 
            SET is_premium = FALSE, 
                subscription_start = NULL, 
                monthly_quota = 0 
            WHERE id = %s
        """, (user_id,))
        
        affected_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        if affected_rows == 0:
            return jsonify({'error': 'User not found or already not premium'}), 404
        
        return jsonify({'message': 'Premium status successfully revoked'})
    except Exception as e:
        app.logger.error(f"Error revoking premium status: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/delete_user/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Delete user's images first
        cur.execute("DELETE FROM images WHERE user_id = %s", (user_id,))
        
        # Then delete the user
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        
        affected_rows = cur.rowcount
        conn.commit()
        cur.close()
        conn.close()
        
        if affected_rows == 0:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({'message': 'User successfully deleted'})
    except Exception as e:
        app.logger.error(f"Error deleting user: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/admin/user_details/<int:user_id>')
@login_required
def get_user_details(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        cur.execute("""
            SELECT id, email, is_premium, prompt_count, monthly_quota, subscription_start
            FROM users 
            WHERE id = %s
        """, (user_id,))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'id': user[0],
            'email': user[1],
            'is_premium': user[2],
            'prompt_count': user[3],
            'monthly_quota': user[4],
            'subscription_start': user[5].isoformat() if user[5] else None
        })
    except Exception as e:
        app.logger.error(f"Error fetching user details: {str(e)}")
        return jsonify({'error': f'Server error: {str(e)}'}), 500

@app.route('/generate_video', methods=['POST'])
@login_required
def generate_video():
    prompt = request.json.get('prompt')
    if not prompt:
        return jsonify({'error': 'No prompt provided'}), 400

    try:
        output = replicate.run(
            "lucataco/animate-diff:beecf59c4aee8d81bf04f0381033dfa10dc16e845b4ae00d281e2fa377e48a9f",
            input={
                "prompt": prompt,
                "num_frames": 16,
                "num_inference_steps": 50,
                "guidance_scale": 7.5
            }
        )
        
        video_url = output['output']
        
        # Save video information to the database
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO videos (user_id, url, prompt, created_at)
            VALUES (%s, %s, %s, NOW())
        """, (current_user.id, video_url, prompt))
        conn.commit()
        cur.close()
        conn.close()

        return jsonify({"video_url": video_url})
    except Exception as e:
        app.logger.error(f"Video generation error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_user_videos')
@login_required
def get_user_videos():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT url, prompt, created_at FROM videos WHERE user_id = %s ORDER BY created_at DESC", (current_user.id,))
    videos = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([
        {
            "url": video[0],
            "prompt": video[1],
            "created_at": video[2].isoformat()
        } for video in videos
    ])

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        username = request.form.get('username')
        
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Check if username already exists
        cur.execute("SELECT id FROM users WHERE username = %s AND id != %s", (username, current_user.id))
        if cur.fetchone():
            flash('Username already taken', 'error')
        else:
            # Update username
            cur.execute("UPDATE users SET username = %s WHERE id = %s", (username, current_user.id))
            conn.commit()
            flash('Profile updated successfully', 'success')
        
        cur.close()
        conn.close()
        
        # Update the current_user object
        current_user.username = username
        
    # Fetch user's subscription details
    subscription_end = None
    if current_user.is_premium and current_user.subscription_start:
        subscription_end = current_user.subscription_start + timedelta(days=30)
    
    return render_template('profile.html', user=current_user, subscription_end=subscription_end)


@app.route('/create-order', methods=['POST'])
@login_required
def create_order():
    try:
        amount = 500  # Amount in paise (500 paise = 5 INR)
        order_currency = 'INR'
        
        order_data = {
            'amount': amount,
            'currency': order_currency,
            'payment_capture': '1'
        }
        
        order = razorpay_client.order.create(data=order_data)
        return jsonify({'order_id': order['id']})
    except Exception as e:
        return jsonify(error=str(e)), 403
    
@app.route('/enhance_prompt', methods=['POST'])
@login_required
def enhance_prompt():
    basic_prompt = request.json.get('prompt')
    
    if not basic_prompt:
        return jsonify({'error': 'No prompt provided'}), 400

    try:
        output = replicate.run(
            "meta/llama-2-70b-chat:02e509c789964a7ea8736978a43525956ef40397be9033abf9fd2badfe68c9e3",
            input={
                "prompt": f"""Enhance the following image generation prompt. Follow these rules strictly:
1. Start with a concise theme or style description.
2. Describe the main subject and its immediate surroundings.
3. Add key visual elements and details.
4. Include artistic style, rendering technique, or inspiration.
5. End with 'best quality, masterpiece'.
6. Keep it under 50 words total.
7. Do not use storytelling or explanatory language.

Example: 'Cybercore Aesthetic, a woman sitting on a counter in a neon lit bar with neon signs and neon lights behind her and a neon sign behind her, cyberpunk style, cyberpunk art, cinema 4d, cinematic angle, cinematic lighting, best quality, masterpiece'

User prompt: {basic_prompt}

Enhanced prompt:""",
                "max_new_tokens": 100,
                "temperature": 0.7,
                "top_p": 0.9,
                "repetition_penalty": 1
            }
        )
        
        # Consume the generator and join the output
        full_response = ''.join(list(output))
        
        # Extract only the enhanced prompt part
        enhanced_prompt = full_response.strip()
        
        # Remove any quotation marks
        enhanced_prompt = enhanced_prompt.strip('"')
        
        app.logger.debug(f"Enhanced prompt: {enhanced_prompt}")
        
        return jsonify({'enhanced_prompt': enhanced_prompt})
    except Exception as e:
        app.logger.error(f"Prompt enhancement error: {str(e)}")
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    with app.app_context():
        init_db()
    app.run(debug=True, host="0.0.0.0", port=4000)