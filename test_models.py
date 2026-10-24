"""
Test different Gemini models to find the fastest
"""
import google.genai as genai
import os
import time
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

load_dotenv()
client = genai.Client(api_key=os.getenv('GEMINI_API_KEY'))

# Create a test image with text
img = Image.new('RGB', (800, 600), color='white')
img_bytes = BytesIO()
img.save(img_bytes, format='JPEG')
img_bytes.seek(0)
test_img = Image.open(img_bytes)

# Models to test (in order from fastest to slowest)
models_to_test = [
    'gemini-1.5-flash-8b',      # Fastest (if available)
    'gemini-1.5-flash',          # Fast and stable
    'gemini-1.5-flash-latest',   # Latest flash version
    'gemini-1.5-pro',            # More accurate but slower
]

print("="*80)
print("GEMINI MODEL SPEED TEST")
print("="*80)

test_prompt = "What is 2 + 2? Reply with only the number."

results = []

for model_name in models_to_test:
    try:
        print(f"\nTesting {model_name}...")
        
        t0 = time.time()
        response = client.models.generate_content(
            model=model_name,
            contents=[test_prompt, test_img]
        )
        elapsed = time.time() - t0
        
        print(f"  ✅ Response: {response.text.strip()}")
        print(f"  ⏱️  Time: {elapsed:.2f}s")
        
        results.append((model_name, elapsed, True))
        
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "NOT_FOUND" in error_msg:
            print(f"  ❌ Not available")
        else:
            print(f"  ❌ Error: {error_msg[:100]}")
        results.append((model_name, 999, False))

# Show summary
print("\n" + "="*80)
print("RESULTS - FASTEST TO SLOWEST:")
print("="*80)

working_models = [(m, t) for m, t, ok in results if ok]
working_models.sort(key=lambda x: x[1])

if working_models:
    for i, (model, elapsed) in enumerate(working_models, 1):
        print(f"{i}. {model:30} - {elapsed:.2f}s")
    
    print("\n" + "="*80)
    print(f"🏆 FASTEST MODEL: {working_models[0][0]}")
    print(f"   Use this in your bot for best speed!")
    print("="*80)
else:
    print("❌ No models worked! Check your API key.")

print("\n💡 RECOMMENDED FOR YOUR BOT:")
if working_models:
    fastest = working_models[0][0]
    print(f"   model='{fastest}'")
else:
    print("   model='gemini-1.5-flash'  # Default fallback")
