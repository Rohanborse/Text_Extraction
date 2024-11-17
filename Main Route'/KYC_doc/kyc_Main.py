from flask import Flask, render_template, request, redirect, url_for, flash, json, jsonify
import os
from werkzeug.utils import secure_filename, send_from_directory
import psycopg2
import google.generativeai as genai
from pdf2image import convert_from_path
import json

app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Configure Google Gemini API
genai.configure(api_key="AIzaSyCP6JZiT1SCjT7d0R1WHwS6mt7BO3btvcs")  # Replace with your actual API key

# Configuration for Gemini model
MODEL_CONFIG = {
    "temperature": 0.2,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 4096,
}

# Initialize Gemini model
model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config=MODEL_CONFIG)

# Ensure upload directory exists
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# PostgreSQL Database connection
def get_db_connection():
    conn = psycopg2.connect(
        host="157.20.51.93",
        database="adm_db",
        user="postgres",
        password="Vikas$7!5&v^ate@",
        port="9871"
    )
    return conn


# PDF to Image Conversion
def pdf_to_image(pdf_path):
    images = convert_from_path(pdf_path, poppler_path='C:\\Program Files (x86)\\poppler-24.08.0\\Library\\bin')
    image_paths = []
    for i, image in enumerate(images):
        image_path = os.path.join(UPLOAD_FOLDER, f"temp_image_{i}.png")
        image.save(image_path, "PNG")
        image_paths.append(image_path)
    return image_paths


# Image Preparation for API Input
def image_format(image_path):
    with open(image_path, "rb") as img_file:
        return [{"mime_type": "image/png", "data": img_file.read()}]


# Gemini Output Generation
def gemini_output(image_path, system_prompt, user_prompt):
    try:
        image_info = image_format(image_path)
        input_prompt = [system_prompt, image_info[0], user_prompt]
        response = model.generate_content(input_prompt)
        raw_output = response.text.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output[8:-3].strip()
        return raw_output
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return ""


# Process file and extract data
def process_file(file_path):
    _, file_extension = os.path.splitext(file_path.lower())
    system_prompt = """
        You are a specialist in analyzing government-issued identity documents.
        You will receive images of documents such as PAN cards and Aadhar cards,
        and your task is to extract structured data fields based on the document type.
        """
    user_prompt = """
        You are an intelligent assistant specialized in extracting structured data from government-issued documents. 
        Given the text extracted from an identity document, please provide the following fields in JSON format based on the document type:
        For a PAN Card:
        - "documentType": "PAN Card"
        - "panNumber": The Permanent Account Number (PAN) on the card.
        - "name": The name of the individual.
        - "fatherName": The father's name (if present). (father name will be the next line of the name)
        - "dateOfBirth": The date of birth in the format DD/MM/YYYY. (dateOfBirth will be the next line of father name)
        For an Aadhar Card:
        - "documentType": "Aadhar Card"
        - "Aadhar Number": The unique 12-digit Aadhar number.
        - "Name": The name of the individual.
        - "dateOfBirth": The date of birth in the format DD/MM/YYYY. (if Date of Birth is not present then Year Of Birth will be present and that will be in YYYY forma but it will also included in dateOfBirth )
        - "Address": The full address including street, city, district, state, and postal code.
        Ensure the fields are extracted accurately, respecting any formatting for dates and numbers.
        But please remind all output of JSON should be in "double quotes symbol". and Double quotes symbol= ""
        """

    if file_extension == ".pdf":
        image_paths = pdf_to_image(file_path)
        if image_paths:
            output_json = gemini_output(image_paths[0], system_prompt, user_prompt)
        else:
            print("Failed to convert PDF to images.")
            return
    elif file_extension in [".png", ".jpg", ".jpeg"]:
        output_json = gemini_output(file_path, system_prompt, user_prompt)
    else:
        print("Unsupported file format.")
        return

    try:
        json_data = json.loads(output_json)
        return json_data
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return {}


def save_data_to_db(extracted_data):
    conn = None
    try:
        # Establish database connection
        conn = get_db_connection()
        cursor = conn.cursor()

        # Get document type from the extracted data
        document_type = extracted_data.get("documentType")

        # Insert PAN Card data if the document is of type "PAN Card"
        if document_type == "PAN Card":
            cursor.execute(
                """INSERT INTO KYC_Document (documentType, panNumber, name, fatherName, dateOfBirth) VALUES (%s, %s, %s, %s, %s)""",
                (extracted_data.get("documentType"),
                 extracted_data.get("panNumber"),
                 extracted_data.get("name"),
                 extracted_data.get("fatherName"),
                 extracted_data.get("dateOfBirth"))
            )

        # Insert Aadhar Card data if the document is of type "Aadhar Card"
        elif document_type == "Aadhar Card":
            cursor.execute(
                """INSERT INTO KYC_Document (Document Type, aadharNumber, name, dateOfBirth, address) VALUES (%s, %s, %s, %s, %s)""",
                (extracted_data.get("documentType"),
                 extracted_data.get("Aadhar Number"),
                 extracted_data.get("Name"),
                 extracted_data.get("dateOfBirth"),
                 extracted_data.get("Address"))
            )

        # Commit transaction
        conn.commit()
        print("Data saved to database successfully.")

    except Exception as e:
        # Print or log the error
        print(f"Error saving data to database: {e}")
        if conn:
            conn.rollback()  # Rollback in case of error

    finally:
        # Ensure the connection is closed
        if conn:
            cursor.close()
            conn.close()
            print("Database connection closed.")
from flask import session, redirect, url_for



