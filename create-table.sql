CREATE TABLE `<redacted>.health.usu_procedures` (
  patient STRUCT<
    name STRING,
    age INT64,
    sex STRING,
    medical_record_number STRING
  >,
  procedure STRUCT<
    date DATE,
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
    snomed_ct ARRAY<STRUCT<
      code STRING,
      description STRING
    >>,
    icd_10 ARRAY<STRUCT<
      code STRING,
      description STRING
    >>,
    cpt ARRAY<STRUCT<
      code STRING,
      description STRING
    >> 
  >
);
