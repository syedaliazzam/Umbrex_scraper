import os
import sys
import imaplib
import email
import hashlib
import json
from email.header import decode_header
from dotenv import load_dotenv

# Ensure UTF-8 output on all platforms (fixes Windows emoji crash)
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

# Load env variables from local .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

EMAIL = os.getenv("UMBREX_EMAIL", "").replace("gamil.com", "gmail.com") # Safe fallback for gamil typo
PASSWORD = os.getenv("UMBREX_IMAP_PASSWORD", "")
IMAP_SERVER = "imap.gmail.com"

def fetch_latest_email():
    print(f"Connecting to {IMAP_SERVER} using account {EMAIL}...")
    try:
        # Connect to server
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL, PASSWORD)
        mail.select("inbox")
        
        # Search specifically for emails from will.bachman@umbrex.com
        # You can add a subject filter too, e.g., SUBJECT "project opportunities"
        search_criterion = 'FROM "will.bachman@umbrex.com"'
        print(f"Searching inbox for criteria: {search_criterion}...")
        status, messages = mail.search(None, search_criterion)
        
        # Fallback for testing: search for "Veritux" in subject if no direct emails exist
        if status != "OK" or not messages[0]:
            print("  No direct emails from will.bachman@umbrex.com found in inbox.")
            search_criterion = 'SUBJECT "Veritux"'
            print(f"🔍 Falling back to test search: {search_criterion}...")
            status, messages = mail.search(None, search_criterion)
            
        if status != "OK" or not messages[0]:
            print("⚠️ No emails found matching the sender or fallback criteria.")
            return None
            
        email_ids = messages[0].split()
        latest_email_id = email_ids[-1] # Get the most recent email
        print(f"Found {len(email_ids)} matching emails. Fetching latest ID: {latest_email_id.decode()}...")
        
        # Fetch the email data
        res, msg_data = mail.fetch(latest_email_id, "(RFC822)")
        if res != "OK":
            print("❌ Failed to fetch email data.")
            return None
            
        for response_part in msg_data:
            if isinstance(response_part, tuple):
                msg = email.message_from_bytes(response_part[1])
                
                # Decode Subject
                subject, encoding = decode_header(msg["Subject"])[0]
                if isinstance(subject, bytes):
                    subject = subject.decode(encoding or "utf-8", errors="ignore")
                
                # Get Date
                date = msg.get("Date")
                print(f"\n📬 EMAIL METADATA:")
                print(f"  From   : {msg.get('From')}")
                print(f"  Subject: {subject}")
                print(f"  Date   : {date}")
                
                # Extract Text/HTML Body
                body = ""
                html_body = ""
                
                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        content_disposition = str(part.get("Content-Disposition"))
                        
                        try:
                            payload = part.get_payload(decode=True)
                            if not payload:
                                continue
                            decoded_payload = payload.decode(errors="ignore")
                        except Exception as e:
                            print(f"  ⚠️ Error decoding part: {e}")
                            continue
                            
                        if content_type == "text/plain" and "attachment" not in content_disposition:
                            body += decoded_payload
                        elif content_type == "text/html" and "attachment" not in content_disposition:
                            html_body += decoded_payload
                else:
                    try:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            body = payload.decode(errors="ignore")
                    except Exception as e:
                        print(f"  ⚠️ Error decoding non-multipart body: {e}")
                
                # Return plain text if available, otherwise html
                final_body = body if body.strip() else html_body
                
                # Locate Project Opportunities section
                project_section = ""
                idx = final_body.lower().rfind("project opportunities")
                if idx != -1:
                    project_section = final_body[idx:]
                    
                    # Find where projects section ends
                    cut_markers = [
                        "event schedule",
                        "in-person mixers",
                        "thought leadership",
                        "#welcomewednesday",
                        "welcome wednesday",
                        "useful links"
                    ]
                    
                    earliest_idx = -1
                    for marker in cut_markers:
                        m_idx = project_section.lower().find(marker, 100) # skip initial header text
                        if m_idx != -1:
                            if earliest_idx == -1 or m_idx < earliest_idx:
                                earliest_idx = m_idx
                                
                    if earliest_idx != -1:
                        project_section = project_section[:earliest_idx]
                else:
                    project_section = final_body
                
                # --- STRUCTURED PARSING LOGIC ---
                import re
                
                # Split text into projects using numbering pattern like "1. ", "*1. ", "17. " etc.
                project_blocks = re.split(r'\n\*?(\d+)\.\s+', "\n" + project_section)
                
                parsed_projects = []
                # re.split returns [prefix_text, number1, block1, number2, block2, ...]
                if len(project_blocks) > 2:
                    for i in range(1, len(project_blocks), 2):
                        num = project_blocks[i]
                        block_text = project_blocks[i+1] if i+1 < len(project_blocks) else ""
                        if not block_text.strip():
                            continue
                            
                        # Clean up markdown formatting (like asterisks) to make regex matching robust
                        clean_block = block_text.replace("*", "")
                        
                        # Find title line from the original lines
                        lines = [l.strip() for l in block_text.splitlines() if l.strip()]
                        if not lines:
                            continue
                            
                        title = lines[0].strip("*").strip()
                        
                        # Find metadata fields using regex on the cleaned block
                        def extract_field(pattern, text):
                            m = re.search(pattern, text, re.IGNORECASE)
                            return m.group(1).strip() if m else "Not specified"
                            
                        start = extract_field(r'Start:\s*(.*)', clean_block)
                        duration = extract_field(r'Duration:\s*(.*)', clean_block)
                        commitment = extract_field(r'Time\s*commitment:\s*(.*)', clean_block)
                        location = extract_field(r'Location:\s*(.*)', clean_block)
                        rate = extract_field(r'Expected\s*rate:\s*(.*)', clean_block)
                        proj_id = extract_field(r'Project\s*ID\s*#?:\s*([^\s<]+)', clean_block)
                        
                        # Extract description: everything between title and first metadata field (or mailto link)
                        desc_lines = []
                        for line in lines[1:]:
                            clean_line = line.replace("*", "").strip()
                            if any(clean_line.startswith(prefix) for prefix in ["Start:", "Language:", "Duration:", "Time commitment:", "Location:", "Expected rate:", "Project ID#:", "I'm interested"]):
                                break
                            desc_lines.append(line)
                        description = " ".join(desc_lines).strip()
                        
                        parsed_projects.append({
                            "number": num,
                            "id": f"umbrex-{proj_id}" if proj_id != "Not specified" else f"umbrex-hash-{hashlib.md5(title.encode()).hexdigest()[:8]}",
                            "project_id_raw": proj_id,
                            "title": title,
                            "description": description,
                            "start": start,
                            "duration": duration,
                            "commitment": commitment,
                            "location": location,
                            "rate": rate,
                            "url": f"mailto:projects@veritux.com?subject=I'm interested in Project ID%23 {proj_id}" if proj_id != "Not specified" else "projects@veritux.com"
                        })
                
                print(f"\n🎯 SUCCESSFULLY PARSED {len(parsed_projects)} PROJECTS FROM EMAIL:")
                print("============================================================")
                print(json.dumps(parsed_projects, indent=2, ensure_ascii=False))
                print("============================================================\n")
                
                # Connect to MongoDB and insert projects
                mongo_uri = os.getenv("MONGO_URI")
                if mongo_uri:
                    print("🔌 Connecting to MongoDB...")
                    try:
                        from pymongo import MongoClient, UpdateOne
                        from datetime import datetime
                        client = MongoClient(mongo_uri)
                        db = client["office_monitor"]
                        collection = db["projects"]
                        
                        # Create unique index if not exists
                        try:
                            collection.create_index("project_id", unique=True)
                        except:
                            pass
                            
                        ops = []
                        detected_at_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        for p in parsed_projects:
                            doc = {
                                "project_id":       p["id"],
                                "title":            p["title"],
                                "description":      p["description"] + f"\n\nStart: {p['start']}\nDuration: {p['duration']}\nCommitment: {p['commitment']}\nLocation: {p['location']}\nExpected Rate: {p['rate']}",
                                "location":         p["location"],
                                "budget":           p["rate"],
                                "duration":         p["duration"],
                                "time_posted":      "Recently",
                                "url":              p["url"],
                                "detected_at":      detected_at_str,
                                "platform":         "umbrex",
                                "inserted_to_sheet": False,
                                "emailed":          True # Suppress separate emails since already received via email
                            }
                            # Upsert
                            ops.append(UpdateOne({"project_id": doc["project_id"]}, {"$setOnInsert": doc}, upsert=True))
                            
                        if ops:
                            res = collection.bulk_write(ops, ordered=False)
                            print(f"🎉 DB: Seeded {res.upserted_count} new projects to collection (matched {res.matched_count} existing).")
                    except Exception as ex:
                        print(f"❌ Failed to insert to MongoDB: {ex}")
                else:
                    print("⚠️ MONGO_URI not found in env. Skipping DB insertion.")
                
                return parsed_projects
                
    except imaplib.IMAP4.error as e:
        print(f"❌ IMAP Authentication/Connection failed: {e}")
        print("  Make sure your App Password is correct and IMAP is enabled in your Gmail settings.")
    except Exception as e:
        print(f"❌ Error occurred: {e}")
    return None

if __name__ == "__main__":
    fetch_latest_email()
