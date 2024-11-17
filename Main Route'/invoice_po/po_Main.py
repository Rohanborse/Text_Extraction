from flask import Flask, render_template, request, redirect, url_for, flash
from werkzeug.utils import secure_filename
import os
import json
from pdf2image import convert_from_path
import psycopg2
import google.generativeai as genai
import decimal

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SECRET_KEY'] = 'your_secret_key'  # Required for flash messages

# Ensure upload folder exists
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Configure Google Gemini API
genai.configure(api_key="AIzaSyCP6JZiT1SCjT7d0R1WHwS6mt7BO3btvcs")

MODEL_CONFIG = {
    "temperature": 0.2,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 4096,
}

# Gemini model configuration
model = genai.GenerativeModel(model_name="gemini-1.5-flash",
                              generation_config=MODEL_CONFIG,
                              safety_settings=[
                                  {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                                  {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                                  {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
                                  {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
                              ])

# PostgreSQL database connection
def connect_to_db():
    """Connect to PostgreSQL database."""
    try:
        connection = psycopg2.connect(
            host="157.20.51.93",  # Your database host
            database="adm_db",  # Your database name
            user="postgres",  # Your database user
            password="Vikas$7!5&v^ate@",  # Your database password
            port="9871"
        )
        return connection
    except Exception as e:
        print(f"Database connection error: {e}")
        return None

def fetch_po_details(po_number):
    """Fetch PO details from the database."""
    conn = connect_to_db()
    if not conn:
        return None

    with conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM f_get_po_detail(%s);", (po_number,))
            db_data = cursor.fetchone()
            if not db_data:
                return {"error": f"PO Number {po_number} not found in the database."}  # Return an error message
    return db_data



# PDF to Image Conversion
def po_pdf_to_image(pdf_path):
    """Convert PDF pages to images."""
    images = convert_from_path(pdf_path, poppler_path='C:\\Program Files (x86)\\poppler-24.08.0\\Library\\bin')  # Ensure poppler is installed
    image_paths = []

    for i, image in enumerate(images):
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], f"temp_image_{i}.png")
        image.save(image_path, "PNG")
        image_paths.append(image_path)
    return image_paths

def image_format(image_path):
    """Prepare image data for API input."""
    with open(image_path, "rb") as img_file:
        return [{
            "mime_type": "image/png",
            "data": img_file.read()
        }]

# Gemini output generation
def po_gemini_output(image_path):
    """Get output from the Gemini model."""
    try:
        image_info = image_format(image_path)
        # Process the first image with Gemini
        system_prompt = """
                        You are a specialist in comprehending receipts.
                        Input images in the form of receipts will be provided to you,
                        and your task is to respond to questions based on the content of the input image.
                        """
        user_prompt = """
                        You are an intelligent assistant specialized in extracting structured data from invoices. Given the text extracted from an invoice, please provide the following fields in JSON format:
                        and cheak care fully for all values we need exact values as present dont miss zero also for example if 25.00 is in invoice then it should be 25.00 not like 25.0 or 25 
                        - "poNumber": The Purchase Order number from the invoice.
                        - "invoiceNo": The invoice number.
                        - "totalAmountWithGst": The total amount including GST.
                        - "products": An array of product details, where each product includes:
                            - "description": The description of the item.
                            - "partNo": The part number associated with the item.some time part no is in next line also if it not fit in column but "you write in one line only", and part no 
                            - "qty": The quantity of the item. just take numerical value dont take "KG" or "Nos" like units
                            - "rate": The rate per item.
                            - "amount": The total amount for the item.it is mus be qty multiply by rate
                        """
        input_prompt = [system_prompt, image_info[0], user_prompt]
        response = model.generate_content(input_prompt)
        raw_output = response.text.strip()
        if raw_output.startswith("```json"):
            raw_output = raw_output[8:-3].strip()

        return raw_output
    except Exception as e:
        print(f"Error during Gemini API call: {e}")
        return ""

# Data comparison logic
def trim_and_convert(value):
    """Trim and convert string to appropriate type."""
    if isinstance(value, str):
        return value.replace('[', '').replace(']', '').replace('\n', ' ').replace(',', '').replace('\"', '').replace('\'', '').strip()
    elif isinstance(value, (float, int)):
        return value
    elif isinstance(value, decimal.Decimal):
        return float(value)
    return value

def compare_data(json_data, db_data):
    """Compare extracted JSON data with database data."""
    comparison_results = {}
    product_comparisons = []

    if db_data is None:
        print("No data found in the database.")
        return comparison_results, product_comparisons  # Indicate no data found

    # Unpack based on the actual structure of db_data
    if isinstance(db_data, tuple) and len(db_data) > 0:
        db_data_dict = db_data[0]  # Get the dictionary from the tuple

        db_po_number = trim_and_convert(db_data_dict['poNumber'])
        db_total_amount_with_gst = trim_and_convert(db_data_dict['totalAmountWithGst'])
        db_products = db_data_dict['products']

        json_po_number = trim_and_convert(json_data.get('poNumber', ''))
        json_total_amount_with_gst = trim_and_convert(json_data.get('totalAmountWithGst', 0))
        json_products = json_data.get('products', [])

        # Comparing PO Number
        comparison_results['poNumber'] = {
            'invoice data': json_po_number,
            'db data': db_po_number,
            'Status': 'Match' if json_po_number == db_po_number else 'Mismatch'
        }

        # Comparing Total Amount
        comparison_results['totalAmountWithGst'] = {
            'invoice data': json_total_amount_with_gst,
            'db data': db_total_amount_with_gst,
            'Status': 'Match' if json_total_amount_with_gst == db_total_amount_with_gst else 'Mismatch'
        }

        # Compare products
        for json_product in json_products:
            json_description = trim_and_convert(json_product.get('description', ''))
            json_part_no = trim_and_convert(json_product.get('partNo', ''))
            json_quantity = trim_and_convert(json_product.get('qty', 0))
            json_rate = trim_and_convert(json_product.get('rate', 0))
            json_amount = trim_and_convert(json_product.get('amount', 0))

            best_match = None
            best_match_score = -1

            # Find the best match for each product
            for db_product in db_products:
                db_description = trim_and_convert(db_product.get('description', ''))
                db_part_no = trim_and_convert(db_product.get('partNo', ''))
                db_quantity = trim_and_convert(db_product.get('qty', 0))
                db_rate = trim_and_convert(db_product.get('rate', 0))
                db_amount = trim_and_convert(db_product.get('amount', 0))

                # Calculate match score (e.g., how many fields match)
                match_score = sum([
                    json_description == db_description,
                    json_part_no == db_part_no,
                    json_quantity == db_quantity,
                    json_rate == db_rate,
                    json_amount == db_amount
                ])

                if match_score > best_match_score:
                    best_match = db_product
                    best_match_score = match_score

            if best_match:
                db_description = trim_and_convert(best_match.get('description', ''))
                db_part_no = trim_and_convert(best_match.get('partNo', ''))
                db_quantity = trim_and_convert(best_match.get('qty', 0))
                db_rate = trim_and_convert(best_match.get('rate', 0))
                db_amount = trim_and_convert(best_match.get('amount', 0))

                product_comparisons.append({
                    'description': {
                        'invoice data': json_description,
                        'db data': db_description,
                        'Status': 'Match' if json_description == db_description else 'Mismatch'
                    },
                    'partNo': {
                        'invoice data': json_part_no,
                        'db data': db_part_no,
                        'Status': 'Match' if json_part_no == db_part_no else 'Mismatch'
                    },
                    'qty': {
                        'invoice data': json_quantity,
                        'db data': db_quantity,
                        'Status': 'Match' if json_quantity == db_quantity else 'Mismatch'
                    },
                    'rate': {
                        'invoice data': json_rate,
                        'db data': db_rate,
                        'Status': 'Match' if json_rate >= db_rate else 'Mismatch'
                    },
                    'amount': {
                        'invoice data': json_amount,
                        'db data': db_amount,
                        'Status': 'Match' if json_amount == db_amount else 'Mismatch'
                    }
                })

    else:
        print("Unexpected data structure:", db_data)

    return comparison_results, product_comparisons



