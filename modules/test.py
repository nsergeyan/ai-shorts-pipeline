import time

from google import genai
def evaluate_video_with_genai():
    client = genai.Client(api_key="AIzaSyBovTpWVnz7JU2jeiusfRlnWYWb-x8vgEw")

    # Upload video
    uploaded_file = client.files.upload(file="/Users/nareksergeyan/YOutuber/data/gameplay/videoplayback.1771416971682.publer.com.mp4")
    print(f"Uploaded file: {uploaded_file.name}")

    # Wait until file is ACTIVE
    file_info = client.files.get(name=uploaded_file.name)
    while file_info.state != "ACTIVE":
        print(f"File state: {file_info.state}, waiting...")
        time.sleep(2)
        file_info = client.files.get(name=uploaded_file.name)
    print("File is ACTIVE ✅")

    # Build prompt
    prompt = f"""
    is there a dog titan(NOT CART TITAN) in background? if yes give timestamps
    """

    # Send request
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[uploaded_file, prompt]
    )

    print(f"Response: {response}")

print(evaluate_video_with_genai())

