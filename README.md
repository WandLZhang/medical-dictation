# Medical Coding App

A web application for medical procedure dictation and coding, powered by Gemini and MedLM

## Overview

This application helps medical professionals dictate procedure reports and automatically generates medical codes (CPT, SNOMED CT, ICD-10). It features speech-to-text, automatic coding suggestions, and secure data storage in BigQuery.

## Setup Instructions

### 1. BigQuery Table Setup

```sql
CREATE TABLE `health.usu_procedures`
(
  patient STRUCT<
    name STRING,
    age INT64,
    sex STRING,
    medical_record_number STRING
  >,
  procedure STRUCT<
    date STRING,
    location STRING,
    preoperative_diagnosis STRING,
    postoperative_diagnosis STRING,
    procedures_performed ARRAY<STRING>,
    surgeon STRING,
    assistant_surgeon STRING,
    anesthesiologist STRING,
    estimated_blood_loss STRING,
    fluids_administered STRING,
    complications STRING,
    disposition STRING
  >,
  coding STRUCT<
    snomed_ct ARRAY<STRUCT<code STRING, description STRING>>,
    icd_10 ARRAY<STRUCT<code STRING, description STRING>>,
    cpt ARRAY<STRUCT<code STRING, description STRING>>
  >
);
```

### 2. Cloud Functions Deployment

Deploy the three backend functions:

```bash
# Medical Dictation Function
gcloud functions deploy medical-dictation-function \
    --runtime python312 \
    --region=us-central1 \
    --memory=1024MB \
    --trigger-http \
    --entry-point=medical_record_assistant

# Generate Field Report Function
gcloud functions deploy generate-field-report \
    --runtime python312 \
    --region=us-central1 \
    --memory=512MB \
    --trigger-http \
    --entry-point=generate_field_report_http

# Submit to BigQuery Function
gcloud functions deploy submit-to-bigquery \
    --runtime python312 \
    --region=us-central1 \
    --memory=256MB \
    --trigger-http \
    --entry-point=submit_to_bigquery
```

Allow public access to the functions:

```bash
# Grant public access to each function
gcloud functions add-invoker-policy-binding medical-dictation-function \
    --region="us-central1" \
    --member="allUsers"

gcloud functions add-invoker-policy-binding generate-field-report \
    --region="us-central1" \
    --member="allUsers"

gcloud functions add-invoker-policy-binding submit-to-bigquery \
    --region="us-central1" \
    --member="allUsers"
```

### 3. Frontend Deployment

1. Go to [Firebase Console](https://console.cloud.google.com/firebase)
2. Click "Get Started" for Firebase App Hosting
3. In the Firebase console, click the "Web App" option near your project ID
4. Enter an app nickname and register the app
5. Deploy using Firebase CLI:

```bash
# Login to Firebase
firebase login

# Initialize Firebase project
firebase init

# Select options:
# - Choose "Hosting: Configure files for Firebase hosting"
# - Select "Use an existing project"
# - Use "public" as your public folder
# - Configure as single-page app: Yes
# - Set up automatic builds with GitHub: No
# - Don't overwrite existing files

# Deploy the application
firebase deploy
```

## Project Structure

- `frontend/`: Web application files
  - `app.js`: Main application logic
  - `index.html`: Main HTML file
  - `styles.css`: Application styling
  
- Cloud Functions:
  - `medical-dictation-function/`: Main dictation processing
  - `generate-field-report/`: Field report generation
  - `submit-to-bigquery/`: BigQuery data submission

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
