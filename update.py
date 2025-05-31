import json
from pathlib import Path

INPUT_JSON_FILE = Path("arpitingle_tweets.json")
OUTPUT_TXT_FILE = Path("speaking_style.txt")

def main():
    # 1. Check if input JSON exists
    if not INPUT_JSON_FILE.exists():
        print(f"Error: Input file '{INPUT_JSON_FILE}' not found.")
        return
    if not INPUT_JSON_FILE.is_file():
        print(f"Error: '{INPUT_JSON_FILE}' is not a file.")
        return

    # 2. Read and parse JSON
    try:
        with open(INPUT_JSON_FILE, 'r', encoding='utf-8') as f:
            tweets_data = json.load(f)
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from '{INPUT_JSON_FILE}'. Make sure it's valid JSON.")
        return
    except Exception as e:
        print(f"Error reading '{INPUT_JSON_FILE}': {e}")
        return

    # 3. Validate JSON structure (should be a list)
    if not isinstance(tweets_data, list):
        print(f"Error: Expected a list of tweets in '{INPUT_JSON_FILE}', but got {type(tweets_data)}.")
        return

    # 4. Extract texts and prepare for writing
    new_style_entries = []
    for i, tweet in enumerate(tweets_data):
        if isinstance(tweet, dict):
            text_content = tweet.get("text")
            if text_content is not None and isinstance(text_content, str):
                # Escape any pre-existing double quotes within the text itself
                # to avoid breaking the outer quotes in the speaking_style.txt format.
                # Also, escape backslashes that might be part of the text.
                processed_text = text_content.replace('\\', '\\\\').replace('"', '\\"')
                # Add indentation to match the existing style file format
                formatted_entry = f'  "{processed_text}",\n'
                new_style_entries.append(formatted_entry)
            else:
                print(f"Warning: Tweet at index {i} is missing 'text' field or it's not a string. Skipping.")
        else:
            print(f"Warning: Item at index {i} in '{INPUT_JSON_FILE}' is not a tweet object (dictionary). Skipping.")


    # 5. Append to output TXT file
    if not new_style_entries:
        print("No new tweet texts found to add to speaking_style.txt.")
        return

    try:
        with open(OUTPUT_TXT_FILE, 'a', encoding='utf-8') as f:
            # If the file is not empty and doesn't end with a newline, add one.
            # Also, check if it ends with a comma and newline, if not, add a comma before the newline.
            # This is to ensure the new entries are correctly formatted as a continuation of a list.
            # For simplicity, this script assumes if you run it multiple times, the last line of
            # speaking_style.txt might be a valid entry ending with ',\n' or it might be incomplete.
            # A more robust solution would parse existing lines, but append is requested.

            # Let's check if the file is empty or if the last character is a newline.
            # If not, add a newline. This is a basic check.
            # A truly robust append to a comma-separated list like this is tricky without
            # reading and rewriting the whole file or at least the last line.
            # For now, we just append. If the file was manually edited and the last
            # entry is missing its comma and newline, this won't fix it.
            # This script primarily focuses on adding NEW entries correctly.

            for entry in new_style_entries:
                f.write(entry)
        print(f"Successfully appended {len(new_style_entries)} tweet texts to '{OUTPUT_TXT_FILE}'.")
    except Exception as e:
        print(f"Error writing to '{OUTPUT_TXT_FILE}': {e}")

if __name__ == "__main__":
    main()
