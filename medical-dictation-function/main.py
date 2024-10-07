import functions_framework
from flask import jsonify, Response
from flask_cors import CORS
import json
import logging
import traceback
from google.cloud import aiplatform
from google.cloud.aiplatform.gapic.schema import predict
from google.protobuf import json_format
from google.protobuf.struct_pb2 import Value
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import re

# Constants
PROJECT_ID = "<redacted>"
DATASET_ID = "health"
TABLE_ID = "usu_procedures"

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize AI Platform client
client_options = {"api_endpoint": "us-central1-aiplatform.googleapis.com"}
client = aiplatform.gapic.PredictionServiceClient(client_options=client_options)

# JSON schema for BigQuery record
RECORD_SCHEMA: Dict[str, Any] = {
    "patient": {
        "name": "",
        "age": 0,
        "sex": "",
        "medical_record_number": ""
    },
    "procedure": {
        "date": "",
        "location": "",
        "preoperative_diagnosis": "",
        "postoperative_diagnosis": "",
        "procedures_performed": [],
        "surgeon": "",
        "assistant_surgeon": "",
        "anesthesiologist": "",
        "estimated_blood_loss": "",
        "fluids_administered": "",
        "complications": "",
        "disposition": ""
    },
    "coding": {
        "snomed_ct": [],
        "icd_10": [],
        "cpt": []
    }
}

class PromptGenerator:
    def __init__(self):
        self.required_fields = [
            "patient.name",
            "patient.age",
            "patient.sex",
            "patient.medical_record_number",
            "procedure.date",
            "procedure.location",
            "procedure.preoperative_diagnosis",
            "procedure.postoperative_diagnosis",
            "procedure.procedures_performed",
            "procedure.surgeon",
            "coding.cpt"
        ]

    def get_next_prompt(self, current_record: Dict[str, Any]) -> Optional[Dict[str, str]]:
        for field in self.required_fields:
            if not self.is_field_complete(current_record, field):
                # Format the field name for better readability
                formatted_field = field.replace('.', ' ').replace('_', ' ').title()
                return {"field": field, "prompt": f"Please provide the {formatted_field}:"}
        return None

    @staticmethod
    def is_field_complete(record: Dict[str, Any], field: str) -> bool:
        keys = field.split('.')
        value = record
        for key in keys:
            value = value.get(key, {})
        return bool(value)

prompt_generator = PromptGenerator()

def create_prompt(user_message: str, current_record: Dict[str, Any], current_prompt: Optional[Dict[str, str]]) -> str:
    return f"""
    ## SYSTEM INSTRUCTIONS
    Purpose: This LLM is designed to assist in updating specific fields of a medical record based on user input, including generating appropriate SNOMED CT and ICD-10 codes for diagnoses and procedures.

    Input: The LLM will accept free-text input related to a specific field in the medical record.

    Output: The LLM will generate a JSON object containing only the fields that were updated based on the user's input, including SNOMED CT and ICD-10 codes when relevant medical information is provided.

    Special Instructions:
    1. When procedures or diagnoses are mentioned, update the 'procedure.procedures_performed' field and generate appropriate codes in the 'coding' section.
    2. Do not insert codes directly into the 'procedure' section fields. All codes should be placed in the 'coding' section.
    3. For CPT, SNOMED CT, and ICD-10 codes, provide both the code and its description in the following format:
       {{"code": "12345", "description": "Description of the procedure or diagnosis"}}
    4. For dates, always format them as strings in YYYY-MM-DD format (e.g., "2024-10-02" for October 2, 2024).
    5. Pay special attention to preoperative and postoperative diagnoses, procedures performed, and any mentioned complications or conditions.
    6. Focus on filling the missing required fields for BigQuery insertion.
    7. Do not use comments in the JSON response.
    8. Ensure all property names are enclosed in double quotes.
    9. Maintain proper JSON structure, especially for arrays and nested objects.
    10. For 'preoperative_diagnosis' and 'postoperative_diagnosis', provide a single string value, not an array.

    Current Record State:
    {json.dumps(current_record, indent=2)}

    Current Prompt:
    {json.dumps(current_prompt, indent=2)}

    ## USER MESSAGE
    {user_message}

    ## ASSISTANT RESPONSE
    Based on the user's input, please update the relevant fields in the record, including generating appropriate SNOMED CT and ICD-10 codes for any mentioned diagnoses or procedures. Focus on filling the missing required fields. Do not add or modify any information that was not explicitly provided by the user. Your response should be a valid JSON object with the following structure:
    {{
        "updated_record": {{
            "patient": {{
                "field_name": "value"
            }},
            "procedure": {{
                "field_name": "value",
                "preoperative_diagnosis": "Single string diagnosis",
                "postoperative_diagnosis": "Single string diagnosis",
                "procedures_performed": [
                    "Procedure 1",
                    "Procedure 2"
                ]
            }},
            "coding": {{
                "cpt": [
                    {{"code": "12345", "description": "Description of procedure 1"}},
                    {{"code": "67890", "description": "Description of procedure 2"}}
                ],
                "snomed_ct": [
                    {{"code": "123456789", "description": "SNOMED CT description 1"}},
                    {{"code": "987654321", "description": "SNOMED CT description 2"}}
                ],
                "icd_10": [
                    {{"code": "A12.3", "description": "ICD-10 description 1"}},
                    {{"code": "B45.6", "description": "ICD-10 description 2"}}
                ]
            }}
        }},
        "message": "Your response message here"
    }}
    """

def merge_user_input(current_record: Dict[str, Any], user_input: Dict[str, Any]) -> Dict[str, Any]:
    """Merge user input with the current record, updating only provided fields."""
    for section, data in user_input.items():
        if section in current_record:
            if section == "coding":
                for coding_type, codes in data.items():
                    if coding_type in current_record[section]:
                        # Merge new codes with existing ones, avoiding duplicates
                        existing_codes = {code['code']: code for code in current_record[section][coding_type]}
                        for new_code in codes:
                            existing_codes[new_code['code']] = new_code
                        current_record[section][coding_type] = list(existing_codes.values())
            else:
                for field, value in data.items():
                    if field in current_record[section]:
                        if field == "date" and not validate_date(value):
                            logger.warning(f"Invalid date format: {value}. Skipping update.")
                            continue
                        if field in ["preoperative_diagnosis", "postoperative_diagnosis"]:
                            # Ensure diagnosis fields are always strings
                            current_record[section][field] = "; ".join(value) if isinstance(value, list) else str(value)
                        else:
                            current_record[section][field] = value
    return current_record

def generate_content(prompt: str) -> str:
    """Generate content using the medlm-large model."""
    logger.info("Generating content using the medlm-large model.")
    instance_dict = {"content": prompt}
    instance = json_format.ParseDict(instance_dict, Value())
    instances = [instance]
    parameters_dict = {
        "candidateCount": 1,
        "maxOutputTokens": 1024,
        "temperature": 0,
        "topP": 0.8,
        "topK": 40
    }
    parameters = json_format.ParseDict(parameters_dict, Value())
    response = client.predict(
        endpoint="projects/<redacted>/locations/us-central1/publishers/google/models/medlm-large",
        instances=instances,
        parameters=parameters
    )
    predictions = response.predictions
    for prediction in predictions:
        return dict(prediction)["content"]

def is_record_complete(record: Dict[str, Any]) -> bool:
    """Check if the record is complete based on required fields."""
    required_fields = [
        "patient.name",
        "patient.age",
        "patient.sex",
        "procedure.date",
        "procedure.location",
        "procedure.procedures_performed",
        "coding.cpt"
    ]
    for field in required_fields:
        keys = field.split('.')
        value = record
        for key in keys:
            value = value.get(key, {})
        if not value:
            return False
    return True

def validate_date(date_string: str) -> bool:
    """Validate if a string is in YYYY-MM-DD format."""
    try:
        datetime.strptime(date_string, "%Y-%m-%d")
        return True
    except ValueError:
        return False

def validate_input(user_message: str, current_record: Dict[str, Any]) -> Tuple[bool, str]:
    """Validate user input and current record."""
    if not user_message.strip():
        return False, "User message cannot be empty."
    if not isinstance(current_record, dict):
        return False, "Invalid current record format."
    # Add more validation as needed
    return True, ""

import re

def sanitize_json_string(json_string: str) -> str:
    """Sanitize the JSON string to ensure it's valid."""
    # Remove any potential Unicode BOM
    json_string = json_string.strip().lstrip('\ufeff')
    
    # Remove any leading/trailing whitespace
    json_string = json_string.strip()
    
    # Remove any comments (single-line or multi-line)
    json_string = re.sub(r'//.*?$|/\*.*?\*/', '', json_string, flags=re.MULTILINE | re.DOTALL)
    
    # Parse the JSON string
    try:
        parsed_json = json.loads(json_string)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {str(e)}")
    
    # Custom JSON encoder to handle escaping
    class CustomJSONEncoder(json.JSONEncoder):
        def encode(self, obj):
            if isinstance(obj, str):
                return json.dumps(obj, ensure_ascii=False)
            return super().encode(obj)
    
    # Re-serialize the JSON with proper escaping
    sanitized_json = json.dumps(parsed_json, cls=CustomJSONEncoder, ensure_ascii=False, indent=2)
    
    return sanitized_json

@functions_framework.http
def medical_record_assistant(request):
    """HTTP Cloud Function for medical record creation using medlm-large model."""
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

    # Extract required data from request
    user_message: str = request_json.get('userMessage')
    current_record: Dict[str, Any] = request_json.get('currentRecord', RECORD_SCHEMA)
    current_prompt: Optional[Dict[str, str]] = request_json.get('currentPrompt')

    # Validate input
    is_valid, error_message = validate_input(user_message, current_record)
    if not is_valid:
        return jsonify({"error": error_message}), 400, headers

    # Prepare the input for the main medlm-large query
    main_prompt = create_prompt(user_message, current_record, current_prompt)

    # Generate content using medlm-large
    try:
        response_text = generate_content(main_prompt)
        sanitized_response = sanitize_json_string(response_text)
        response_json = json.loads(sanitized_response)
        
        if isinstance(response_json, dict) and "updated_record" in response_json:
            updated_record = merge_user_input(current_record, response_json["updated_record"])
            
            record_complete = is_record_complete(updated_record)
            next_prompt = prompt_generator.get_next_prompt(updated_record)
            
            response_json['updated_record'] = updated_record
            response_json['next_prompt'] = next_prompt
            response_json['ready_to_insert'] = record_complete

            # Provide a message to confirm submission when the record is complete
            if record_complete:
                response_json['message'] = "The record is complete. You can now submit it to BigQuery or continue adding more information."
            else:
                response_json['message'] = response_json.get('message', '').strip()
        else:
            raise ValueError("Invalid response structure from medlm-large model")
        
        return jsonify(response_json), 200, headers
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding JSON: {str(e)}")
        logger.error(f"Raw response: {response_text}")
        logger.error(f"Sanitized response: {sanitized_response}")
        return jsonify({"error": f"Error decoding JSON response: {str(e)}"}), 500, headers
    except Exception as e:
        logger.error(f"Error generating response: {str(e)}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return jsonify({"error": "An unexpected error occurred. Please try again later."}), 500, headers

if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google Cloud Functions,
    # a webserver will be used to run the function.
    from flask import Flask, request
    app = Flask(__name__)
    CORS(app)  # Enable CORS for all routes when running locally
    
    @app.route('/', methods=['POST'])
    def local_medical_record_assistant():
        return medical_record_assistant(request)
    
    app.run(host='localhost', port=8080, debug=True)