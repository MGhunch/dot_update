from flask import Flask, request, jsonify
from anthropic import Anthropic
import httpx
import json
import os
from datetime import datetime, date, timedelta

app = Flask(__name__)

# Custom HTTP client for Anthropic
custom_http_client = httpx.Client(
    timeout=60.0,
    follow_redirects=True
)

client = Anthropic(
    api_key=os.environ.get('ANTHROPIC_API_KEY'),
    http_client=custom_http_client
)

# Airtable config
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY')
AIRTABLE_BASE_ID = 'app8CI7NAZqhQ4G1Y'
AIRTABLE_PROJECTS_TABLE = 'Projects'

# Load prompt from file
with open('prompt.txt', 'r') as f:
    UPDATE_PROMPT = f.read()


def strip_markdown_json(content):
    """Strip markdown code blocks from Claude's JSON response"""
    content = content.strip()
    if content.startswith('```'):
        content = content.split('\n', 1)[1] if '\n' in content else content[3:]
    if content.endswith('```'):
        content = content.rsplit('```', 1)[0]
    return content.strip()


def get_working_days_from_today(days=5):
    """Calculate a date N working days from today"""
    current = date.today()
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Monday = 0, Friday = 4
            added += 1
    return current.isoformat()


def get_project_by_job_number(job_number):
    """Fetch a project record by job number"""
    if not AIRTABLE_API_KEY:
        return None, None
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        search_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}"
        params = {'filterByFormula': f"{{Job Number}}='{job_number}'"}
        
        response = httpx.get(search_url, headers=headers, params=params, timeout=10.0)
        response.raise_for_status()
        
        records = response.json().get('records', [])
        
        if not records:
            print(f"Job '{job_number}' not found in Airtable")
            return None, None
        
        record = records[0]
        return record['id'], record['fields']
        
    except Exception as e:
        print(f"Error fetching project: {e}")
        return None, None


def update_project_in_airtable(record_id, updates):
    """Update a project record in Airtable"""
    if not AIRTABLE_API_KEY or not record_id:
        return False
    
    try:
        headers = {
            'Authorization': f'Bearer {AIRTABLE_API_KEY}',
            'Content-Type': 'application/json'
        }
        
        update_url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_PROJECTS_TABLE}/{record_id}"
        update_data = {'fields': updates}
        
        response = httpx.patch(update_url, headers=headers, json=update_data, timeout=10.0)
        response.raise_for_status()
        
        print(f"Updated project record: {record_id}")
        return True
        
    except Exception as e:
        print(f"Error updating project: {e}")
        return False


# ===================
# UPDATE ENDPOINT
# ===================
@app.route('/update', methods=['POST'])
def update():
    """Process job updates"""
    try:
        data = request.get_json()
        email_content = data.get('emailContent', '')
        job_number = data.get('jobNumber', '')
        
        if not email_content:
            return jsonify({'error': 'No email content provided'}), 400
        
        if not job_number:
            return jsonify({'error': 'No job number provided'}), 400
        
        # Fetch current project data from Airtable
        project_record_id, current_data = get_project_by_job_number(job_number)
        
        if not project_record_id:
            return jsonify({
                'error': 'Job not found',
                'jobNumber': job_number
            }), 404
        
        # Build context for Claude
        current_context = f"""
Current job data:
- Job Number: {job_number}
- Project Name: {current_data.get('Project Name', 'Unknown')}
- Stage: {current_data.get('Stage', 'Unknown')}
- Status: {current_data.get('Status', 'Unknown')}
- With Client: {current_data.get('With Client?', False)}
- Current Update: {current_data.get('Update', 'None')}
"""
        
        # Call Claude with Update prompt
        response = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=1500,
            temperature=0.2,
            system=UPDATE_PROMPT,
            messages=[
                {'role': 'user', 'content': f'{current_context}\n\nEmail content:\n\n{email_content}'}
            ]
        )
        
        # Parse Claude's JSON response
        content = response.content[0].text
        content = strip_markdown_json(content)
        analysis = json.loads(content)
        
        # Ensure update_due is always set
        update_due = analysis.get('updateDue') or get_working_days_from_today(5)
        
        # Build Airtable update payload (only include non-null changes)
        airtable_updates = {}
        
        if analysis.get('stage'):
            airtable_updates['Stage'] = analysis['stage'].title()
        
        if analysis.get('status'):
            airtable_updates['Status'] = analysis['status'].title()
            airtable_updates['Status Changed'] = datetime.now().isoformat()
        
        if analysis.get('withClient') is not None:
            airtable_updates['With Client?'] = analysis['withClient']
        
        if analysis.get('updateSummary'):
            airtable_updates['Update'] = analysis['updateSummary']
            airtable_updates['Update due'] = update_due
        
        # Apply updates to Airtable Projects table
        update_success = False
        if airtable_updates:
            update_success = update_project_in_airtable(project_record_id, airtable_updates)
        
        # Return complete response
        return jsonify({
            'jobNumber': job_number,
            'projectName': current_data.get('Project Name', ''),
            'previousStage': current_data.get('Stage', ''),
            'previousStatus': current_data.get('Status', ''),
            'newStage': analysis.get('stage'),
            'newStatus': analysis.get('status'),
            'withClient': analysis.get('withClient'),
            'updateSummary': analysis.get('updateSummary', ''),
            'updateDue': update_due,
            'hasBlocker': analysis.get('hasBlocker', False),
            'blockerNote': analysis.get('blockerNote'),
            'confidence': analysis.get('confidence', 'MEDIUM'),
            'confidenceNote': analysis.get('confidenceNote'),
            'teamsMessage': analysis.get('teamsMessage', {}),
            'airtableUpdated': update_success,
            'fieldsUpdated': list(airtable_updates.keys())
        })
        
    except json.JSONDecodeError as e:
        return jsonify({
            'error': 'Claude returned invalid JSON',
            'details': str(e),
            'raw_response': content
        }), 500
    except Exception as e:
        return jsonify({
            'error': 'Internal server error',
            'details': str(e)
        }), 500


# ===================
# HEALTH CHECK
# ===================
@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Dot Update',
        'endpoints': ['/update', '/health']
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
