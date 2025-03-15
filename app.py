from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import json
import pandas as pd
from openai import OpenAI
import mysql.connector
import matplotlib
matplotlib.use("Agg")  # Use Agg backend to avoid Tkinter
import matplotlib.pyplot as plt
from sqlalchemy import create_engine
import os
import traceback

app = Flask(__name__)
CORS(app)

static_dir = 'static'
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

# Set up OpenRouter OpenAI API client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key="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"
)

def fetch_table_data(table_name):
    try:
        print(f"🔍 Checking if table '{table_name}' exists in database...")
        engine = create_engine("mysql+pymysql://root:root@localhost/newdatabase")

        tables = pd.read_sql("SHOW TABLES", engine)
        table_names = tables.iloc[:, 0].tolist()
        print(f"📋 Available tables: {table_names}")

        if table_name not in table_names:
            print(f"❌ Table '{table_name}' not found!")
            return None
        
        print(f"✅ Fetching data from table: {table_name}")
        df = pd.read_sql(f"SELECT * FROM {table_name}", engine)
        print(f"📊 Retrieved {len(df)} rows")
        return df

    except Exception as e:
        print(f"❌ MySQL Connection Error: {e}")
        traceback.print_exc()
        return None

def extract_chart_details(prompt):
    try:
        print(f"📝 Extracting chart details from: {prompt}")
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": f"Extract structured chart details from: '{prompt}'. Return ONLY a JSON object containing table_name, x_col, y_col, and chart_type (bar, line, or scatter)."}]
        )
        response_text = response.choices[0].message.content.strip()
        print(f"📥 OpenAI Response: {response_text}")

        details = json.loads(response_text)
        valid_chart_types = {"bar", "line", "scatter"}

        if details["chart_type"] not in valid_chart_types:
            print(f"⚠️ Invalid chart type: {details['chart_type']}")
            return None

        print(f"✅ Extracted details: {details}")
        return details

    except Exception as e:
        print("❌ OpenAI API Error:", e)
        traceback.print_exc()
        return None

def execute_query(prompt):
    try:
        print(f"💬 Received query prompt: {prompt}")

        # Fetch schema and convert it to a string
        schema = get_database_schema()
        if not schema:
            return None  # Handle case where schema fetch fails

        schema_str = json.dumps(schema, indent=2)
        print(f"📜 Database Schema: {schema_str}")

        # Modify the OpenAI prompt to include schema
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "user", "content": f"Here is the database schema:\n{schema_str}\n\nConvert this question into a SQL query: '{prompt}'. Use the correct table and column names."}
            ]
        )

        query = response.choices[0].message.content.strip()
        print(f"🔍 Generated SQL Query: {query}")

        engine = create_engine("mysql+pymysql://root:root@localhost/newdatabase")

        with engine.connect() as connection:
            print(f"📡 Executing query: {query}")
            result = pd.read_sql(query, connection)
            print(f"📊 Query returned {len(result)} rows")

        return result.to_dict(orient='records')

    except Exception as e:
        print("❌ Error executing query:", e)
        traceback.print_exc()
        return None

def visualize_data(df, x_col, y_col, chart_type):
    try:
        print(f"📊 Generating {chart_type} chart for {x_col} vs {y_col}")
        plt.figure(figsize=(8, 6))
        
        if chart_type == "bar":
            df.plot(kind="bar", x=x_col, y=y_col)
        elif chart_type == "line":
            df.plot(kind="line", x=x_col, y=y_col)
        elif chart_type == "scatter":
            df.plot(kind="scatter", x=x_col, y=y_col)
        else:
            print(f"❌ Unsupported chart type: {chart_type}")
            return None

        img_path = os.path.join("static", "chart.png")
        plt.savefig(img_path)
        plt.close()
        print(f"✅ Chart saved at: {img_path}")
        return img_path

    except Exception as e:
        print("❌ Error generating chart:", e)
        traceback.print_exc()
        return None

def get_database_schema():
    try:
        engine = create_engine("mysql+pymysql://root:root@localhost/newdatabase")
        schema_info = {}

        with engine.connect() as connection:
            tables = pd.read_sql("SHOW TABLES", connection)
            table_names = tables.iloc[:, 0].tolist()

            for table in table_names:
                columns = pd.read_sql(f"DESCRIBE {table}", connection)
                schema_info[table] = list(columns["Field"])  # Extract column names

        return schema_info

    except Exception as e:
        print("❌ Error fetching schema:", e)
        traceback.print_exc()
        return None

@app.route("/generate_chart", methods=["POST"])
def generate_chart():
    try:
        print("📩 Received request for chart generation")
        data = request.json
        print(f"📜 Request data: {data}")

        prompt = data.get("prompt")
        details = extract_chart_details(prompt)

        if not details:
            print("❌ Failed to extract chart details")
            return jsonify({"error": "❌ Failed to extract chart details"}), 400

        df = fetch_table_data(details["table_name"])
        if df is None:
            print("❌ Table not found in database")
            return jsonify({"error": "❌ Table not found"}), 400

        img_path = visualize_data(df, details["x_col"], details["y_col"], details["chart_type"])
        if not img_path:
            print("❌ Failed to generate chart")
            return jsonify({"error": "❌ Failed to generate chart"}), 400

        print(f"📤 Sending chart file: {img_path}")
        return send_file(img_path, mimetype="image/png")

    except Exception as e:
        print("❌ Error processing /generate_chart:", e)
        traceback.print_exc()
        return jsonify({"error": "❌ Server error"}), 500

@app.route("/ask_database", methods=["POST"])
def ask_database():
    try:
        print("📩 Received request for database query")
        data = request.json
        print(f"📜 Request data: {data}")

        prompt = data.get("question")
        if not prompt:
            print("⚠️ Empty query received")
            return jsonify({"error": "⚠️ Query cannot be empty"}), 400

        response = execute_query(prompt)
        if not response:
            print("❌ Could not process the query")
            return jsonify({"error": "❌ Could not process the query"}), 400

        print(f"✅ Query successful: {response}")
        return jsonify({"response": response})

    except Exception as e:
        print("❌ Internal Server Error:", e)
        traceback.print_exc()
        return jsonify({"error": f"❌ Server Error: {str(e)}"}), 500

if __name__ == "__main__":
    print("🚀 Starting Flask server...")
    app.run(debug=True)
