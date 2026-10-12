import os

from flask import Flask, send_from_directory
from flask_cors import CORS

from config import Config
from db import init_db
from routes import api


def create_app() -> Flask:
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config["UPLOAD_FOLDER"] = os.path.abspath(Config.UPLOAD_FOLDER)

    CORS(app, origins=Config.CORS_ORIGINS, supports_credentials=True)
    init_db(Config.MYSQL_URI)

    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.register_blueprint(api)

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "1") == "1")
