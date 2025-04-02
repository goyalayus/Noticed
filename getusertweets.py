import asyncio
import json
import os
from twikit import Client
# import traceback # Optional: uncomment for more detailed error printing during debugging

# --- Credentials ---
# <<< MAKE SURE THESE ARE 100% CORRECT >>>
USERNAME = "@A22110009"
EMAIL = "ayush_g@ar.iitr.ac.in"
PASSWORD = "freedom_0207"  # <<< DOUBLE-CHECK THIS PASSWORD >>>
# Use a distinct file name for cookies
COOKIES_FILE = 'cookies.json'

# --- Target User ---
# <<< CHANGE THIS to the screen name (without '@') of the user whose tweets you want >>>
TARGET_USER_SCREEN_NAME = 'arpitingle'

# --- Configuration ---
# Type of tweets to fetch: 'Tweets', 'Tweets & Replies', 'Media'
TWEET_TYPE = 'Tweets'
# Delay between fetching pages (in seconds) to respect rate limits
PAGE_FETCH_DELAY = 2

# Initialize client
client = Client('en-US')

# --- Tweet Fetching Function ---
async def fetch_all_tweets(user):
    """Fetches all available tweets for a given user object."""
    all_tweets = []
    # Use getattr for safety when accessing attributes
    screen_name = getattr(user, 'screen_name', '[unknown screen name]')
    statuses_count = getattr(user, 'statuses_count', '[unknown]')

    print(f"\nStarting tweet fetch for @{screen_name} ({TWEET_TYPE})...")
    print(f"Profile reports {statuses_count} tweets.")
    print(f"Note: API limitations might prevent fetching all historical tweets.")

    try:
        # Get the first batch/page of tweets
        current_tweets_batch = await user.get_tweets(TWEET_TYPE)
        batch_count = 0

        while current_tweets_batch:
            batch_count += 1
            batch_size = len(current_tweets_batch)
            all_tweets.extend(current_tweets_batch)
            print(f"Fetched batch {batch_count} ({batch_size} tweets). Total fetched: {len(all_tweets)}")

            # --- Rate Limiting Delay ---
            # print(f"Waiting for {PAGE_FETCH_DELAY} seconds before next fetch...")
            await asyncio.sleep(PAGE_FETCH_DELAY)

            # Get the next batch of tweets
            current_tweets_batch = await current_tweets_batch.next()

        print(f"\nFinished fetching. Retrieved {len(all_tweets)} tweets.")

    except Exception as e:
        print(f"\nAn error occurred during tweet fetching: {e}")
        print(f"Fetched {len(all_tweets)} tweets before the error.")
        # Optional: uncomment below for detailed error info during fetching
        # print("Detailed fetch error:")
        # traceback.print_exc()

    return all_tweets

# --- Main Function ---
async def main():
    print("Attempting to login...")
    try:
        # Use the cookies_file argument directly in login
        await client.login(
            auth_info_1=USERNAME,
            auth_info_2=EMAIL,
            password=PASSWORD,
            cookies_file=COOKIES_FILE # Let twikit handle cookie loading/saving
        )
        print(f"Login successful (or using existing session from {COOKIES_FILE}).")

    except Exception as e:
        # This will catch login errors, including wrong password
        print(f"Login failed: {e}")
        print("\n--- Troubleshooting ---")
        print("1. Double-check your USERNAME, EMAIL, and ESPECIALLY PASSWORD variables.")
        print(f"2. Check if the '{COOKIES_FILE}' is corrupted (try deleting it).")
        print("3. Twitter might require extra verification (CAPTCHA) - twikit might not handle all cases.")
        print("-----------------------\n")
        # Optional: uncomment below for detailed error info during login
        # print("Detailed login error:")
        # traceback.print_exc()
        return # Exit if login fails

    # --- Get Target User ---
    user = None # Initialize user to None
    print(f"\nFetching user profile for @{TARGET_USER_SCREEN_NAME}...")
    try:
        user = await client.get_user_by_screen_name(TARGET_USER_SCREEN_NAME)
        if not user:
            print(f"User @{TARGET_USER_SCREEN_NAME} not found.")
            return

        # Use getattr for safe attribute access when printing user info
        user_id = getattr(user, 'id', 'N/A')
        user_name = getattr(user, 'name', 'N/A')
        followers_count = getattr(user, 'followers_count', 'N/A')
        # Try 'friends_count', provide default 'N/A' if missing
        following_count = getattr(user, 'friends_count', 'N/A')
        statuses_count = getattr(user, 'statuses_count', 'N/A')

        print(f"Found user: {user_name} (ID: {user_id})")
        print(f"Followers: {followers_count}")
        print(f"Following: {following_count}") # Safely prints 'N/A' if missing
        print(f"Tweets reported: {statuses_count}")

    except Exception as e:
        print(f"Failed to get user profile: {e}")
        # Optional: uncomment below for more detailed debugging info
        # print("Detailed get user error:")
        # traceback.print_exc()
        return

    # --- Fetch Tweets (only if user object was successfully retrieved) ---
    if user:
        all_user_tweets = await fetch_all_tweets(user)

        # --- Process Results ---
        if all_user_tweets:
            print(f"\nSuccessfully retrieved {len(all_user_tweets)} tweets for @{TARGET_USER_SCREEN_NAME}.")

            print("\n--- Sample of first 5 tweets ---")
            for i, tweet in enumerate(all_user_tweets[:5]):
                # Use getattr for safety when printing tweet info
                tweet_text = getattr(tweet, 'text', 'N/A')
                tweet_id = getattr(tweet, 'id', 'N/A')
                print(f"{i+1}. ID: {tweet_id} | Text: {tweet_text[:100]}...") # Truncate long text

            # --- Save tweets to JSON ---
            output_filename = f"{TARGET_USER_SCREEN_NAME}_tweets.json"
            print(f"\nSaving tweet data to {output_filename}...")
            try:
                tweet_data_list = []
                for tweet in all_user_tweets:
                    # Manually construct a dictionary for each tweet using getattr
                    # This avoids the 'Tweet' object has no attribute 'data' error
                    tweet_dict = {
                        'id': getattr(tweet, 'id', None),
                        'text': getattr(tweet, 'text', None),
                        # Convert datetime to string for JSON compatibility
                        'created_at': str(getattr(tweet, 'created_at', None)),
                        'user_id': getattr(tweet.user, 'id', None) if hasattr(tweet, 'user') else None,
                        'user_screen_name': getattr(tweet.user, 'screen_name', None) if hasattr(tweet, 'user') else None,
                        'retweet_count': getattr(tweet, 'retweet_count', 0),
                        'favorite_count': getattr(tweet, 'favorite_count', 0), # Often referred to as likes
                        'reply_count': getattr(tweet, 'reply_count', 0),
                        'quote_count': getattr(tweet, 'quote_count', 0),
                        'lang': getattr(tweet, 'lang', None),
                        # Extract basic media info (URLs) - adjust if needed based on twikit's media object structure
                        'media_urls': [getattr(m, 'media_url_https', getattr(m, 'url', None))
                                       for m in getattr(tweet, 'media', []) if hasattr(m, 'media_url_https') or hasattr(m, 'url')],
                        # Extract basic URL info - adjust if needed
                        'expanded_urls': [getattr(u, 'expanded_url', getattr(u, 'url', None))
                                         for u in getattr(tweet, 'urls', []) if hasattr(u, 'expanded_url') or hasattr(u, 'url')],
                        # Add other potentially relevant fields using getattr
                        'in_reply_to_status_id': getattr(tweet, 'in_reply_to_status_id', None),
                        'in_reply_to_user_id': getattr(tweet, 'in_reply_to_user_id', None),
                        'is_quote_status': getattr(tweet, 'is_quote_status', False),
                        'quoted_status_id': getattr(tweet, 'quoted_status_id', None),
                        # You can add more fields by inspecting the `tweet` object attributes
                        # (e.g., using print(dir(tweet)) on one tweet)
                    }
                    # Remove keys with None values if desired, for cleaner JSON
                    # tweet_dict = {k: v for k, v in tweet_dict.items() if v is not None}
                    tweet_data_list.append(tweet_dict)

                # Write the list of dictionaries to the JSON file
                with open(output_filename, 'w', encoding='utf-8') as f:
                    json.dump(tweet_data_list, f, ensure_ascii=False, indent=2)
                print(f"Successfully saved tweets to {output_filename}")

            except Exception as e:
                print(f"Error saving tweets to JSON: {e}")
                # Optional: uncomment below for detailed error info during saving
                # print("Detailed saving error:")
                # traceback.print_exc()
        else:
            print(f"\nNo tweets were retrieved for @{TARGET_USER_SCREEN_NAME}.")
    else:
         # This case should be caught earlier, but added for completeness
         print(f"Cannot fetch tweets because user @{TARGET_USER_SCREEN_NAME} was not loaded.")


# --- Run the async main function ---
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
