from flask import Flask, render_template, request, jsonify, send_file
import os
import replicate
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
import base64
import requests
from io import BytesIO
import time

load_dotenv()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

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
                "black-forest-labs/flux-dev",
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

if __name__ == '__main__':
    app.run(debug=True)