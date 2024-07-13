from datetime import datetime

from flask import Flask

app = Flask(__name__)


@app.route("/")
def hello_world():
    print("new web request")
    return f"hello from disco!!! the datetime is {datetime.now()}"
@app.route("/test")
def test():
    return f'THIS IS A TEST!!! IM ON THE INTERNET :3'


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=True)
