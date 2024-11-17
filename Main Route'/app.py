import json, os
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from werkzeug.utils import secure_filename, send_from_directory
from Ebill.ebill_Main import get_cost_saving_from_output, ebill_gemini_output, ebill_pdf_to_image
from invoice_po.po_Main import fetch_po_details, compare_data, trim_and_convert, po_pdf_to_image, po_gemini_output  # Invoice/PO functions
from KYC_doc.kyc_Main import process_file,save_data_to_db

app = Flask(__name__)
app.secret_key = 'your_secret_key'
UPLOAD_FOLDER = 'uploads'
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/invoice', methods=['GET', 'POST'])
def upload_invoice():
    if request.method == 'POST':
        file = request.files['file']
        if file and file.filename.endswith('.pdf'):
            filename = secure_filename(file.filename)
            pdf_path = os.path.join(app.root_path, app.config['UPLOAD_FOLDER'], filename)
            file.save(pdf_path)  # Save the uploaded PDF

            # Convert PDF to images
            image_paths = po_pdf_to_image(pdf_path)

            output_json = po_gemini_output(image_paths[0])

            # Parse the output JSON
            try:
                json_data = json.loads(output_json)
            except json.JSONDecodeError as e:
                flash(f"Error parsing JSON: {e}")
                return redirect(request.url)

            # Fetch PO details from DB and compare
            po_number = trim_and_convert(json_data.get('poNumber', ''))
            db_data = fetch_po_details(po_number)
            comparison_results, product_comparisons = compare_data(json_data, db_data)

            return render_template('po_results.html', comparison_results=comparison_results, product_comparisons=product_comparisons)

    return render_template('po_upload.html')

@app.route('/kyc', methods=['GET', 'POST'])
def upload_kyc():
    return render_template('kyc_upload.html')

@app.route('/kyc/upload_file', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file part')
        return redirect(request.url)

    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(request.url)

    filename = secure_filename(file.filename)
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(file_path)

    # Process the uploaded file and extract data (replace with actual extraction logic)
    extracted_data = process_file(file_path)  # You should define the process_file function

    if extracted_data:
        session['extracted_data'] = extracted_data
        session['filename'] = filename
        return render_template('kyc_result.html', data=extracted_data, filename=filename)
    else:
        flash("Error extracting data from file.")
        return redirect(url_for('upload_form'))

@app.route('/kyc/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/kyc/save_data', methods=['POST'])
def save_data():
    try:
        extracted_data = session.get('extracted_data')
        if not extracted_data:
            return jsonify({'error': 'No extracted data found'}), 400

        save_data_to_db(extracted_data)  # Define this function to save data to the database
        session.pop('extracted_data', None)

        return jsonify({'message': 'Data saved successfully!'}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/electricity_bill', methods=['GET', 'POST'])
def electricity_bill():
    return render_template('ebill_upload.html')


@app.route('/electricity_bill/pdf_upload', methods=['POST'])
def pdf_upload():
    if 'pdf_file' not in request.files:
        flash('No file part')
        return redirect(request.url)
    pdf_file = request.files['pdf_file']
    if pdf_file.filename == '':
        flash('No selected file')
        return redirect(request.url)
    if pdf_file:
        pdf_path = os.path.join(UPLOAD_FOLDER, pdf_file.filename)
        pdf_file.save(pdf_path)

        # Process the PDF to images
        image_paths = ebill_pdf_to_image(pdf_path)
        if not image_paths:
            flash("No images were generated from the PDF.")
            return redirect(url_for('index'))

        # Get the Gemini output
        output_json = ebill_gemini_output(image_paths)
        if output_json:
            # Store extracted data in session for later use in save_data route
            session['extracted_data'] = output_json
            # session['filename'] = filename

        if output_json is None:
            flash("Failed to get Gemini output.")
            return redirect(url_for('index'))

        # Store output_json as a string in session
        session['output_json'] = json.dumps(output_json)

        # Parse the JSON string back into a dictionary before passing to the template
        parsed_output_json = json.loads(session['output_json'])

        # Render the result page with the parsed output JSON
        return render_template('ebill_result.html', output_json=parsed_output_json, pdf_path=pdf_path)
    return redirect(url_for('index'))

@app.route('/calculate_saving', methods=['POST'])
def calculate_saving():
    try:
        output_json = session.get('extracted_data')
        rate = float(output_json["Current Consumption Details"].get("Rate", 0))
        cost_saving = get_cost_saving_from_output(output_json)
        return render_template('ebill_result.html',rate = rate, cost_saving=cost_saving, output_json=output_json)
    except Exception as e:
        return str(e), 400
if __name__ == '__main__':
    app.run(debug=True, port=3000)

