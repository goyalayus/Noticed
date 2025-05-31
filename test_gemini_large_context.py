import google.generativeai as genai
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv
# We might not need to directly import generation_types.FinishReason if comparing by value or string representation
from google.generativeai import types as generation_types # Keep for other type hints if needed

# --- Configuration ---
BLOG_FILE_PATH = Path("blogs.txt")
MODEL_NAME = 'gemini-2.5-flash-preview-04-17'

# Simplified prompt for testing
TEST_PROMPT_TEMPLATE = """
Your knowledge base consists of the following blog posts:
--- START BLOG CONTENT ---
{blog_content}
--- END BLOG CONTENT ---

Based ONLY on the information in the blog content above, what are the main differences discussed between Snabbit and Urban Company?
If the information is not present, state that.
Keep your answer concise.
"""

# Safety settings
SAFETY_SETTINGS = {
    generation_types.HarmCategory.HARM_CATEGORY_HARASSMENT: generation_types.HarmBlockThreshold.BLOCK_NONE,
    generation_types.HarmCategory.HARM_CATEGORY_HATE_SPEECH: generation_types.HarmBlockThreshold.BLOCK_NONE,
    generation_types.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: generation_types.HarmBlockThreshold.BLOCK_NONE,
    generation_types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: generation_types.HarmBlockThreshold.BLOCK_NONE,
}

async def load_file_content(file_path: Path) -> str:
    if not file_path.is_file():
        print(f"Error: File not found at {file_path}")
        return ""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        print(f"Successfully loaded content from {file_path} ({len(content)} bytes)")
        return content
    except Exception as e:
        print(f"Error loading content from {file_path}: {e}")
        return ""

async def main():
    load_dotenv()
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        print("Error: GEMINI_API_KEY not found.")
        return

    genai.configure(api_key=api_key)

    print(f"\n--- Fetching Model Info for: {MODEL_NAME} ---")
    model_info_retrieved = None
    try:
        model_info_retrieved = genai.get_model(f'models/{MODEL_NAME}')
        if model_info_retrieved:
            print(f"Model Display Name: {model_info_retrieved.display_name}")
            print(f"Input Token Limit: {model_info_retrieved.input_token_limit}")
            print(f"Output Token Limit: {model_info_retrieved.output_token_limit}")
        else:
            print(f"Could not retrieve info for model {MODEL_NAME}")
            return
    except Exception as e:
        print(f"Error getting model information for {MODEL_NAME}: {e}")
        return

    print(f"\n--- Loading Blog Content from: {BLOG_FILE_PATH} ---")
    blog_content_text = await load_file_content(BLOG_FILE_PATH)
    if not blog_content_text:
        print("Cannot proceed without blog content.")
        return

    full_test_prompt = TEST_PROMPT_TEMPLATE.format(blog_content=blog_content_text)
    print(f"\n--- Prompt Constructed (first 200 chars): ---")
    print(full_test_prompt[:200] + "...")
    print(f"... (Total prompt length: {len(full_test_prompt)} characters)")

    model = genai.GenerativeModel(MODEL_NAME)

    print(f"\n--- Counting Input Tokens for the Constructed Prompt ---")
    try:
        count_tokens_response = model.count_tokens(full_test_prompt)
        actual_input_tokens = getattr(count_tokens_response, 'total_tokens', 'N/A')
        print(f"Estimated Input Tokens by count_tokens(): {actual_input_tokens}")
        if isinstance(actual_input_tokens, int) and model_info_retrieved and \
           actual_input_tokens > model_info_retrieved.input_token_limit:
            print(f"WARNING: Estimated input tokens ({actual_input_tokens}) EXCEED model's input token limit ({model_info_retrieved.input_token_limit})!")
    except Exception as e:
        print(f"Error counting tokens: {e}")

    print(f"\n--- Attempting to Generate Content with Large Context (Model: {MODEL_NAME}) ---")
    try:
        response = await model.generate_content_async(
            contents=full_test_prompt,
            safety_settings=SAFETY_SETTINGS,
            generation_config=generation_types.GenerationConfig(
                max_output_tokens=250,
                temperature=0.5
            )
        )

        print("\n--- Gemini API Response ---")
        generated_text = "No text generated or response was blocked."
        finish_reason_val = "N/A"
        prompt_feedback_str = "N/A"

        # It's good practice to check if response and response.candidates exist
        if response and response.candidates:
            candidate = response.candidates[0]
            # candidate.finish_reason is an enum, e.g. FinishReason.STOP
            # We can get its name for a more readable string or its value (integer)
            finish_reason_name = candidate.finish_reason.name # e.g., "STOP", "MAX_TOKENS"
            finish_reason_val = candidate.finish_reason.value # e.g., 1, 2

            print(f"Finish Reason Name: {finish_reason_name}") # Log the name
            print(f"Finish Reason Value: {finish_reason_val}")   # Log the integer value

            if finish_reason_name == "STOP": # Compare with the string name
                try:
                    generated_text = response.text
                except ValueError as ve:
                    generated_text = f"Error accessing response.text: {ve}. Likely blocked."
                    if candidate.content and candidate.content.parts:
                        generated_text += f" Parts: {[part.text for part in candidate.content.parts if hasattr(part, 'text')]}"
                    else:
                        generated_text += " No valid parts found in candidate."
            elif finish_reason_name == "MAX_TOKENS":
                generated_text = "Generation stopped due to MAX_TOKENS. Output might be incomplete."
                try: generated_text += f" Partial: {response.text}"
                except: pass # response.text might error if no valid part due to MAX_TOKENS
            elif finish_reason_name == "SAFETY":
                generated_text = f"Generation stopped due to SAFETY. Ratings: {candidate.safety_ratings}"
            else: # Other reasons like RECITATION, OTHER
                generated_text = f"Generation stopped. Finish Reason: {finish_reason_name}."
        else:
            print("Response did not contain any candidates.")


        # This print statement was for the old variable name.
        # Let's keep it consistent or remove if the new ones above are sufficient.
        # print(f"Finish Reason: {finish_reason_val}") # This variable `finish_reason_val` now holds the integer value
                                                   # Or you can print `finish_reason_name`

        if hasattr(response, 'prompt_feedback') and response.prompt_feedback:
            prompt_feedback_str = (
                f"Block Reason: {response.prompt_feedback.block_reason}, "
                f"Safety Ratings: {response.prompt_feedback.safety_ratings}"
            )
        print(f"Prompt Feedback: {prompt_feedback_str}") # This is fine
        print("\nGenerated Text:")
        print("-----------------------------------------")
        print(generated_text)
        print("-----------------------------------------")

        if hasattr(response, 'usage_metadata'):
            print("\nUsage Metadata:")
            print(f"  Prompt Token Count (from metadata): {response.usage_metadata.prompt_token_count}")
            print(f"  Candidates Token Count: {response.usage_metadata.candidates_token_count}")
            print(f"  Total Token Count: {response.usage_metadata.total_token_count}")

    except Exception as e:
        print(f"An error occurred during content generation: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
