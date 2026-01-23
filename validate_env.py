"""Script to validate .env file configuration."""
import os
import json
import sys
from dotenv import load_dotenv

load_dotenv()


def validate_env():
    """Validate environment variables and provide helpful error messages."""
    errors = []
    warnings = []
    
    print("Validating .env file configuration...\n")
    
    # Check required variables
    required_vars = {
        "GOOGLE_API_KEY": os.getenv("GOOGLE_API_KEY"),
        "DISCORD_BOT_TOKEN": os.getenv("DISCORD_BOT_TOKEN"),
        "GOOGLE_SHEETS_ID": os.getenv("GOOGLE_SHEETS_ID"),
    }
    
    for var_name, var_value in required_vars.items():
        if not var_value:
            errors.append(f"❌ Missing required variable: {var_name}")
        else:
            print(f"✅ {var_name} is set")
    
    # Check Google Sheets authentication
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE")
    service_account_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    
    if creds_file:
        if os.path.exists(creds_file):
            print(f"✅ GOOGLE_CREDENTIALS_FILE points to existing file: {creds_file}")
            # Try to validate JSON
            try:
                with open(creds_file, 'r') as f:
                    json.load(f)
                print(f"✅ Service account JSON file is valid")
            except json.JSONDecodeError as e:
                errors.append(f"❌ Invalid JSON in {creds_file}: {e}")
            except Exception as e:
                errors.append(f"❌ Error reading {creds_file}: {e}")
        else:
            errors.append(f"❌ GOOGLE_CREDENTIALS_FILE points to non-existent file: {creds_file}")
    elif service_account_json:
        print("⚠️  GOOGLE_SERVICE_ACCOUNT_JSON is set (using file path is recommended)")
        try:
            json.loads(service_account_json)
            print("✅ GOOGLE_SERVICE_ACCOUNT_JSON contains valid JSON")
        except json.JSONDecodeError as e:
            errors.append(f"❌ Invalid JSON in GOOGLE_SERVICE_ACCOUNT_JSON: {e}")
            errors.append("   Tip: Use GOOGLE_CREDENTIALS_FILE with a file path instead")
    else:
        errors.append("❌ No Google Sheets authentication method found")
        errors.append("   Set either GOOGLE_CREDENTIALS_FILE or GOOGLE_SERVICE_ACCOUNT_JSON")
    
    # Optional variables
    if os.getenv("GOOGLE_CALENDAR_ID"):
        print("✅ GOOGLE_CALENDAR_ID is set (optional)")
    else:
        warnings.append("⚠️  GOOGLE_CALENDAR_ID not set (optional, for future calendar features)")
    
    # Print results
    print("\n" + "="*60)
    if errors:
        print("\n❌ ERRORS FOUND:")
        for error in errors:
            print(f"  {error}")
        print("\nPlease fix these errors before running the bot.")
        return False
    else:
        print("\n✅ All required configuration is valid!")
        if warnings:
            print("\n⚠️  WARNINGS:")
            for warning in warnings:
                print(f"  {warning}")
        return True


if __name__ == "__main__":
    success = validate_env()
    sys.exit(0 if success else 1)

