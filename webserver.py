import threading
import time
import json

from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# Shared state to hold the latest GPU data
# {
#   "data_point": {
#       "value": 40.0,
#       "last_seen": 123456789
#   }
# }
thermal_data = {}

# --- FLASK ENDPOINT ---
@app.route('/update_datepoint', methods=['POST'])
def update_datapoint():
    try:
        # Expects raw text or form data containing the temperature integer
        data_points: dict = json.loads(request.data.decode('utf-8').strip())
        
        for key, value in data_points.items():
            thermal_data.update({
                key: {
                    "value": value,
                    "last_seen": time.time()
                }
            })

        return "OK", 200
    except (ValueError, TypeError):
        return "Invalid Data", 400