from flask import Flask, request, render_template, redirect, url_for, flash, session
import os
import json
import google.generativeai as genai
from pdf2image import convert_from_path


app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Required for sessions
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def merge_dicts(target, source):
    for key, value in source.items():
        if isinstance(value, dict) and key in target:
            merge_dicts(target[key], value)
        elif not target.get(key):  # Only update if target value is None or empty
            target[key] = value

def calculate_cost_of_saving(kvah, kwh, rate):
    try:
        # Calculate cost of saving
        cost_of_saving = (kvah - kwh) * rate
        cost_of_saving = round(cost_of_saving, 2)
        return cost_of_saving
    except ValueError:
        print("Error: KVAH or KWH values are not in a valid format.")
        return None

# Gemini output generation

def get_cost_saving_from_output(output):
    try:
        kvah = float(output["Current Consumption Details"].get("KVAH", 0))
        kwh = float(output["Current Consumption Details"].get("KWH", 0))
        rate = float(output["Current Consumption Details"].get("Rate", 0))


        cost_saving = calculate_cost_of_saving(kvah, kwh, rate)
        return cost_saving
    except ValueError:
        print("Error: Invalid values for KVAH or KWH.")
        return None


def ebill_pdf_to_image(pdf_path, output_folder="uploads", page_limit=2):
    """Convert only the first 'page_limit' pages of a PDF to images and save them."""
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    try:
        # Limit conversion to the first 'page_limit' pages
        images = convert_from_path(pdf_path, first_page=1, last_page=page_limit,
                                   poppler_path='C:\\Program Files (x86)\\poppler-24.08.0\\Library\\bin')
        image_paths = []
        for i, image in enumerate(images):
            image_path = os.path.join(output_folder, f"temp_image_{i}.png")
            image.save(image_path, "PNG")
            image_paths.append(image_path)
        return image_paths
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return []

def image_format(image_path):
    """Prepare image data for API input."""
    try:
        with open(image_path, "rb") as img_file:
            return [{
                "mime_type": "image/png",
                "data": img_file.read()
            }]
    except FileNotFoundError as e:
        print(f"Image file not found: {e}")
        return []
    except Exception as e:
        print(f"Error preparing image for API: {e}")
        return []

def cleanup_images(image_paths):
    """Delete all temporary images created from PDF pages."""
    for path in image_paths:
        try:
            os.remove(path)
        except Exception as e:
            print(f"Error deleting file {path}: {e}")


genai.configure(api_key="AIzaSyCP6JZiT1SCjT7d0R1WHwS6mt7BO3btvcs")

MODEL_CONFIG = {
    "temperature": 0.2,
    "top_p": 1,
    "top_k": 32,
    "max_output_tokens": 4096,
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=MODEL_CONFIG,
    safety_settings=[
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"}
    ]
)


def ebill_gemini_output(image_paths):
    """Generate a single JSON output from Gemini using multiple images and prompts."""
    combined_output = {
        "Consumer Details": {},
        "Billing Summary": {},
        "Current Consumption Details": {}
    }

    for i, image_path in enumerate(image_paths):
        try:
            image_info = image_format(image_path)
            if not image_info:
                continue  # Skip if image data preparation failed
            system_prompt = """ 
                                    "You are a highly specialized assistant trained to interpret and extract structured data from electricity bills 
                                    issued by utilities. Your goal is to analyze the input document, identify key data fields, and return structured 
                                    information in JSON format. The electricity bill includes details about the consumer, consumption metrics, charges,
                                    payment history, and other billing-related information.

                                    The document may contain the following sections:

                                    Consumer Information: Customer details like name, address, consumer number, PAN, and GSTIN.
                                    Billing Period and Important Dates: Billing cycle, bill date, due date, and last payment date.
                                    Consumption Metrics: Meter readings, consumption details, and power factor.
                                    Financial Summary: Summary of charges, including energy charges, demand charges, and total bill amount.
                                    Additional Notes: Important notifications, available discounts, rebates, and other informational messages.
                                    Extract each field with precision and present it in JSON format under the specified categories:

                                    Consumer Details
                                    Billing Period and Date Information
                                    Current Consumption Details
                                    Billing Summary
                                    Historical Data
                                    Additional Information
                                    Your output should be concise, with only relevant data fields accurately labeled and organized for quick and effective 
                                    analysis. Ignore any promotional content or irrelevant text, and focus solely on structured data extraction.
                                      """
            user_prompt = """
                                "Given the API response with detailed electricity billing data, extract only the specific sections and fields 
                                listed below and structure them in JSON format as shown. Exclude any unrelated data or additional comments. 
                                Ensure the JSON output follows this exact structure, with the specified fields organized under Consumer Details,
                                 Billing Summary, and Current Consumption Details. Each field should have the correct label and placement as shown below.

                                Extract and format the data as follows:

                                Consumer Details:
                                Consumer No: Identifier for the consumer
                                Consumer Name: Full name of the consumer
                                Address: Complete address of the consumer
                                Village: Village name
                                Pin Code: Postal code
                                Contract Demand (KVA): Contract demand in KVA
                                75% of Con. Demand (KVA): 75% of the contract demand in KVA
                                Billing Summary:

                                Bill Amount: Total billed amount for the current cycle
                                Demand Charges: Charges based on demand
                                Wheeling Charge: Charges for wheeling
                                Energy Charges: Charges based on energy consumption
                                TOD Tariff EC: Time-of-day tariff energy charges
                                FAC: Fuel adjustment charge
                                Electricity Duty: Duty on electricity usage
                                Bulk Consumption Rebate: Rebate for bulk consumption
                                Tax on Sale: Tax on the sale of electricity
                                Incremental Consumption Rebate: Rebate for increased consumption
                                Charges For Excess Demand: Charges if demand exceeded
                                Tax Collection at Source: Tax collected at source
                                Debit Bill Adjustment: Adjustments on the bill (debit)
                                Current Interest: Interest applied on the current bill
                                Principal Arrears: Outstanding principal amount
                                Interest Arrears: Outstanding interest amount
                                Total Bill Amount (Rounded): Rounded total bill amount
                                Delay Payment Charges: Late payment charges
                                Billed Demand KVA : find it in billed details Section 
                                @Rs : find in billed Details Section
                                Current Consumption Details:

                                KWH: Total Consumption of Energy in kilowatt-hours (this is located in the current consumption table Column is KWH and row is Total Consumption)
                                KVAH: Total Consumption apparent energy consumed
                                RKVA (LAG): Reactive power in kVAR (lagging)
                                RKVA (LEAD): Reactive power in kVAR (leading)
                                KW (MD): Maximum demand in kilowatts
                                KVA (MD): Maximum demand in kilovolt-amperes
                                Billed Demand (KVA): Demand billed in kilovolt-amperes
                                Assessed P.F.: Assessed power factor
                                Billed P.F.: Billed power factor
                                Rate : Rate will be the amount per unit that is use to calculate the total bill cost
                        """
            input_prompt = [system_prompt, image_info[0], user_prompt]
            response = model.generate_content(input_prompt)

            # Log the raw response to debug
            # print(f"Raw API Response for page {i + 1}: {response.text}")

            raw_output = response.text.strip()
            if raw_output.startswith("```json"):
                raw_output = raw_output[8:-3].strip()

            # Load page data as JSON
            page_data = json.loads(raw_output)

            # Merge page_data into combined_output
            merge_dicts(combined_output["Consumer Details"], page_data.get("Consumer Details", {}))
            merge_dicts(combined_output["Billing Summary"], page_data.get("Billing Summary", {}))
            merge_dicts(combined_output["Current Consumption Details"],
                        page_data.get("Current Consumption Details", {}))

        except Exception as e:
            print(f"Error during Gemini API call for {image_path} (page {i + 1}): {e}")

    return combined_output



