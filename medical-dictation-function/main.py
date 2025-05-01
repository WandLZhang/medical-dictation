import functions_framework
from flask import jsonify, Response
from flask_cors import CORS
import json
import logging
import traceback
from google import genai
from google.genai import types
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import re
import time
import os

# Constants
PROJECT_ID = "wz-data-catalog-demo"
DATASET_ID = "health"
TABLE_ID = "usu_procedures"

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Gemini client
client = genai.Client(
    vertexai=True,
    project=PROJECT_ID,
    location="us-central1",
)

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
    """Generate content using the Gemini 2.0 model."""
    logger.info("Generating content using the Gemini 2.0 model.")
    
    # Add explicit JSON-only instruction to the prompt
    prompt += "\n\nIMPORTANT: Return ONLY the raw JSON object. Do not include any explanatory text, markdown formatting, or code blocks. The response should start with '{' and end with '}' with no other characters before or after."
    
    # Create content for Gemini
    contents = [
        types.Content(
            role="user",
            parts=[{"text": prompt}]
        )
    ]

    # Configure Gemini model - optimized for JSON generation
    model = "gemini-2.0-flash-001"
    generate_content_config = types.GenerateContentConfig(
        temperature=0,
        top_p=0.95,
        candidate_count=1,
        max_output_tokens=8192,
        response_modalities=["TEXT"],
        safety_settings=[
            types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF"
            ),
            types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF"
            )
        ]
    )

    # Initialize retry parameters
    base_delay = 5  # Start with 5 seconds
    max_attempts = 3
    attempt = 0
    
    # Retry logic for handling rate limits
    while attempt < max_attempts:
        try:
            # Generate response using Gemini
            response = client.models.generate_content(
                model=model,
                contents=contents,
                config=generate_content_config,
            )
            
            # Print the raw response for debugging (visible in cloud function logs)
            print("========== RAW GEMINI RESPONSE START ==========")
            print(response.text)
            print("========== RAW GEMINI RESPONSE END ============")
            
            return response.text.strip()
            
        except Exception as e:
            error_str = str(e)
            if "429 RESOURCE_EXHAUSTED" in error_str:
                attempt += 1
                # Calculate exponential backoff delay
                delay = min(base_delay * (2 ** (attempt - 1)), 60)  # Cap at 60 seconds
                print(f"Rate limited. Attempt {attempt} of {max_attempts}. Waiting {delay} seconds...")
                time.sleep(delay)
            else:
                # If it's not a rate limit error, re-raise
                print(f"ERROR GENERATING CONTENT: {error_str}")
                raise
    
    # If we've exhausted all retries
    raise Exception(f"Failed to generate content after {max_attempts} attempts due to rate limiting")

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
    if not json_string or not json_string.strip():
        logger.error("Empty JSON string received")
        return '{}'
    
    # Print the raw input for debugging (visible in cloud function logs)
    print("========== JSON INPUT START ==========")
    print(json_string[:500] + ("..." if len(json_string) > 500 else ""))
    print("========== JSON INPUT END ============")
    
    # Remove any potential Unicode BOM
    json_string = json_string.strip().lstrip('\ufeff')
    
    # Remove any leading/trailing whitespace
    json_string = json_string.strip()
    
    # Remove any comments (single-line or multi-line)
    json_string = re.sub(r'//.*?$|/\*.*?\*/', '', json_string, flags=re.MULTILINE | re.DOTALL)
    
    # Try to extract JSON content using different strategies
    cleaned_text = json_string
    
    # First try to find JSON between ```json and ``` markers (markdown code blocks)
    if '```json' in cleaned_text or '```' in cleaned_text:
        print("Attempting to extract JSON from markdown code block")
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned_text)
        if match:
            cleaned_text = match.group(1).strip()
            print(f"Extracted JSON from code block: {cleaned_text[:100]}...")
    
    # If that fails or if we still don't have valid JSON, try to find JSON between { and }
    if not cleaned_text.startswith('{') or not cleaned_text.endswith('}'):
        print("Attempting to extract JSON between curly braces")
        if '{' in cleaned_text and '}' in cleaned_text:
            start = cleaned_text.find('{')
            end = cleaned_text.rfind('}') + 1
            if start >= 0 and end > start:
                cleaned_text = cleaned_text[start:end]
                print(f"Extracted JSON between braces: {cleaned_text[:100]}...")
    
    # Parse the JSON string
    try:
        print("Attempting to parse JSON")
        parsed_json = json.loads(cleaned_text)
        print("Successfully parsed JSON")
    except json.JSONDecodeError as e:
        print(f"JSON PARSING ERROR: {str(e)}")
        print(f"ERROR CONTEXT: {cleaned_text[max(0, e.pos-50):min(len(cleaned_text), e.pos+50)]}")
        
        # Try to recover by wrapping the response in a standard structure
        try:
            # First attempt: Fix common issues like unescaped quotes
            fixed_text = re.sub(r'(?<!\\)"(?=(,|\s*}|\s*]|\s*:))', '\\"', cleaned_text)
            parsed_json = json.loads(fixed_text)
            print("Successfully parsed JSON after fixing quotes")
        except json.JSONDecodeError:
            try:
                # Second attempt: Create a fallback object with the raw text
                escaped_text = cleaned_text.replace('"', '\\"').replace('\n', '\\n')
                fallback_json = f'{{"message": "Error parsing model response", "raw_text": "{escaped_text}"}}'
                parsed_json = json.loads(fallback_json)
                print("Using fallback JSON structure")
            except:
                # If all else fails, return a simple error object
                print("ALL JSON PARSING ATTEMPTS FAILED")
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
    """HTTP Cloud Function for medical record creation using Gemini 2.0 model."""
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

    # Prepare the input for the Gemini 2.0 query
    main_prompt = create_prompt(user_message, current_record, current_prompt)

    # Generate content using Gemini 2.0
    try:
        response_text = generate_content(main_prompt)
        sanitized_response = sanitize_json_string(response_text)
        response_json = json.loads(sanitized_response)
        
        # Print the response for debugging (visible in cloud function logs)
        print("========== PARSED RESPONSE JSON START ==========")
        print(json.dumps(response_json, indent=2)[:1000])
        print("========== PARSED RESPONSE JSON END ============")
        
        # Auto-fix the structure if it doesn't have the expected format
        if isinstance(response_json, dict) and "updated_record" not in response_json:
            # If we have direct fields like 'procedure', 'patient', or 'coding', they should be wrapped
            record_fields = ['procedure', 'patient', 'coding']
            has_direct_fields = any(field in response_json for field in record_fields)
            
            if has_direct_fields:
                print("Response has direct fields without 'updated_record' wrapper - auto-fixing structure")
                # Create a properly structured response by wrapping the current response
                fixed_response = {
                    "updated_record": {},
                    "message": "Processed user input and updated fields."
                }
                
                # Copy all record-related fields into updated_record
                for field in record_fields:
                    if field in response_json:
                        fixed_response["updated_record"][field] = response_json[field]
                
                # For any other fields that aren't part of the record structure, copy them at the top level
                for key, value in response_json.items():
                    if key not in record_fields:
                        fixed_response[key] = value
                
                # Replace the response with our fixed version
                print("Fixed response structure:")
                print(json.dumps(fixed_response, indent=2)[:1000])
                response_json = fixed_response
        
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
            # Handle invalid response structure with detailed print statements
            print("CRITICAL ERROR: Invalid response structure from Gemini 2.0 model")
            print(f"Keys found in response: {list(response_json.keys()) if isinstance(response_json, dict) else 'not a dict'}")
            print(f"FULL RAW GEMINI RESPONSE: {response_text}")
            
            # Create a fallback response with the raw Gemini output for debugging
            error_response = {
                "error": "Invalid response structure from Gemini model",
                "raw_gemini_response": response_text,
                "parsed_json": response_json if isinstance(response_json, dict) else str(response_json),
                "debug_info": "The model did not return the expected 'updated_record' structure"
            }
            return jsonify(error_response), 500, headers
        
        return jsonify(response_json), 200, headers
    except json.JSONDecodeError as e:
        print(f"ERROR DECODING JSON: {str(e)}")
        print(f"RAW RESPONSE: {response_text}")
        print(f"SANITIZED RESPONSE: {sanitized_response}")
        return jsonify({"error": f"Error decoding JSON response: {str(e)}"}), 500, headers
    except Exception as e:
        print(f"ERROR GENERATING RESPONSE: {str(e)}")
        print(f"TRACEBACK: {traceback.format_exc()}")
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
