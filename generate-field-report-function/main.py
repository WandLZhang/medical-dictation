import functions_framework
from flask import jsonify
import base64
import vertexai
from vertexai.generative_models import GenerativeModel, Part, SafetySetting
import json

# Constants
PROJECT_ID = "<redacted>"
LOCATION = "us-central1"
MODEL_NAME = "gemini-1.5-flash-001"

textsi_1 = """Generate random military physician field reports based on procedures performed. It should read like a spoken dictation with awkward (yet natural) oral wordings. Provide variation in the procedures that would fit into these CPT Category 1 codes:
Evaluation and Management (99202–99499)
Anesthesia (00100–01999)
Surgery (10004–69990) — further broken into smaller groups by body area or system within this code range
Radiology (Including Nuclear Medicine and Diagnostic Ultrasound) (70010–79999)
Pathology and Laboratory (80047–89398)
Medicine (90281–99199, 99500-99607)

# Example output

This is Captain Jane Smith, dictating an operative report for Sergeant John Doe. Uh, let\'s see, he\'s twenty-eight years old, male. Medical record number is one, two, three, four, five, six, seven, eight, nine, zero.

Okay, the date of the procedure was October 27th, 2023. This was performed at Field Surgical Unit Alpha, Operating Room One.

Um, Lieutenant Commander David Lee was the Assistant Surgeon, and Major Emily Brown, CRNA, was the Anesthesiologist.

Preoperative diagnosis: Gunshot wound to the right lower extremity with suspected vascular injury. Postoperative diagnosis: Gunshot wound to the right lower extremity with, uh, it turned out to be a complete transection of the superficial femoral artery.

The procedure we performed was an exploratory laparotomy, a right lower extremity fasciotomy, and a superficial femoral artery repair using an interposition saphenous vein graft.

Now, for the indications... Sergeant Doe presented with a gunshot wound to the right lower leg sustained during combat. On exam, he had diminished distal pulses and, uh, we were concerned about compartment syndrome. Unfortunately, we didn\'t have access to imaging studies due to the field conditions. We felt that urgent surgical exploration was necessary to control the bleeding and, uh, to fully assess and address the vascular and soft tissue injuries.

Okay, so, the procedure... After the patient was placed under general anesthesia, we positioned him supine on the operating table. The right lower extremity was prepped and draped in the usual sterile fashion. We began with a midline laparotomy incision to quickly assess for any intra-abdominal injuries, but, um, thankfully, we didn\'t find any significant injuries there.

Next, we made a longitudinal incision over the course of the superficial femoral artery in the right thigh. We encountered a significant hematoma, and the superficial femoral artery was found to be, as I said, completely transected. We obtained proximal and distal control of the artery.

A right lower extremity fasciotomy was then performed to relieve the compartment pressure. We harvested a saphenous vein graft from the, uh, ipsilateral leg. The transected superficial femoral artery was then repaired using that interposition saphenous vein graft. We used a 6-0 Prolene suture for the anastomosis.

Hemostasis was achieved, and the wound was irrigated with sterile saline solution. We closed the wound in layers using absorbable sutures and applied a sterile dressing.

Estimated blood loss was approximately 800 milliliters. We gave him two liters of lactated Ringer\'s solution.

Uh, no complications. The patient was transferred to a higher level of care for postoperative monitoring and further management.

Prognosis is fair. Uh, he\'s at risk for complications including infection, graft failure, and, uh, potentially limb loss. Close monitoring and aggressive treatment will be necessary.

Recommendations... Continue broad-spectrum antibiotics, serial vascular checks, and monitor for any signs of compartment syndrome. We need to get repeat imaging studies as soon as they become available. Uh, and we\'ll need to consider transfer to a vascular surgery center for definitive management once that\'s possible.

Okay, that concludes this operative report. Dictated by Captain Jane Smith, MD, on October 27th, 2023, at 2200 hours."""

generation_config = {
    "max_output_tokens": 8192,
    "temperature": 1.45,
    "top_p": 0.95,
}

safety_settings = [
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HATE_SPEECH,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
    SafetySetting(
        category=SafetySetting.HarmCategory.HARM_CATEGORY_HARASSMENT,
        threshold=SafetySetting.HarmBlockThreshold.OFF
    ),
]

def generate_field_report():
    vertexai.init(project=PROJECT_ID, location=LOCATION)
    model = GenerativeModel(
        MODEL_NAME,
        system_instruction=[textsi_1]
    )
    responses = model.generate_content(
        ["""generate a field report"""],
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )

    full_response = ""
    for response in responses:
        full_response += response.text

    return full_response

@functions_framework.http
def generate_field_report_http(request):
    """HTTP Cloud Function for generating a field report."""
    # Set CORS headers for the preflight request
    if request.method == 'OPTIONS':
        # Allows GET requests from any origin with the Content-Type
        # header and caches preflight response for an 3600s
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET',
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    # Set CORS headers for the main request
    headers = {
        'Access-Control-Allow-Origin': '*'
    }

    try:
        field_report = generate_field_report()
        return jsonify({"fieldReport": field_report}), 200, headers
    except Exception as e:
        return jsonify({"error": str(e)}), 500, headers

if __name__ == "__main__":
    # This is used when running locally only. When deploying to Google Cloud Functions,
    # a webserver will be used to run the function.
    from flask import Flask, request
    app = Flask(__name__)

    @app.route('/', methods=['GET'])
    def local_generate_field_report():
        return generate_field_report_http(request)

    app.run(host='localhost', port=8080, debug=True)