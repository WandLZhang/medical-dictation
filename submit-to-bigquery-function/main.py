import functions_framework
from flask import jsonify
from google.cloud import bigquery
import json
import logging
import time
from typing import Dict, Any, List, Tuple

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants
PROJECT_ID = "<redacted>"
DATASET_ID = "health"
TABLE_ID = "usu_procedures"
MAX_CPT_CODES = 10

@functions_framework.http
def submit_to_bigquery(request):
    """HTTP Cloud Function for submitting a medical record to BigQuery."""
    # Handle CORS preflight request
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    # Set CORS headers for the main request
    headers = {
        'Access-Control-Allow-Origin': '*'
    }

    # Parse request data
    request_json = request.get_json(silent=True)
    if not request_json:
        return jsonify({"error": "No JSON data provided"}), 400, headers

    record = request_json.get('record')
    if not record:
        return jsonify({"error": "No record provided"}), 400, headers

    # Validate the record
    is_valid, error_message = validate_record(record)
    if not is_valid:
        return jsonify({"error": f"Invalid record: {error_message}"}), 400, headers

    # Insert the record into BigQuery
    success = insert_into_bigquery_with_retry(record)
    if success:
        return jsonify({"message": "Record successfully inserted into BigQuery"}), 200, headers
    else:
        return jsonify({"error": "Failed to insert record into BigQuery"}), 500, headers

def validate_record(record: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate the structure and content of the record."""
    required_sections = ["patient", "procedure", "coding"]
    for section in required_sections:
        if section not in record:
            return False, f"Missing required section: {section}"

    # Validate patient section
    patient = record.get("patient", {})
    required_patient_fields = ["name", "age", "sex", "medical_record_number"]
    for field in required_patient_fields:
        if not patient.get(field):
            return False, f"Missing required patient field: {field}"

    # Validate procedure section
    procedure = record.get("procedure", {})
    required_procedure_fields = ["date", "location", "procedures_performed"]
    for field in required_procedure_fields:
        if not procedure.get(field):
            return False, f"Missing required procedure field: {field}"

    # Validate coding section
    coding = record.get("coding", {})
    if not coding.get("cpt"):
        return False, "Missing CPT codes in coding section"

    # Validate CPT codes
    is_valid, error_message = validate_cpt_codes(coding.get("cpt", []))
    if not is_valid:
        return False, f"Invalid CPT codes: {error_message}"

    return True, ""

def validate_cpt_codes(cpt_codes: List[Dict[str, str]]) -> Tuple[bool, str]:
    """Validate CPT codes."""
    if not isinstance(cpt_codes, list):
        return False, "CPT codes must be a list"
    if len(cpt_codes) > MAX_CPT_CODES:
        return False, f"Number of CPT codes exceeds the maximum limit of {MAX_CPT_CODES}"
    for code in cpt_codes:
        if not isinstance(code, dict) or 'code' not in code or 'description' not in code:
            return False, "Each CPT code must be a dictionary with 'code' and 'description' fields"
    return True, ""

def insert_into_bigquery_with_retry(record: Dict[str, Any], max_retries: int = 3) -> bool:
    """Insert the record into BigQuery with retry mechanism."""
    client = bigquery.Client()
    table_ref = client.dataset(DATASET_ID, project=PROJECT_ID).table(TABLE_ID)
    
    for attempt in range(max_retries):
        try:
            # Convert the record to match BigQuery schema
            bq_record = {
                "patient": record.get("patient", {}),
                "procedure": {
                    **record.get("procedure", {}),
                    "date": record.get("procedure", {}).get("date"),  # Keep as string
                    "procedures_performed": record.get("procedure", {}).get("procedures_performed", [])
                },
                "coding": {
                    "snomed_ct": record.get("coding", {}).get("snomed_ct", []),
                    "icd_10": record.get("coding", {}).get("icd_10", []),
                    "cpt": record.get("coding", {}).get("cpt", [])
                }
            }
            
            # Serialize the record to JSON
            json_record = json.dumps(bq_record)
            bq_record = json.loads(json_record)  # Deserialize to ensure it's valid JSON

            errors = client.insert_rows_json(table_ref, [bq_record])
            if errors:
                logger.error(f"Errors inserting into BigQuery: {errors}")
                raise Exception(f"BigQuery insertion error: {errors}")
            return True
        except Exception as e:
            logger.error(f"Attempt {attempt + 1} failed: {str(e)}")
            if attempt == max_retries - 1:
                logger.error("Max retries reached. Insertion failed.")
                return False
            time.sleep(2 ** attempt)  # Exponential backoff
    return False

if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google Cloud Functions,
    # a webserver will be used to run the function.
    from flask import Flask, request
    app = Flask(__name__)

    @app.route('/', methods=['POST'])
    def local_submit_to_bigquery():
        return submit_to_bigquery(request)

    app.run(host='localhost', port=8080, debug=True)