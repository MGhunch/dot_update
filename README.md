# Dot Update

Hunch job update processor. Part of the Dot World ecosystem.

## Endpoints

- `POST /update` - Process job update emails
- `GET /health` - Health check

## Input

```json
{
  "jobNumber": "ONE 090",
  "emailContent": "Email body text..."
}
```

## Output

Returns parsed update with:
- Stage/status changes
- Update summary
- Due date
- Teams message (subject + body)
- Airtable update confirmation

## Environment Variables

- `ANTHROPIC_API_KEY` - Claude API key
- `AIRTABLE_API_KEY` - Airtable API key
- `PORT` - Server port (default 8080)

## Files

- `app.py` - Main application
- `prompt.txt` - Claude prompt for update parsing
