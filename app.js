// Application State
let currentRecord = {
    patient: {
        name: "",
        age: 0,
        sex: "",
        medical_record_number: ""
    },
    procedure: {
        date: "",
        location: "",
        preoperative_diagnosis: "",
        postoperative_diagnosis: "",
        procedures_performed: [],
        surgeon: "",
        assistant_surgeon: ""
    },
    coding: {
        snomed_ct: [],
        icd_10: [],
        cpt: []
    }
};
let chatHistory = [];
let isListening = false;
let recognition;

// DOM Elements
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const micBtn = document.getElementById('micBtn');
const enterBtn = document.getElementById('enterBtn');
const signInBtn = document.getElementById('signInBtn');
const preGenerateBtn = document.getElementById('preGenerateBtn');
const loadingSpinner = document.getElementById('loadingSpinner');

// Progress Bar Elements
const patientProgressBar = document.getElementById('patient-progress');
const procedureProgressBar = document.getElementById('procedure-progress');
const codingProgressBar = document.getElementById('coding-progress');

// Completion Box Elements
const completionBoxes = {
    patient: ['name', 'age', 'sex'],
    procedure: ['date', 'location', 'preoperative_diagnosis', 'postoperative_diagnosis', 'procedures_performed', 'surgeon', 'assistant_surgeon'],
    coding: ['cpt', 'snomed_ct', 'icd_10']
};

// Event Listeners
chatInput.addEventListener('keypress', handleChatInputKeypress);
micBtn.addEventListener('click', toggleSpeechRecognition);
enterBtn.addEventListener('click', sendChatMessage);
signInBtn.addEventListener('click', toggleSignIn);
preGenerateBtn.addEventListener('click', generateFieldReport);

// Functions
function handleChatInputKeypress(event) {
    if (event.key === 'Enter') {
        sendChatMessage();
    }
}

function toggleSpeechRecognition() {
    if (!recognition) {
        initializeSpeechRecognition();
    }

    if (isListening) {
        recognition.stop();
        micBtn.classList.remove('active');
    } else {
        recognition.start();
        micBtn.classList.add('active');
    }

    isListening = !isListening;
}

function initializeSpeechRecognition() {
    if ('webkitSpeechRecognition' in window) {
        recognition = new webkitSpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onstart = () => {
            console.log('Speech recognition started');
        };

        recognition.onresult = (event) => {
            const transcript = event.results[0][0].transcript;
            chatInput.value = transcript;
            sendChatMessage();
        };

        recognition.onerror = (event) => {
            console.error('Speech recognition error', event.error);
            micBtn.classList.remove('active');
            isListening = false;
        };

        recognition.onend = () => {
            console.log('Speech recognition ended');
            micBtn.classList.remove('active');
            isListening = false;
        };
    } else {
        console.error('Speech recognition not supported in this browser');
        micBtn.style.display = 'none';
    }
}

async function sendChatMessage() {
    const message = chatInput.value.trim();
    if (message) {
        addMessageToChat('user', message);
        chatInput.value = '';
        chatHistory.push({ role: 'user', content: message });
        
        showLoadingSpinner();
        
        try {
            const response = await callCloudFunction(message);
            console.log('Cloud function response:', response);

            if (response && typeof response === 'object') {
                if (response.message) {
                    addMessageToChat('bot', response.message);
                    chatHistory.push({ role: 'assistant', content: response.message });
                }
                
                if (response.updated_record) {
                    updateCurrentRecord(response.updated_record);
                    console.log('Updated record:', currentRecord);
                    updateProgressBars();
                    updateCompletionBoxes();
                }
                
                if (response.ready_to_insert) {
                    console.log('Record is complete and ready to insert');
                    addSubmitButton();
                }
                
                if (response.next_prompt) {
                    addMessageToChat('bot', response.next_prompt.prompt);
                }
            } else {
                throw new Error('Invalid response structure from cloud function');
            }
        } catch (error) {
            console.error('Error in sendChatMessage:', error);
            addMessageToChat('bot', `An error occurred: ${error.message}`);
        } finally {
            hideLoadingSpinner();
        }
    }
}

function updateCurrentRecord(updatedRecord) {
    // Merge the updated record with the current record
    for (const section in updatedRecord) {
        if (currentRecord.hasOwnProperty(section)) {
            currentRecord[section] = {
                ...currentRecord[section],
                ...updatedRecord[section]
            };
        }
    }
}

function addMessageToChat(sender, message) {
    const messageElement = document.createElement('div');
    messageElement.className = `mb-4 ${sender === 'user' ? 'text-right' : 'text-left'}`;
    
    let parsedMessage;
    try {
        parsedMessage = marked.parse(message || '');
    } catch (error) {
        console.error('Error parsing markdown:', error);
        parsedMessage = 'Error displaying message';
    }
    
    messageElement.innerHTML = `
        <span class="inline-block bg-${sender === 'user' ? 'blue' : 'gray'}-200 rounded px-4 py-2 max-w-3/4">
            ${parsedMessage}
        </span>
    `;

    chatMessages.appendChild(messageElement);
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addSubmitButton() {
    const submitButton = document.createElement('button');
    submitButton.textContent = 'Submit to BigQuery';
    submitButton.className = 'submit-bigquery-btn mt-2 bg-green-500 hover:bg-green-600 text-white font-bold py-2 px-4 rounded';
    submitButton.addEventListener('click', submitToBigQuery);
    
    const lastMessage = chatMessages.lastElementChild;
    if (lastMessage) {
        lastMessage.appendChild(submitButton);
    } else {
        chatMessages.appendChild(submitButton);
    }
}

async function callCloudFunction(userMessage) {
    const cloudFunctionUrl = 'https://us-central1-<redacted>.cloudfunctions.net/medical-dictation-function';

    const payload = {
        userMessage: userMessage,
        currentRecord: currentRecord,
        chatHistory: chatHistory
    };
    
    try {
        const response = await fetch(cloudFunctionUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        return await response.json();
    } catch (error) {
        console.error('Error calling cloud function:', error);
        throw error;
    }
}

function toggleSignIn() {
    const isSignedIn = signInBtn.textContent === 'Sign Out';
    signInBtn.textContent = isSignedIn ? 'Sign In' : 'Sign Out';
    console.log(isSignedIn ? 'User signed out' : 'User signed in');
    // Implement actual sign-in/sign-out logic here
}

function updateProgressBars() {
    const patientProgress = calculateSectionProgress(currentRecord.patient);
    const procedureProgress = calculateSectionProgress(currentRecord.procedure);
    const codingProgress = calculateSectionProgress(currentRecord.coding);

    updateProgressBar(patientProgressBar, patientProgress, 'Patient Info', currentRecord.patient);
    updateProgressBar(procedureProgressBar, procedureProgress, 'Procedure Details', currentRecord.procedure);
    updateProgressBar(codingProgressBar, codingProgress, 'Coding', currentRecord.coding);
}

function calculateSectionProgress(section) {
    if (!section || typeof section !== 'object') {
        console.error('Invalid section provided to calculateSectionProgress:', section);
        return 0;
    }

    const totalFields = Object.keys(section).length;
    if (totalFields === 0) return 0;

    const filledFields = Object.values(section).filter(value => {
        if (Array.isArray(value)) {
            return value.length > 0;
        }
        return value !== "" && value !== 0 && value != null;
    }).length;

    return (filledFields / totalFields) * 100;
}

function updateProgressBar(progressBar, percentage, sectionName, sectionData) {
    if (progressBar) {
        progressBar.style.width = `${percentage}%`;
        const completedItems = Object.values(sectionData).filter(value => {
            if (Array.isArray(value)) return value.length > 0;
            return value !== "" && value !== 0 && value != null;
        }).length;
        const totalItems = Object.keys(sectionData).length;
        progressBar.setAttribute('data-tooltip', `<strong>${sectionName}:</strong><br>${percentage.toFixed(1)}% complete<br>${completedItems} / ${totalItems} items completed`);
    } else {
        console.error('Progress bar element not found');
    }
}

function updateCompletionBoxes() {
    for (const [section, fields] of Object.entries(completionBoxes)) {
        fields.forEach(field => {
            const boxElement = document.getElementById(`${section}-${field}-box`);
            if (boxElement) {
                const isCompleted = isFieldCompleted(currentRecord[section], field);
                boxElement.classList.toggle('completed', isCompleted);
                if (isCompleted) {
                    const value = getFieldValue(currentRecord[section], field);
                    const originalLabel = boxElement.textContent;
                    boxElement.setAttribute('data-tooltip', `<strong>${originalLabel}:</strong><br>${value}`);
                } else {
                    boxElement.setAttribute('data-tooltip', '');
                }
            }
        });
    }
}

function isFieldCompleted(section, field) {
    const value = section[field];
    if (Array.isArray(value)) {
        return value.length > 0;
    }
    return value !== "" && value !== 0 && value != null && value !== undefined;
}

function getFieldValue(section, field) {
    const value = section[field];
    if (Array.isArray(value)) {
        return value.length > 0 ? formatArrayValue(value) : '';
    }
    return value ? value.toString() : '';
}

function formatArrayValue(arr) {
    return arr.map(item => {
        if (typeof item === 'object' && item !== null) {
            return `${item.code}: ${item.description}`;
        }
        return item.toString();
    }).join('<br>');
}

async function submitToBigQuery() {
    const submitUrl = 'https://us-central1-<redacted>.cloudfunctions.net/submit-to-bigquery';
    
    showLoadingSpinner();
    
    try {
        const response = await fetch(submitUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ record: currentRecord }),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        addMessageToChat('bot', result.message || 'Record submitted successfully to BigQuery');
        
        // Reset the current record and update UI
        currentRecord = JSON.parse(JSON.stringify(currentRecord));
        updateProgressBars();
        updateCompletionBoxes();
    } catch (error) {
        console.error('Error submitting to BigQuery:', error);
        addMessageToChat('bot', `Error submitting to BigQuery: ${error.message}`);
    } finally {
        hideLoadingSpinner();
    }
}

async function generateFieldReport() {
    const generateUrl = 'https://us-central1-<redacted>.cloudfunctions.net/generate-field-report';
    
    showLoadingSpinner();
    
    try {
        const response = await fetch(generateUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ currentRecord: currentRecord }),
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const result = await response.json();
        if (result.fieldReport) {
            chatInput.value = result.fieldReport;
            addMessageToChat('bot', 'Sample field report generated. You can edit it before sending.');
        } else {
            throw new Error('No field report generated');
        }
    } catch (error) {
        console.error('Error generating field report:', error);
        addMessageToChat('bot', `Error generating field report: ${error.message}`);
    } finally {
        hideLoadingSpinner();
    }
}

function showLoadingSpinner() {
    loadingSpinner.classList.remove('hidden');
}

function hideLoadingSpinner() {
    loadingSpinner.classList.add('hidden');
}

// Initialize the application
function init() {
    initializeSpeechRecognition();
    addMessageToChat('bot', 'Welcome! Please provide information about the medical procedure. You can start by telling me the patient\'s name and age.');
    updateProgressBars();
    updateCompletionBoxes();
}

// Run initialization
init();
