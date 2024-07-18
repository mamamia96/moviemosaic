from datetime import datetime
from fetch_data import scrape, rss_feed_exists, valid_movies
from time import time
from file_management import file_cleanup, file_saver, serve_image, read_image
from image_builder import build
from ratio_tester import get_moviecells
from flask import Flask, redirect, url_for, request, session, send_file, render_template
import io
import base64
import secrets
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os
from flask_session import Session

app = Flask(__name__)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.secret_key = secrets.token_urlsafe(16)
Session(app)
usernames = []

# def file_cleaner():
#     # this is executed every ten minutes
#     file_cleanup(usernames)

# scheduler = BackgroundScheduler()
# scheduler.add_job(file_cleaner, trigger='interval', minutes=10)
# scheduler.start()


def validate_submitted_string(s: str) -> bool:
	# temporary until I figure out how i want to structure this
	print(f'RSS FEED -> letterboxd.com/rss/{s}: {rss_feed_exists(s)}')
	return True and rss_feed_exists(s)

@app.route('/user/<string:username>')
def dynamic_page(username):
    usernames.append(username)
    image_string, image = create_mosaic(username)
    # session['image_path'] = file_saver(username=username, image=image)
    session['image_string'] = image_string
    download_url = url_for('download_image', username=username)
    # file_cleanup(filter_str=username)
    return render_template('dynamic_page.html', image=image_string, download_url=download_url)

@app.route('/download/<string:username>')
def download_image(username):
    # image_path = session.get('image_path', None)
    # image = read_image(image_path)
    image_string = session.get('image_string', None)
    if image_string:
        image_data = base64.b64decode(image_string)
        buffer = io.BytesIO(image_data)
        # buffer = io.BytesIO()
        # image_string.save(buffer, format='PNG')
        buffer.seek(0)
        # file_cleanup()
        return send_file(buffer, as_attachment=True, download_name=f'{username}.png', mimetype='image/png/')
    else:
        return 'Image not found', 404

# FIGURE OUT SESSSIONS<>
# @app.after_request
# def after_request(response):
#     session.pop('error_message', None)
#     response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
#     return response

@app.route('/', methods=['GET', 'POST'])
def main_form():
    if request.method == 'GET':
        return render_template('main_form.html')
    
    submitted_username = request.form['username_submitted']
    
    if not validate_submitted_string(submitted_username):
        return render_template('main_form.html', error_message='Invalid username')
    
    movie_items = valid_movies(submitted_username, datetime.now().month)
    if not movie_items:
        return render_template('main_form.html', error_message=f'No valid movies found for {submitted_username}')
    return redirect(url_for('dynamic_page', username=submitted_username))


def create_mosaic(username: str):
    # image_str is used for displaying image on webpage
    # image is raw data of image. Save it to local storage
    movie_cells = scrape(username, datetime.now().month)

    if not movie_cells:
        return None, None

    image = build(movie_cells, username, 'config.json')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    buffer.seek(0)
    image_string = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return image_string, image

if __name__ == "__main__":
    if os.path.isfile('.env'):
        load_dotenv('.env')
    print(os.environ)
    app.run(host="0.0.0.0", port=8080, debug=True)

# when i have post redirect using get
