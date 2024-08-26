from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2 import sql
import os
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

# Database connection
def get_db_connection():
    return psycopg2.connect(os.getenv('DATABASE_URL'))

@app.route('/api/users', methods=['GET'])
def get_users():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, is_premium, prompt_count, monthly_quota FROM users")
    users = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        'id': user[0],
        'email': user[1],
        'is_premium': user[2],
        'prompt_count': user[3],
        'monthly_quota': user[4]
    } for user in users])

@app.route('/api/user/<int:user_id>', methods=['GET'])
def get_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, email, is_premium, prompt_count, monthly_quota FROM users WHERE id = %s", (user_id,))
    user = cur.fetchone()
    cur.close()
    conn.close()
    if user:
        return jsonify({
            'id': user[0],
            'email': user[1],
            'is_premium': user[2],
            'prompt_count': user[3],
            'monthly_quota': user[4]
        })
    return jsonify({'error': 'User not found'}), 404

@app.route('/api/user/<int:user_id>/credits', methods=['PUT'])
def update_user_credits(user_id):
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET prompt_count = %s, monthly_quota = %s WHERE id = %s",
        (data['prompt_count'], data['monthly_quota'], user_id)
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'message': 'User credits updated successfully'})

@app.route('/api/user/<int:user_id>/prompts', methods=['GET'])
def get_user_prompts(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT prompt, created_at FROM images WHERE user_id = %s ORDER BY created_at DESC", (user_id,))
    prompts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{
        'prompt': prompt[0],
        'created_at': prompt[1].isoformat()
    } for prompt in prompts])

if __name__ == '__main__':
    app.run(debug=True, port=5001)